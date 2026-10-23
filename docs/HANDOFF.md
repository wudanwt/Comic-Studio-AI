# Comic Studio AI — 开发交接

## 当前里程碑

P0 / v0.1 单用户可编辑漫画合成闭环，功能分支：feat/mvp-comic-workbench-v0.1。

## 已实现

- React + TypeScript 六个独立业务界面：项目、角色、剧情、逐格分镜、合成、设置。
- FastAPI/SQLAlchemy 项目和角色存储，按 4/6/8/12 格创建漫画。
- 离线可重复的 Mock 剧情分镜与初始演示对白（已有对白不覆盖），单格文字与镜头编辑。
- 中文对白有独立的数据库源字符串、锁定/解锁与版本号。
- PNG/JPEG/WebP 上传后归一化为 PNG，按格生成不可覆盖的 asset ID，经确认后被画格引用。
- 服务端 SVG/PNG 1920×1080 合成，中文用 SVG 文本节点而非生图模型输出。
- 校验文本超框、坐标越界、气泡重叠，以及图片归属和文件缺失。
- 导出 JSON 供进一步工程编辑。
- 服务端带能力声明的 MockImageProvider，逐格生成无中文字占位插画并独立保存候选；可批量生成缺失画格。
- Docker Compose/PostgreSQL、CI 与 API 集成测试。

## 本地执行

阅读 docs/GETTING_STARTED.md。

## 已验证

在本地 Python/FastAPI 测试环境执行 server/tests/test_api.py：2 passed。GitHub Actions / Docker / npm build 尚须以 CI 结果核实，不应视为已通过。

## 已知限制与风险

1. 单用户原型，无权限隔离、鉴权、CSRF 防护等生产级安全配置。Docker 只绑定 127.0.0.1。
2. 没有生图 API、LLM、参考图控制、ComfyUI/GPU Worker；Mock 只生成分镜描述。
3. 没有独立不可变角色版本、复杂剧情审计、候选生图审批工作流。
4. 气泡支持手动填写归一化坐标，而不是可拖拽缩放；尚无指向说话者的气泡尾巴。
5. 中文排版使用字符宽度近似和 Noto CJK 字体；还没有精确 glyph 测量、嵌入字体/缺字检查、人工视觉审计自动化。文档或画格图片中自带的文字也无法自动验证。
6. 当前用 ORM create_all 建表，没有 Alembic 迁移和事务性历史快照。
7. 导出的 SVG 包含 base64 嵌入图片，文件可能较大；大量画格需更高效的图像存储与渲染方案。
8. 当前缺少单用户以外的认证、存储配额、模型费用控制。

## 下一阶段实施顺序

1. 补齐鉴权与权限域、Alembic 与正式 asset service。
2. 角色人设不可变版本、参考图包、场景/道具资产。
3. LLMAdapter（Mock 与 OpenAI-compatible）、结构化故事生成 Schema、人工批准。
4. ImageProvider（Mock 与 ComfyUI/API）、异步 job/idempotency、候选及逐格重绘。
5. react-konva 拖拽画格和气泡、文本精确度量和排版预检。
6. 项目审计、工程版本、回滚、并发和真实浏览器 E2E。

## 不可破坏的设计约束

- 已锁定的对白不允许 PATCH。
- 文字变更不触发生图，也不覆盖已批准图片文件。
- 跨项目角色、图片关系需要后端拒绝。
- 用户中文对白只有 dialogue.text 一份真值；禁止由图像模型描绘中文字。
- 真实模型能力及环境状态必须明确展示，Mock 不得冒充线上完成的 AI 调用。
