# Comic Studio AI v0.3 · 角色资产和后台任务

## 新增功能

### 角色参考图历史版本

在角色档案中上传正面、侧面、背面、表情、服装等多角度参考图，每个上传会生成不可覆盖的新资产与版本记录。切换当前定妆仅更新 active reference，不删除旧版本；旧版单参考图接口仍保留兼容性。

### 后台生图队列

分镜页面可提交 Mock 或真实 AI 画格任务，后端返回 202 + Job ID，独立 worker 轮询 PostgreSQL。
任务状态：queued → running → succeeded/failed，任意排队或执行中任务允许取消；失败可重试，最多2次。
模型请求在提交时冻结分镜、人设文本和参考资产 ID。后续编辑不影响已经提交的任务。
成功产物进入候选图列表，**不会自动替换已批准图片**。页面轮询任务状态，允许对失败任务显式重试。

PostgreSQL 使用 SELECT FOR UPDATE SKIP LOCKED 避免同一任务被多 Worker 同时领取；SQLite 仅支持串行本地测试。
Worker 在异常退出后按10分钟的陈旧阈值恢复 running 任务；这是简化的租约策略，尚无运行中的心跳续租。生产环境应加入基于租约的 heartbeat 与幂等写入验证。

### 可视化对白气泡位置编辑

进入逐格分镜，可在图像上拖动气泡或拖拽右下角调节大小，松手将坐标保存到独立文字记录。
已锁定中文对白允许修改位置/尺寸，但禁止修改 text 或 speaker_id；图片资产 ID 不变。
原 SVG / PNG 导出仍按后端坐标重新叠字，具备超框和气泡碰撞检查。

## 试运行

```bash
git checkout feat/production-workbench-v0.3
cp .env.example .env
docker compose up --build
# 前端 http://localhost:5173
```

Worker 默认随 compose 自动启动。要手动执行单轮任务，可在 server 环境中调用：

```bash
cd server
PYTHONPATH=. python -c 'import worker; print(worker.process_one())'
PYTHONPATH=. pytest -q tests
```

## 验收路径

1. 新建角色，上传正面与侧面图片，切换当前定妆后两张旧图仍然可访问。
2. 进入逐格分镜，提交 Mock 后台任务，任务应该从 queued 进入 succeeded 并产生候选图。
3. 手工采用候选图；增加并锁定中文对白；拖动气泡坐标，检查文字不变化。
4. 导出 SVG 与 PNG，检查画格保持原图，只移动对白。
5. 修改分镜后再次提交真实生图；以前的生图任务快照不得变化。
6. 对失败任务查看不含敏感响应正文的 error_code，最多允许一次手工重试。

## 当前限制和后续开发

- 单用户、本机开发版，无鉴权和授权隔离，禁止公网部署。
- 人设图像参考历史已版本化，尚无同一角色多视角自动组合、LoRA、IP-Adapter 或一致性评分。
- 并发 Worker 锁依赖 PostgreSQL；SQLite 并发领取不安全。
- 当前角色人设文本本身没有不可变版本系统，Job 只有冻结提示词与参考 asset IDs。
- 气泡画布是基础拖拽编辑器，尚无形状、气泡尾巴、字体层级、智能对齐和高精度中文排版。
- 真正图像局部重绘与 ComfyUI 工作流未实现；厂商模型兼容性尚需现场验证。
- 应把数据库初始化 create_all 迁移到 Alembic，加入鉴权、组织隔离、审计及任务成本配额。
- 长运行任务需增加心跳与可续租锁以保证恢复语义，避免陈旧任务在10分钟后发生重复执行。
