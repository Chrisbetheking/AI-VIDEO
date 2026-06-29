# CPU Open-Source TTS Experiment

独立实验服务，不接入主 FastAPI 后端。在 4核8G Ubuntu ECS 上用 CPU 跑 ChatTTS / OpenVoice。

## 快速开始

```bash
# 安装
cd tools/cpu_open_tts_service
bash install.sh

# 启动
bash run.sh
# 监听 127.0.0.1:7861

# 测试
curl http://127.0.0.1:7861/health
```

## API

### GET /health

```json
{"ok":true,"mode":"cpu_open_tts","device":"cpu","chattts_loaded":true,"openvoice_loaded":false}
```

### POST /synthesize

```bash
# ChatTTS only (中文口播，不克隆音色)
curl -X POST http://127.0.0.1:7861/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"来马来西亚买房，区域选错几百万直接打水漂。","mode":"chattts_only"}'

# OpenVoice clone (需要参考音频)
curl -X POST http://127.0.0.1:7861/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello, this is a test.","reference_audio":"/root/uncle_voice_sample.mp3","mode":"openvoice_clone"}'
```

## 模式说明

| 模式 | 说明 | 音色 |
|---|---|---|
| `chattts_only` | ChatTTS 中文语音合成 | 默认音色，自然流畅 |
| `openvoice_clone` | OpenVoice 音色转换 | 接近参考音频音色 |

## 预估性能

| 指标 | 预估 |
|---|---|
| 模型加载 | 30-60s (ChatTTS), 60-120s (OpenVoice) |
| 合成速度 | ~0.3-0.5x 实时 (CPU) |
| 内存占用 | ChatTTS ~2GB, +OpenVoice ~4GB |
| Swap 建议 | 建议 4GB swap |

## 环境变量

| 变量 | 默认值 |
|---|---|
| `CPU_TTS_PORT` | 7861 |
| `CPU_TTS_OUTPUT_DIR` | `./outputs` |
| `OPENVOICE_BASE_CKPT` | `../OpenVoice/checkpoints_v2/base_speakers/EN` |
| `OPENVOICE_CONVERTER_CKPT` | `../OpenVoice/checkpoints_v2/converter` |
