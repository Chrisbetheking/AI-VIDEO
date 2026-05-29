from pathlib import Path

APP = Path('frontend/src/App.tsx')
if not APP.exists():
    raise SystemExit('找不到 frontend/src/App.tsx。请在项目根目录运行：python fix_frontend_token_banner.py')

s = APP.read_text(encoding='utf-8')
original = s

# 1) Remove common hard-blocking token warning banners by replacing exact Chinese text block conditions conservatively.
# This script intentionally does not touch API/ECS logic; it only prevents frontend from claiming token is missing
# when backend/ECS can already save data successfully.
texts = [
    '请先填写接口 Token，必须和 Render 的 HEAT_RADAR_INGEST_TOKEN 一致。',
    '请先填写接口 Token，必须和 Render 的 HEAT_RADAR_INGEST_TOKEN一致。',
    '请先填写接口 Token，必须和 Render 的 HEAT_RADAR_INGEST_TOKEN 一致',
]
for t in texts:
    if t in s:
        s = s.replace(t, '采集接口已由后端/ECS校验；网页端不再重复要求 Token。')

# 2) If a disabled condition references token in the same button line, make the button not blocked by frontend token.
# Common patterns from React JSX.
replacements = {
    'disabled={!collectorToken || collectorBusy}': 'disabled={collectorBusy}',
    'disabled={!heatRadarIngestToken || collectorBusy}': 'disabled={collectorBusy}',
    'disabled={!ingestToken || collectorBusy}': 'disabled={collectorBusy}',
    'disabled={!token || collectorBusy}': 'disabled={collectorBusy}',
    'disabled={!collectorToken}': 'disabled={false}',
    'disabled={!heatRadarIngestToken}': 'disabled={false}',
    'disabled={!ingestToken}': 'disabled={false}',
}
for a,b in replacements.items():
    s = s.replace(a,b)

# 3) Ensure command request gets token from multiple localStorage aliases if code uses collectorToken state initializer.
# This is safe even if it does nothing.
patterns = [
    "localStorage.getItem('collectorToken') || ''",
    'localStorage.getItem("collectorToken") || ""',
    "localStorage.getItem('heatRadarIngestToken') || ''",
    'localStorage.getItem("heatRadarIngestToken") || ""',
]
fallback = "localStorage.getItem('collectorToken') || localStorage.getItem('heatRadarIngestToken') || localStorage.getItem('HEAT_RADAR_INGEST_TOKEN') || ''"
for p in patterns:
    if p in s:
        s = s.replace(p, fallback)

if s == original:
    print('没有找到常见 token banner/disabled 写法。你需要手动搜索：HEAT_RADAR_INGEST_TOKEN 或 请先填写接口 Token。')
else:
    APP.write_text(s, encoding='utf-8')
    print('已修复 frontend/src/App.tsx 的前端 Token 误报/按钮禁用逻辑。')
    print('下一步：npm run build，然后重新部署 Cloudflare 前端。')
