# AI VIDEO V10.34 视频审查闸门 + 豆包审片 + 封面自动承接

## 这次补丁做什么

正式链路变为：

```text
视频生成完成
→ 自动机械质检
→ 豆包视频理解审查
→ 人工确认
→ 自动生成 9:16 视频封面
→ 解锁小红书图文包
```

未人工通过时：

```text
/api/graphic-window/video-cover/generate
/api/graphic-window/xiaohongshu/generate
```

会返回 HTTP 409，不会继续包装，也不会调用 FAL。

## 自动检查内容

机械检查：

- 最终视频本地文件是否存在
- 是否有视频流和音轨
- 是否为竖屏且至少 720×1280
- 视频与配音时长误差是否小于 1 秒
- 公网 URL 是否真正返回视频 MIME，而不是 HTML
- subtitle_source 是否记录为原稿锁定
- 黑帧检测
- 长静帧检测

豆包视频理解检查：

- 画面是否跟当时口播内容一致
- 字幕是否有繁体、错字、乱码、抽象符号
- 字幕是否提前或滞后
- 是否存在镜头重复、静止、黑帧或错误地标
- 是否达到进入封面合成的标准

## 状态

```text
not_reviewed
reviewing
review_pending_human
review_failed
approved
rejected
review_error
```

只有 `approved` 会设置：

```text
packaging_unlocked = true
```

## 部署

把压缩包上传到服务器 `/tmp/` 后执行：

```bash
cd /opt/ai-video

rm -rf /tmp/AI_VIDEO_V10_34_REVIEW_GATE_BYTE_PACKAGING
unzip -o /tmp/AI_VIDEO_V10_34_REVIEW_GATE_BYTE_PACKAGING.zip   -d /tmp/AI_VIDEO_V10_34_REVIEW_GATE_BYTE_PACKAGING

bash /tmp/AI_VIDEO_V10_34_REVIEW_GATE_BYTE_PACKAGING/deploy_review_gate.sh
```

成功标志：

```text
=== DEPLOY_DONE_VIDEO_REVIEW_GATE ===
```

## 部署后页面

```text
https://ai-video-s5v.pages.dev/graphic-window/
```

页面会增加：

- 自动审查视频
- 通过并生成 9:16 封面
- 退回修改
- 机械分、豆包分、综合分
- 问题时间段与修复建议

## 手工测试当前任务

```bash
cd /opt/ai-video

bash tools/review_current_job.sh
```

指定任务：

```bash
bash tools/review_current_job.sh full_ai_v1034_xxxxxxxxx
```

## 环境变量

默认启用：

```bash
AI_VIDEO_REQUIRE_REVIEW_APPROVAL=true
AI_VIDEO_AUTO_REVIEW_ON_COMPLETE=true
AI_VIDEO_AUTO_REVIEW_INTERVAL_SECONDS=60
```

豆包读取现有配置：

```bash
ARK_API_KEY
ARK_VIDEO_MODEL
ARK_BASE_URL
```

没有配置豆包时，机械质检仍会执行，但必须人工确认。

## API

运行审查：

```bash
curl -X POST   http://127.0.0.1:8000/api/video/review/JOB_ID/run   -H 'Content-Type: application/json'   -d '{"force_ai":true,"force":true}'
```

查看报告：

```bash
curl http://127.0.0.1:8000/api/video/review/JOB_ID
```

人工通过并自动生成封面：

```bash
curl -X POST   http://127.0.0.1:8000/api/video/review/JOB_ID/approve   -H 'Content-Type: application/json'   -d '{"reviewer":"human","generate_cover":true}'
```

退回：

```bash
curl -X POST   http://127.0.0.1:8000/api/video/review/JOB_ID/reject   -H 'Content-Type: application/json'   -d '{"reviewer":"human","reason":"字幕时间仍不准确"}'
```

## 回滚

```bash
bash rollback_review_gate.sh
```

或者指定备份目录：

```bash
bash rollback_review_gate.sh /opt/ai-video/_backup_before_review_gate_时间
```

## 重要说明

- 自动审查只调用已配置的豆包视频理解模型，不调用 FAL。
- 自动审查通过后也不会直接跳过人工确认。
- 点击“通过并生成 9:16 封面”后，才会解锁封面和小红书图文。
- 封面调用现有本地图文 provider，不重新生成视频。
