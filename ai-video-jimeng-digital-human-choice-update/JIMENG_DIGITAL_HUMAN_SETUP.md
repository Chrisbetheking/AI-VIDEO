# 火山即梦 / OmniHuman 数字人接入说明

## 上传覆盖文件

把本包内文件按路径上传覆盖到 GitHub。

## Render 环境变量

先用预览模式：

```env
ENABLE_DIGITAL_HUMAN=true
DIGITAL_HUMAN_ENGINE=preview
```

正式接入火山即梦 / OmniHuman：

```env
ENABLE_DIGITAL_HUMAN=true
DIGITAL_HUMAN_ENGINE=jimeng
JIMENG_ENABLED=true
JIMENG_ACCESS_KEY_ID=你的火山AccessKeyID
JIMENG_SECRET_ACCESS_KEY=你的火山SecretAccessKey
JIMENG_REGION=cn-north-1
JIMENG_SERVICE=cv
JIMENG_VERSION=2024-06-06
JIMENG_ENDPOINT=https://visual.volcengineapi.com
JIMENG_POLL_SECONDS=8
JIMENG_MAX_WAIT_SECONDS=900
```

模型 Action 预置值：

```env
JIMENG_OMNI15_SUBMIT_ACTION=JimengRealmanAvatarPictureOmniV15SubmitTask
JIMENG_OMNI15_GET_ACTION=JimengRealmanAvatarPictureOmniV15GetResult
JIMENG_QUICK_SUBMIT_ACTION=JimengRealmanAvatarPictureSubmitTask
JIMENG_QUICK_GET_ACTION=JimengRealmanAvatarPictureGetResult
JIMENG_VIDEO30_SUBMIT_ACTION=JimengI2VV301080PSubmitTask
JIMENG_VIDEO30_GET_ACTION=JimengI2VV301080PGetResult
```

如果火山 API Explorer 里显示的 Action 名称和这里不一致，以 API Explorer 为准，在 Render 里覆盖对应环境变量。

## 使用方式

1. 先在素材库上传叔叔授权照片/视频。
2. 先在配音导演生成豆包配音。
3. 进入数字人工作台。
4. 引擎选择“火山即梦/OmniHuman”。
5. 模型选择：
   - OmniHuman1.5：模拟真人口播优先。
   - 数字人快速模式：便宜/快速预览。
   - 即梦视频生成3.0：更偏图生视频，不是最优真人口播。
6. 勾选授权确认，生成。

## 不调用数字人

引擎选择“静态预览/素材合成”，后续可以直接用上传素材 + 配音合成视频。
