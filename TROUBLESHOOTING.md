# Troubleshooting Guide

## Quick Health Check

```bash
curl -s https://ai-video.YOUR_SERVER.sslip.io/api/health | python3 -m json.tool
```

Expected response:
```json
{"status": "ok", "version": "1.0.0"}
```

## Common Issues

### /api/health returns error or timeout

1. Check if the backend service is running:
   ```bash
   sudo systemctl status ai-video
   ```

2. Check backend logs:
   ```bash
   sudo journalctl -u ai-video -f
   ```

3. Check Nginx:
   ```bash
   sudo nginx -t && sudo systemctl status nginx
   ```

### /api/tts-segments returns 422

1. Ensure the request includes either `segments` or `text` field:
   ```json
   {"text": "your script here", "voice": "default"}
   ```

2. Check TTS provider credentials:
   ```bash
   grep TTS_PROVIDER /opt/ai-video/backend/.env
   ```

### /api/compose-video fails

1. Check ffmpeg is installed:
   ```bash
   ffmpeg -version
   ```

2. Check disk space:
   ```bash
   df -h /opt/ai-video/backend/outputs/
   ```

3. Review error in backend logs:
   ```bash
   sudo journalctl -u ai-video -n 50 --no-pager | grep -i compose
   ```

### Digital Human generation fails

1. Verify digital human is enabled:
   ```bash
   grep ENABLE_DIGITAL_HUMAN /opt/ai-video/backend/.env
   ```

2. Check engine configuration:
   ```bash
   grep DIGITAL_HUMAN_ /opt/ai-video/backend/.env
   ```

3. For Jimeng/OmniHuman: verify VOLCENGINE credentials.
4. For FAL: verify FAL_KEY is set.
5. For webhook: verify DIGITAL_HUMAN_WEBHOOK_URL is accessible.

### Nginx 502 Bad Gateway

1. Backend may have crashed:
   ```bash
   sudo systemctl restart ai-video
   sudo journalctl -u ai-video -n 20
   ```

2. Port conflict:
   ```bash
   sudo lsof -i :8000
   ```

### Nginx 404 Not Found

1. Check Nginx config:
   ```bash
   sudo nginx -t
   ```

2. Verify the site is enabled:
   ```bash
   ls -la /etc/nginx/sites-enabled/
   ```

### Certbot / HTTPS issues

```bash
sudo certbot renew --dry-run
sudo certbot certificates
```

### ffmpeg errors

1. Check ffmpeg is installed and in PATH:
   ```bash
   which ffmpeg
   ffmpeg -version
   ```

2. Common fixes:
   - `Unknown encoder 'libx264'`: `sudo apt install libx264-dev`
   - `Fontconfig error`: `sudo apt install fonts-noto-cjk`

### MiniMax / Hailuo Issues

1. Check if MiniMax is enabled:
   ```bash
   curl https://ai-video.YOUR_SERVER.sslip.io/api/minimax/status
   ```

2. Verify API key:
   ```bash
   grep MINIMAX_API_KEY /opt/ai-video/backend/.env
   ```

3. If disabled, all MiniMax endpoints return:
   ```json
   {"ok": false, "enabled": false, "message": "MiniMax provider is disabled or missing API key"}
   ```

### Windows Collector Issues

1. Verify collector is running:
   ```powershell
   Get-Process | Where-Object { $_.ProcessName -like "*python*" }
   ```

2. Check collector token matches ECS backend.
3. Verify network access to ECS backend.
