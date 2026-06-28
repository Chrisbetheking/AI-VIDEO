# AI Video Growth Studio - Deployment Guide

## Architecture

- **Backend**: FastAPI (Python) on Ubuntu ECS
- **Frontend**: React + Vite, deployed to Cloudflare Pages
- **Storage**: Cloudflare R2 for media, Supabase for metadata
- **Collector**: Windows/Ubuntu headful browser automation

## Ubuntu ECS Deployment

### 1. System Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv ffmpeg nginx certbot python3-certbot-nginx
```

### 2. Clone and Setup

```bash
git clone https://github.com/Chrisbetheking/AI-VIDEO.git /opt/ai-video
cd /opt/ai-video/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration

```bash
cp .env.example .env
nano .env
```

Required variables:
- `APP_DATA_DIR` - Data directory path
- `TTS_PROVIDER` - `volcengine` / `doubao` / `sapi`
- `VOLCENGINE_APP_ID` / `VOLCENGINE_TOKEN` - TTS credentials
- `DIGITAL_HUMAN_WEBHOOK_URL` - External digital human API
- `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` - Cloudflare R2
- `SUPABASE_URL` / `SUPABASE_KEY` - Supabase

### 4. systemd Service

```ini
# /etc/systemd/system/ai-video.service
[Unit]
Description=AI Video Growth Studio Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/ai-video/backend
Environment=PATH=/opt/ai-video/backend/.venv/bin:/usr/bin
ExecStart=/opt/ai-video/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-video
sudo systemctl start ai-video
```

### 5. Nginx Reverse Proxy

```nginx
# /etc/nginx/sites-available/ai-video
server {
    server_name ai-video.YOUR_SERVER.sslip.io;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 500M;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 600s;
        client_max_body_size 500M;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/ai-video /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 6. HTTPS with Certbot

```bash
sudo certbot --nginx -d ai-video.YOUR_SERVER.sslip.io
```

### 7. Frontend Deployment (Cloudflare Pages)

```bash
cd frontend
npm install
npm run build
```

Deploy `dist/` to Cloudflare Pages. Set environment variable:
- `VITE_API_BASE` = `https://ai-video.YOUR_SERVER.sslip.io`

### 8. Collector Deployment (Windows)

```bash
cd collector-local
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Configure `.env` with ECS backend URL and collector token.

## Health Check

```bash
curl https://ai-video.YOUR_SERVER.sslip.io/api/health
# Expected: {"status":"ok","version":"1.0.0"}
```
