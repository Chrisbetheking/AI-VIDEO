# AI-VIDEO 一页式智能视频增长工作台

当前前端入口已改为 `VideoCreationWizard`，用于替代旧的工程控制台。用户进入页面后不再看到旧 App / 关闭浮层，而是直接进入一页式中控台。

## 主流程

1. 视频创作：输入主题 / 同行主页 / 爆款链接，AI 提取关键词和生成文案。
2. 口播配音：每句口播可单独设置语速、语调、语气、停顿和重点词。
3. 画面风格：每个镜头可手动编辑画面主体、口播、时长、素材来源、运镜、转场和 AI Prompt。
4. 成片预览：调用后端 `POST /api/video/full-ai/tts-first/start`，再轮询 `GET /api/video/full-ai/tts-first/job/{job_id}`。

## 联动模块

- 账号素材：同行主页、爆款链接和真实素材可以一键带入视频创作。
- 数字人库：选中的数字人会传入生成 payload 的 `avatar_config`。
- 获客线索：评论/私信可分析为意向分和回复建议，并可反向作为视频选题。
- 设置：统一管理后端地址、Token、默认城市和素材策略。

## 前端传给后端的关键字段

- `script_segments`
- `segment_voice_settings`
- `keyword_insights`
- `manual_shot_plan`
- `shot_overrides`
- `transition_plan`
- `asset_context`
- `avatar_config`

这些字段用于保证内容、配音、镜头、素材、数字人和获客承接都能在同一条链路里联动。
