"""Model adapters for reviewed comic story drafts and text-free panel image candidates.

Configuration lives exclusively in server environment variables. No user-supplied
URLs, secrets, or remote image fetches are accepted by these adapters.
"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
import json
import os
from typing import Any

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError


class AIProviderError(Exception):
    """Safe, non-secret error intended for API clients."""


MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 30_000_000
CAMERA_CHOICES = {"远景", "全景", "中景", "近景", "特写", "俯拍", "仰拍"}


def _base(env_name: str) -> str:
    return os.getenv(env_name, "").strip().rstrip("/")


def _config(kind: str) -> tuple[str, str, str]:
    prefix = "STORY" if kind == "story" else "IMAGE"
    endpoint = _base(f"{prefix}_API_BASE_URL")
    model = os.getenv(f"{prefix}_MODEL", "").strip()
    key = os.getenv(f"{prefix}_API_KEY", "").strip()
    if not (endpoint and model):
        raise AIProviderError(f"{prefix} model not configured. Set {prefix}_API_BASE_URL and {prefix}_MODEL.")
    if not endpoint.startswith(("http://", "https://")):
        raise AIProviderError(f"{prefix}_API_BASE_URL must be an http(s) base URL.")
    if len(endpoint) > 500 or len(model) > 120:
        raise AIProviderError(f"{prefix} model configuration exceeds length limits.")
    return endpoint, model, key


def capability_status() -> dict[str, Any]:
    story_url, image_url = _base("STORY_API_BASE_URL"), _base("IMAGE_API_BASE_URL")
    story_model, image_model = os.getenv("STORY_MODEL", ""), os.getenv("IMAGE_MODEL", "")
    return {
        "story": {"ready": bool(story_url and story_model), "model": story_model, "method": "chat/completions", "preview_approval": True},
        "image": {"ready": bool(image_url and image_model), "model": image_model,
                  "reference_mode": reference_mode(), "method": "images/generations or images/edits",
                  "candidate_approval": True},
        "warning": "Single-user local development. External model calls can incur costs. Never expose this server publicly.",
    }


def reference_mode() -> str:
    value = os.getenv("IMAGE_REFERENCE_MODE", "off").strip().lower()
    return value if value in ("off", "edits") else "off"


def _request(endpoint: str, key: str, json_payload: dict | None = None,
             files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
             form: dict[str, str] | None = None) -> dict:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        if files is None:
            response = httpx.post(endpoint, json=json_payload, headers=headers, timeout=120, follow_redirects=False)
        else:
            response = httpx.post(endpoint, data=form, files=files, headers=headers, timeout=120, follow_redirects=False)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
        raise AIProviderError(f"Model service unavailable: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        # Never echo provider response: it may include bearer tokens or private prompts.
        raise AIProviderError(f"Model service returned HTTP {response.status_code}")
    if len(response.content) > MAX_JSON_BYTES * 15:
        raise AIProviderError("Model response exceeds size limit")
    try:
        obj = response.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise AIProviderError("Model response is not JSON") from exc
    if not isinstance(obj, dict):
        raise AIProviderError("Model response must be an object")
    return obj


def _parse_story(raw: str, count: int, names: list[str]) -> dict:
    if len(raw) > 100_000:
        raise AIProviderError("Story response is too long")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise AIProviderError("Story output is not strict JSON (no markdown fences allowed)") from exc
    if not isinstance(data, dict) or not isinstance(data.get("panels"), list):
        raise AIProviderError("Story JSON must contain a panels array")
    if len(data["panels"]) != count:
        raise AIProviderError(f"Story model returned {len(data['panels'])} panels; expected {count}")
    outline = data.get("outline")
    if not isinstance(outline, str) or len(outline) > 1500:
        raise AIProviderError("Story outline must be a string of at most 1500 characters")
    output = []
    for expected, entry in enumerate(data["panels"], start=1):
        if not isinstance(entry, dict) or entry.get("sequence") != expected:
            raise AIProviderError("Panel sequence must be ordered and exact")
        scene, camera, dialogues = entry.get("scene"), entry.get("camera"), entry.get("dialogues")
        if not isinstance(scene, str) or not (2 <= len(scene) <= 700):
            raise AIProviderError("Each panel needs a scene description of 2-700 characters")
        if not isinstance(camera, str) or camera not in CAMERA_CHOICES:
            raise AIProviderError("Invalid camera setting")
        if not isinstance(dialogues, list) or len(dialogues) > 2:
            raise AIProviderError("At most two dialogue bubbles per panel")
        formatted = []
        for item in dialogues:
            if not isinstance(item, dict):
                raise AIProviderError("Dialogue entries must be objects")
            speaker, text = item.get("speaker_name"), item.get("text")
            if speaker is not None and (not isinstance(speaker, str) or speaker not in names):
                raise AIProviderError("Dialogue speaker must exactly match an existing character or null")
            if not isinstance(text, str) or not (1 <= len(text) <= 50):
                raise AIProviderError("Dialogue must be 1-50 Chinese characters or punctuation")
            formatted.append({"speaker_name": speaker, "text": text})
        output.append({"sequence": expected, "scene": scene, "camera": camera, "dialogues": formatted})
    return {"outline": outline, "panels": output}


def story_draft(title: str, premise: str, style: str, count: int,
                characters: list[dict[str, str]]) -> dict:
    url, model, key = _config("story")
    names = [c["name"] for c in characters]
    system = (
        "你是专业中文漫画编剧和分镜导演。请只返回一个合法 JSON 对象，不要 Markdown。"
        "格式必须是 {\"outline\":\"...\",\"panels\":[{\"sequence\":1,\"scene\":\"...\","
        "\"camera\":\"中景\",\"dialogues\":[{\"speaker_name\":null,\"text\":\"...\"}]}]}。"
        f"必须准确生成 {count} 格，sequence从1连续递增。每格最多2句对白，每句最多50字。"
        "台词必须使用简体中文、自然简洁，角色名称严格匹配输入角色，旁白speaker_name使用null。"
        "camera只能是远景、全景、中景、近景、特写、俯拍、仰拍。"
        "画格动作、人物站位、镜头连续性要具体；图像应没有文字，台词后续单独排版。"
    )
    payload = {
        "model": model, "temperature": 0.6,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({
                "title": title[:160], "premise": premise[:2000], "style": style[:120],
                "panel_count": count, "characters": characters[:12]
            }, ensure_ascii=False)}
        ],
    }
    result = _request(url + "/chat/completions", key, json_payload=payload)
    try:
        text = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError("Chat completion response has no message content") from exc
    if not isinstance(text, str):
        raise AIProviderError("Chat completion content must be plain JSON text")
    return _parse_story(text, count, names)


def build_panel_prompt(scene: str, camera: str, style: str, characters: list[dict],
                       override: str = "") -> str:
    cast = "\n".join(
        f"人物{index+1}：{c['name']}；外貌：{c['appearance']}；性格：{c['personality']}"
        for index, c in enumerate(characters[:8])
    )
    detail = override.strip() or scene
    return (
        f"专业彩色漫画单格插画，{style}，{camera}。"
        f"画面内容：{detail}\n人物设定：\n{cast}\n"
        "保证人物外观、配饰、服装和表情一致，画面动作自然，有清晰的漫画叙事构图。"
        "不要画漫画边框，不要画气泡，不要画标题或字母。"
        "绝对不要出现任何中文、英文、数字、标点、签名、水印或其他可见文字。"
        "为后续人工叠加气泡保留适当的画面留白。"
    )


def normalize_png(raw: bytes) -> bytes:
    if len(raw) > MAX_IMAGE_BYTES:
        raise AIProviderError("Generated image exceeds 12MB limit")
    try:
        with Image.open(BytesIO(raw)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise AIProviderError("Generated image dimensions exceed limit")
            img = ImageOps.exif_transpose(img)
            converted = img.convert("RGB")
            output = BytesIO()
            converted.save(output, "PNG", optimize=True)
            data = output.getvalue()
            if len(data) > MAX_IMAGE_BYTES:
                raise AIProviderError("Normalized image exceeds 12MB limit")
            return data
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AIProviderError("Model did not return a valid raster image") from exc


def image_candidate(prompt: str, reference_images: list[bytes]) -> bytes:
    url, model, key = _config("image")
    if len(prompt) > 6000:
        raise AIProviderError("Panel prompt too long")
    use_edit = bool(reference_images) and reference_mode() == "edits"
    if reference_images and not use_edit:
        raise AIProviderError("Reference images provided, but IMAGE_REFERENCE_MODE=edits is not enabled")
    size = os.getenv("IMAGE_SIZE", "1536x1024")
    if size not in {"1024x1024", "1536x1024", "1024x1536", "1792x1024", "1024x1792"}:
        raise AIProviderError("Unsupported IMAGE_SIZE")
    if use_edit:
        files = [("image", (f"reference-{i}.png", img, "image/png"))
                 for i, img in enumerate(reference_images)]
        obj = _request(url + "/images/edits", key,
                       files=files, form={"model": model, "prompt": prompt, "size": size, "n": "1"})
    else:
        obj = _request(url + "/images/generations", key,
                       json_payload={"model": model, "prompt": prompt, "size": size, "n": 1})
    try:
        encoded = obj["data"][0]["b64_json"]
        if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE_BYTES * 2:
            raise AIProviderError("Image provider must return bounded b64_json output")
        raw = base64.b64decode(encoded, validate=True)
    except (KeyError, IndexError, TypeError, binascii.Error, ValueError) as exc:
        raise AIProviderError("Image provider must return data[0].b64_json (no URL downloads)") from exc
    return normalize_png(raw)
