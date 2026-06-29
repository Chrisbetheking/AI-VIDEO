# AI-VIDEO 抖音采集 Worker（恢复版）

来源：从用户上传的历史代码包中恢复并合并：
- `ai_video_worker_gbk_ai_model_fix_20260601/collector-local`：最新 command_worker / run_all / collector / uploader / video_resolver，含 Windows UTF-8 控制台修复、视频 intake、进度回传。
- `ai_video_full_stability_one_shot_patch/collector-local`：cookie_manager 与视频解析增强。
- `collector_local_batch3_worker/collector-local`：state / utils / excel_io / requirements / accounts.seed.json 支撑文件。
- `collector_progress_digital_human_patch/collector-local`：Windows 定时任务与启动脚本。

## 能做什么
- 使用 Playwright 打开抖音网页端，使用本机登录态。
- 读取账号主页近期视频、置顶视频、标题、发布时间、点赞/评论/收藏/分享/播放等指标。
- 尽量读取评论相关字段；具体评论列表是否完整取决于抖音页面可见性和风控。
- 使用 `yt-dlp,cobalt,text` 链路尽力解析视频地址。
- 将结果上报到新后端，后端负责 AI 判断、入库、R2 留存、前端实时日志展示。
- 前端 `/api/collector/commands` 下发任务后，本 worker 通过 `command_worker.py` 轮询领取。

## 安装
```powershell
cd C:\ai-video-worker\collector-local
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
notepad .env
```

`.env` 里至少填写：
```env
API_BASE_URL=https://ai-video.47-76-143-158.sslip.io
HEAT_RADAR_INGEST_TOKEN=服务器里的collector token
AUTO_COLLECTOR_CRON_TOKEN=同一个token
```

服务器 token 查看：
```bash
cat /root/ai_video_collector_token.txt
```
不要把 token 发到聊天或截图里。

## 第一次登录
```powershell
python run_all.py --headful --dry-run --once
```
浏览器打开后手动登录抖音，登录态会保存在 `profiles/douyin`。

## 手动采集测试
```powershell
python run_all.py --headful --account "房产马来小哥" --limit 1 --no-delay
```

## 监听前端下发命令
```powershell
python command_worker.py
```
然后在前端“采集器/实时日志”页面点击“网页下发采集命令”。

## 设为开机自启监听
管理员 PowerShell：
```powershell
powershell -ExecutionPolicy Bypass -File .\install_command_worker_task.ps1
```

## 每日自动跑
```powershell
powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1 -Time "02:00" -Limit 10
```

## 注意
这个 worker 是合规公开页面采集器，不绕过登录、验证码和风控。遇到验证页会记录并跳过，需要人工登录/验证。
