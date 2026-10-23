"""Provider contracts and an offline, unmistakably illustrative Mock renderer.

Mock artwork is for workflow validation, not AI-generated creative imagery.
"""
from __future__ import annotations

from io import BytesIO
from math import sin
from typing import Protocol

from PIL import Image, ImageDraw


class ImageProvider(Protocol):
    name: str
    capabilities: dict[str, bool]

    def generate(self, sequence: int, panel_count: int, seed: str) -> bytes:
        """Return PNG bytes with no text rendered in the image."""


class MockImageProvider:
    name = "mock-illustration"
    capabilities = {
        "text_to_image": False,
        "offline_mock": True,
        "reference_image": False,
        "image_edit": False,
        "generates_text": False,
    }

    def generate(self, sequence: int, panel_count: int, seed: str) -> bytes:
        width, height = 1024, 576
        palette = [
            ((215, 236, 254), (105, 165, 227)),
            ((236, 224, 255), (154, 127, 225)),
            ((255, 231, 204), (243, 159, 108)),
            ((213, 242, 232), (78, 165, 151)),
        ]
        top, bottom = palette[(sequence - 1) % len(palette)]
        image = Image.new("RGB", (width, height))
        px = image.load()
        for y in range(height):
            t = y / height
            rgb = tuple(round(top[k] * (1 - t) + bottom[k] * t) for k in range(3))
            for x in range(width):
                px[x, y] = rgb
        draw = ImageDraw.Draw(image)
        draw.ellipse((710, 45, 880, 215), fill=(255, 247, 207))
        for x, y in ((95, 115), (335, 85), (560, 155)):
            draw.ellipse((x, y, x + 170, y + 72), fill=(255, 255, 255))
            draw.ellipse((x + 65, y - 22, x + 175, y + 60), fill=(255, 255, 255))
        for i in range(8):
            x = i * 155 - 50
            h = 110 + (i * 79 + sequence * 33) % 200
            draw.rounded_rectangle((x, 420 - h, x + 112, 500), radius=9, fill=(73, 113, 157), outline=(37, 76, 117), width=3)
            for wy in range(430-h, 470, 36):
                for wx in range(x+14,x+100,34):
                    draw.rectangle((wx,wy,wx+15,wy+19),fill=(255,230,148))
        draw.rectangle((0, 468, width, 576), fill=(74, 113, 139))
        draw.rectangle((0, 492, width, 503), fill=(239, 228, 194))
        # Cat-like character shapes. Shapes deliberately contain no words or letters.
        for j, center in enumerate((290, 705)):
            d = -1 if j == 0 else 1
            cy = 315 + (j * 21 + sequence * 7) % 35
            fur = (236, 225, 211) if j == 0 else (236, 151, 66)
            draw.ellipse((center-92,cy+46,center+92,cy+218),fill=fur,outline=(74,69,68),width=7)
            draw.polygon([(center-78,cy+12),(center-85,cy-85),(center-17,cy-40)],fill=fur)
            draw.polygon([(center+78,cy+12),(center+85,cy-85),(center+17,cy-40)],fill=fur)
            draw.ellipse((center-83,cy-48,center+83,cy+88),fill=fur,outline=(74,69,68),width=6)
            draw.ellipse((center-54,cy+8,center-26,cy+36),fill=(40,46,61))
            draw.ellipse((center+26,cy+8,center+54,cy+36),fill=(40,46,61))
            draw.polygon([(center-11,cy+40),(center+11,cy+40),(center,cy+52)],fill=(126,65,64))
            draw.arc((center-30,cy+35,center,cy+74),0,120,fill=(91,67,66),width=4)
            draw.arc((center,cy+35,center+30,cy+74),60,180,fill=(91,67,66),width=4)
            for wy in (cy+36,cy+54):
                draw.line((center+d*9,wy,center+d*72,wy+5),fill=(85,69,65),width=3)
        out=BytesIO()
        image.save(out,format="PNG")
        return out.getvalue()


def provider_manifest() -> list[dict]:
    p=MockImageProvider()
    return [{"name":p.name,"kind":"image","capabilities":p.capabilities,
             "description":"仅生成无字占位插画，用于演示完整漫画工作流；不调用任何AI模型。"}]
