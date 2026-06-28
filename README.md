# AI Video Growth Studio / AI 视频增长中枢

AI-powered short video automation system for real estate, education, and lifestyle content.

热点采集 → 账号/素材管理 → AI 文案生成 → TTS 配音 → 可选数字人开场 → 素材混剪 → 字幕/关键词增强 → 导出 MP4 → 投流/监控

## Features

- **AI Copywriting**: DeepSeek-powered script generation with knowledge base
- **Cloud TTS**: Segmented voice synthesis (Volcengine / Doubao)
- **Digital Human**: Volcengine OmniHuman / FAL Lipsync integration
- **Smart Compose**: FFmpeg 9:16 vertical video with ASS subtitles
- **Subtitle System**: Auto-sized subtitles (min 80px), keyword overlays with pure text styling
- **Heat Radar**: Competitor video analysis and collector automation
- **One-Click Pipeline**: Script → Audio → Digital Human → Compose

## Quick Start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your API keys
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev  # Opens at http://localhost:5173
```

### Docker

```bash
docker compose up --build
```

## Experimental: MiniMax / Hailuo B-roll

Optional video generation for real estate and foreign trade B-roll. Set `MINIMAX_ENABLED=true` and `MINIMAX_API_KEY` in `.env`.

| Endpoint | Description |
|----------|-------------|
| `POST /api/minimax/video/text-to-video` | Text → B-roll video |
| `POST /api/minimax/video/image-to-video` | Image → B-roll video |
| `GET /api/minimax/status` | Provider status + B-roll prompts |

## Key API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check |
| `POST /api/generate-copy` | AI script generation |
| `POST /api/tts-segments` | Segmented TTS (`text` or `segments`) |
| `POST /api/compose-video` | Video composition with subtitles |
| `POST /api/digital-human/create` | Digital human intro generation |
| `GET /api/assets` | Asset library |
| `POST /api/one-click-generate` | Full pipeline plan |

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Ubuntu ECS + Nginx + HTTPS deployment.

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues.

## Security

- Never commit `.env` files (API keys, tokens, secrets)
- Never commit media files (`.mp4`, `.mp3`, etc.)
- Never commit databases (`.db`, `.sqlite3`)
- All AI voice generation requires proper consent and authorization

## License

Proprietary. All rights reserved.
