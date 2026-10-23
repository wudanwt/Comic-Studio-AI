# 架构（P0）

前端 React 19 + TypeScript + Vite：
- 项目、角色、剧情、分镜与合成编辑界面。
- 通过 /api 同源反向代理访问 FastAPI。
- 当前无账号系统，仅在本机开发使用。

后端 FastAPI + SQLAlchemy：
- projects, characters, panels, dialogues, assets 五张表；
- 图片上传后转 PNG，保存 SHA256，图片批准只更新 panel.approved_asset_id；
- 锁定对白只可先 unlock，再 patch；每次编辑增加 version；
- 合成渲染调用 snapshot → SVG（转义并保留中文源字符串）→ CairoSVG PNG；
- 合成时检测可识别的溢出、气泡重叠和资产错误，拒绝不合格导出；
- PostgreSQL 容器运行，非 Docker 可选 SQLite。

关于后续路线：业务服务保持模块化单体，图像任务通过 job queue/worker 扩展；场景、角色版本、模型适配器、审核链和可编辑布局将逐步增强。暂不改动已有任何其他仓库的数字人 Worker。
