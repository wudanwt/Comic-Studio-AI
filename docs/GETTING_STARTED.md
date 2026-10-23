# 本地启动和验收

## 开发环境

推荐 Docker Compose（本地开发用途）：


 ```bash
git clone https://github.com/wudanwt/Comic-Studio-AI.git
cd Comic-Studio-AI
git checkout feat/mvp-comic-workbench-v0.1
docker compose up --build
```

打开 http://localhost:5173，API 文档在 http://localhost:8000/docs。

没有 Docker 时，在本机分别启动：

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 8000

# 在另一个终端
cd web
npm install
npm run dev
```

非 Docker 方式默认为 SQLite，安装 Noto Sans CJK 字体以保证 PNG 中文呈现。

## 端到端人工验收

1. 创建「大小姐与司机」四格项目。
2. 添加「布偶猫大小姐」和「大橘司机」角色，填写外观设定。
3. 在「剧情工坊」生成 Mock 分镜，并在「逐格分镜」调整四格场景。
4. 给每格分别新增中文对白，锁定已确认文本。
5. 为其中一格上传 PNG/JPEG/WebP，批准该画格图片。
6. 在「漫画合成」检查排版，导出 SVG、PNG、JSON。
7. 解锁第三格对白，改写并重新锁定，重新导出；确认全部画格的图片 ID 没有变化。

## 测试

```bash
cd server
PYTHONPATH=. pytest -q tests
```

测试涉及数据库事务、跨项目人物引用阻止、中文原文、锁定/解锁、单格图片资产不变性、PNG 生成及非图片上传拒绝。

## 当前限制

这是**单用户本地开发 MVP**，无登录鉴权，不得直接暴露公网。当前没有接入真实模型或 ComfyUI；没有角色版本锁定、专业拖拽合成器、审计历史和后台任务；建表使用 create_all，后续要引入 Alembic；中文超框检查目前基于保守字符宽度估算，不等同于完整字形度量，导出成品仍需视觉复核。
