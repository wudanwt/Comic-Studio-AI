# v0.2 AI 模型接入与测试

> 本功能基于 PR #1 v0.1。目前仍是单用户、本地开发版，禁止直接公网部署。

## 一、配置

复制 .env.example 到 .env，再将实际兼容模型的地址、模型名与凭据填入（不要把 .env 上传 Git）。

```bash
cp .env.example .env
docker compose up --build
```

- STORY_API_BASE_URL：OpenAI-compatible base URL，应含 /v1，不要以 /chat/completions 结尾。
- STORY_MODEL：用于生成漫画大纲、逐格分镜、中文对白的模型。
- STORY_API_KEY：服务端需要鉴权时填写实际凭据。
- IMAGE_API_BASE_URL：支持 /images/generations 的兼容服务 /v1 地址。
- IMAGE_MODEL：图像生成功能模型。
- IMAGE_API_KEY：图像服务鉴权凭据。
- IMAGE_REFERENCE_MODE：off 或 edits。启用 edits 时，将角色定妆照通过 multipart/form-data 传给 /images/edits；目标模型必须支持相应接口。
- IMAGE_SIZE：默认 1536x1024，也允许 1024x1024、1024x1536、1792x1024、1024x1792，实际由服务商决定。

当前图像接口必须返回 data[0].b64_json，为保证安全，不会下载任意远程 URL。部分厂商协议不完全兼容，需用真实服务实测。API 状态页面不会返回密钥。

## 二、使用流程

1. 新建项目，添加人物外貌、性格，按需上传定妆参考图。
2. 进入剧情工坊选择 AI 生成待审剧本，服务端验证格数、镜头、角色归属与中文对白长度；生成结果只存为草稿。
3. 审阅后点击确认采用。若项目中已有任何台词，服务端拒绝应用草稿，防止覆盖已修改或已锁定对白。
4. 逐格分镜里选择出场角色、修改图像提示词，调用真实图片 API；返回的是候选图，只有确认采用才更新当前画格。
5. 中文对白在后期由矢量排版服务绘制，文本修改不触发生图；从漫画合成页面导出 SVG/PNG/JSON。

## 三、测试

```bash
cd server
PYTHONPATH=. pytest -q tests
```

test_ai_pipeline.py 对模型 HTTP 进行本地模拟，覆盖剧本预审不改写、草稿应用保护、角色参考图、候选审批和拒绝 URL 图片。CI 通过不代表真实厂商兼容性已经验证。

## 四、尚未完成

- 异步任务、进度更新、超时重试、取消及多 GPU Worker。
- ComfyUI、局部重绘、连续人物一致性评测。
- 多用户鉴权、配额、费用控制、Alembic迁移。
- 精确字形度量、拖拽编辑器、版本回滚与审计。

## 五、安全

角色参考图和提示词会发送到所配置的模型服务。不要未经授权发送个人隐私图片。API Key 应只通过环境变量传入，前端不会保存密钥。Docker 服务仅绑定 127.0.0.1。
