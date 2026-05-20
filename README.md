# 短视频 AI 自动化 Web Demo（DeepSeek + 云端 TTS + FFmpeg）

这是一个可直接演示的短视频自动化系统 Demo：

- 文案生成：DeepSeek API
- 文案知识库：SQLite 本地库，支持参考历史文案类比生成
- 配音：云端 TTS（默认 `edge-tts`，办公本无 GPU 也能用；失败时自动降级为静音音频，保证流程可跑通）
- 自动剪辑：FFmpeg 插件式视频合成，支持图片/视频素材，自动裁剪为 9:16
- 字幕：自动切分口播稿生成 SRT 并烧录字幕
- 投流分析：抖音投流模拟分析和实时监控指标（后续可替换成真实巨量/抖音数据 API）
- 部署：本地 Docker 一键跑；前端可上 Cloudflare Pages，后端部署到 Render/Railway/VPS/云服务器

> 建议先用 Docker 本地演示，最稳、最快。Cloudflare Pages 只适合放前端，视频合成后端需要 Python + FFmpeg 环境。

---

## 1. 最快启动方式（推荐）

### 准备

电脑需要安装：

- Docker Desktop
- 一个 DeepSeek API Key

### 启动

在项目根目录执行：

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，填入：

```env
DEEPSEEK_API_KEY=你的_deepseek_key
```

然后启动：

```bash
docker compose up --build
```

打开：

```text
http://localhost:8000
```

---

## 2. 不用 Docker 的本地启动方式

需要本地安装 FFmpeg、Python 3.10+、Node 20+。

### 后端

```bash
cd backend
cp .env.example .env
# 编辑 .env，填 DEEPSEEK_API_KEY
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端

另开一个终端：

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

打开：

```text
http://localhost:5173
```

---

## 3. Cloudflare 部署建议

### 方案 A：最快演示

- 后端：部署到 Render / Railway / Fly.io / VPS / 宝塔面板 Docker
- 前端：部署到 Cloudflare Pages
- 前端环境变量：

```env
VITE_API_BASE=https://你的后端域名
```

### 方案 B：单体部署

直接把本项目 Docker 镜像部署到一台云服务器，访问后端域名即可。后端会自动托管前端静态页面。

---

## 4. 关键接口

- `POST /api/generate-copy`：DeepSeek 生成标题、口播稿、简介、标签、镜头建议
- `POST /api/tts`：云端 TTS 生成音频
- `POST /api/assets`：上传图片/视频素材
- `POST /api/compose-video`：合成 9:16 MP4
- `POST /api/ad-analysis`：投流建议与实时指标模拟
- `GET /api/knowledge` / `POST /api/knowledge`：文案知识库

---

## 5. 模块说明

### 哪些是 AI？

- 文案生成：AI，调用 DeepSeek
- 配音：AI/云端 TTS，默认使用 `edge-tts` 调云端语音服务，不需要 GPU

### 哪些是插件/程序？

- 视频剪辑：FFmpeg 程序化合成
- 字幕烧录：FFmpeg + SRT
- 最终 MP4：FFmpeg 导出

### 后续正式版可升级

- TTS 换成正式商用 API（火山、讯飞、腾讯云、阿里云等）
- 投流分析接入巨量引擎/抖音企业号数据
- 素材库接对象存储（Cloudflare R2 / 阿里 OSS / 腾讯 COS）
- 任务队列接 Celery/RQ，支持多用户并发
- 登录权限、操作日志、成片审核流

---

## 6. 安全提醒

- 生产环境不要把 DeepSeek API Key 写在前端。
- Demo 页面支持临时输入 API Key，是为了现场快速试用；正式部署建议只放在后端 `.env` 或云平台 Secret。
- AI 配音涉及真实人物声音时，需要本人授权。
- 对外投流涉及广告性质内容时，需要符合平台规则和广告合规要求。
