from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings
from app.schemas import CopyRequest, EditPlanRequest, EditPlanResponse, GeneratedCopy, RewriteFromInspirationRequest, VoiceDirectorRequest, VoiceDirectorResponse


class DeepSeekError(RuntimeError):
    pass


def _safe_json_loads(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?', '', cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r'```$', '', cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _as_str(payload: Dict[str, Any], name: str, default: str = '') -> str:
    value = payload.get(name, default)
    if isinstance(value, list):
        return '\n'.join(str(x) for x in value)
    return str(value or default).strip()


def _as_list(payload: Dict[str, Any], name: str) -> List[str]:
    value = payload.get(name, [])
    if isinstance(value, str):
        return [x.strip(' #，,\n\t') for x in re.split(r'[,，#\n]', value) if x.strip(' #，,\n\t')]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def normalize_copy(payload: Dict[str, Any], fallback_topic: str) -> GeneratedCopy:
    title = _as_str(payload, 'title', fallback_topic)[:80]
    hook = _as_str(payload, 'hook', title)
    script = _as_str(payload, 'script') or _as_str(payload, '口播稿') or f'今天给大家分享：{fallback_topic}。'
    description = _as_str(payload, 'description', title)
    tags = _as_list(payload, 'tags')[:12] or ['短视频', '老板口播']
    shots = _as_list(payload, 'shots')[:12] or ['老板正面口播', '产品/服务细节', '客户或案例画面', '结尾引导咨询']
    kb_refs = _as_list(payload, 'kb_refs')[:8]
    return GeneratedCopy(title=title, hook=hook, script=script, description=description, tags=tags, shots=shots, kb_refs=kb_refs)


def _candidate_models(primary: str) -> List[str]:
    models: List[str] = []
    for m in [primary, 'deepseek-chat', 'deepseek-v4-flash']:
        m = (m or '').strip()
        if m and m not in models:
            models.append(m)
    return models


def _friendly_error(status_code: int, text: str, url: str, model: str) -> str:
    hint = ''
    if status_code == 401:
        hint = '请检查 DEEPSEEK_API_KEY 是否正确。'
    elif status_code == 402:
        hint = 'DeepSeek 账户余额不足或未开通计费。'
    elif status_code == 404:
        hint = '请检查 DEEPSEEK_BASE_URL，应为 https://api.deepseek.com。'
    elif status_code in (400, 422):
        hint = '可能是模型名或请求参数不兼容。'
    elif status_code in (429, 503):
        hint = 'DeepSeek 当前限流或服务繁忙，稍后重试。'
    return f'DeepSeek 返回错误 {status_code}，url={url}，model={model}。{hint} 原始返回：{text[:500]}'


async def _chat_json(settings: Settings, system: str, user: str, temperature: float = 0.7, timeout: int = 90) -> Dict[str, Any]:
    api_key = settings.deepseek_api_key.strip()
    if not api_key:
        raise DeepSeekError('缺少 DeepSeek API Key。请设置 DEEPSEEK_API_KEY。')
    url = settings.deepseek_base_url.rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    last_error = ''
    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in _candidate_models(settings.deepseek_model):
            body: Dict[str, Any] = {
                'model': model,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                'temperature': temperature,
                'stream': False,
                'response_format': {'type': 'json_object'},
            }
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                raise DeepSeekError(f'DeepSeek 请求失败：{exc}') from exc
            if resp.status_code >= 400:
                last_error = _friendly_error(resp.status_code, resp.text, url, model)
                continue
            data = resp.json()
            try:
                content = data['choices'][0]['message']['content']
                return _safe_json_loads(content)
            except Exception as exc:
                raise DeepSeekError(f'DeepSeek 输出解析失败：{data}') from exc
    raise DeepSeekError(last_error or 'DeepSeek 调用失败。')


async def test_deepseek(settings: Settings, api_key_override: Optional[str] = None) -> Dict[str, Any]:
    api_key = (api_key_override or settings.deepseek_api_key or '').strip()
    if not api_key:
        raise DeepSeekError('缺少 DeepSeek API Key。请设置 DEEPSEEK_API_KEY。')
    url = settings.deepseek_base_url.rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json={
            'model': settings.deepseek_model,
            'messages': [{'role': 'user', 'content': '只回复两个字：成功'}],
            'temperature': 0,
            'stream': False,
        })
    if resp.status_code >= 400:
        raise DeepSeekError(_friendly_error(resp.status_code, resp.text, url, settings.deepseek_model))
    data = resp.json()
    return {'ok': True, 'url': url, 'model': settings.deepseek_model, 'reply': data.get('choices', [{}])[0].get('message', {}).get('content', '')}


async def generate_copy(settings: Settings, req: CopyRequest, knowledge_texts: List[str]) -> GeneratedCopy:
    kb_block = '\n\n---\n\n'.join(knowledge_texts + req.knowledge_examples[:10])
    system = '你是中国短视频增长团队的资深编导和投流策划。必须输出严格 JSON。'
    user = f'''
请生成一条适合抖音/视频号的 9:16 短视频文案。
主题：{req.topic}
行业：{req.industry or '未填写'}
目标受众：{req.audience or '未填写'}
核心卖点：{req.selling_points or '未填写'}
风格：{req.style}
期望时长：{req.duration_seconds} 秒
参考文案知识库（模仿风格，不要照抄）：
{kb_block or '暂无'}

输出 JSON 字段：title, hook, script, description, tags, shots, kb_refs。
'''.strip()
    payload = await _chat_json(settings, system, user, temperature=0.75)
    return normalize_copy(payload, req.topic)


async def rewrite_from_inspiration(settings: Settings, req: RewriteFromInspirationRequest) -> GeneratedCopy:
    system = '你是短视频原创改写专家，负责把竞品视频结构转化为原创文案。必须避免照抄原文，只借鉴结构和表达节奏。输出严格 JSON。'
    user = f'''
参考视频/文案内容：
{req.reference_text}

请针对以下业务重新创作一条原创短视频文案：
行业：{req.industry or '未填写'}
目标受众：{req.audience or '未填写'}
核心卖点：{req.selling_points or '未填写'}
风格：{req.style}
期望时长：{req.duration_seconds} 秒

要求：
1. 不要照抄参考文案，句子相似度要低。
2. 保留参考内容的有效结构：开头钩子、痛点、解决方案、信任背书、行动引导。
3. 生成标题、前 3 秒钩子、完整口播、简介、话题标签、镜头建议。
4. 适合老板口播和商业转化。

输出 JSON 字段：title, hook, script, description, tags, shots, kb_refs。
'''.strip()
    payload = await _chat_json(settings, system, user, temperature=0.78)
    return normalize_copy(payload, req.industry or '原创短视频文案')


async def generate_edit_plan(settings: Settings, req: EditPlanRequest) -> EditPlanResponse:
    system = '你是短视频剪辑导演。根据文案生成可执行剪辑方案。必须输出严格 JSON。'
    user = f'''
标题：{req.title}
口播稿：
{req.script}

可用素材说明：{req.asset_summary or '未填写，默认使用老板口播、产品细节、公司环境、案例画面。'}
目标时长：{req.duration_seconds} 秒

请输出 JSON：
{{
  "rhythm": "整体剪辑节奏",
  "timeline": ["0-3秒：...", "3-8秒：..."],
  "broll_keywords": ["素材关键词"],
  "subtitle_style": "字幕风格",
  "music_style": "音乐风格",
  "cover_ideas": ["封面方案"]
}}
'''.strip()
    payload = await _chat_json(settings, system, user, temperature=0.65)
    return EditPlanResponse(
        rhythm=_as_str(payload, 'rhythm', '前 3 秒强钩子，中段快节奏信息密集，结尾强 CTA'),
        timeline=_as_list(payload, 'timeline') or ['0-3秒：强钩子字幕+老板正面口播', '3-20秒：痛点+解决方案+B-roll', '最后：信任背书+咨询引导'],
        broll_keywords=_as_list(payload, 'broll_keywords') or ['老板出镜', '产品细节', '公司环境', '客户案例'],
        subtitle_style=_as_str(payload, 'subtitle_style', '大号白字，关键词高亮，底部居中'),
        music_style=_as_str(payload, 'music_style', '轻快、专业、低音量铺底'),
        cover_ideas=_as_list(payload, 'cover_ideas') or ['老板头像+痛点标题+品牌色背景'],
    )


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except Exception:
        number = default
    return max(low, min(high, number))


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(low, min(high, number))


def _fallback_voice_segments(script: str, style: str, intensity: str) -> Dict[str, Any]:
    from re import split

    raw_parts = [x.strip() for x in split(r'(?<=[。！？!?；;\n])', script.replace('\r', '\n')) if x.strip()]
    if not raw_parts:
        raw_parts = [script.strip() or '今天先简单跟大家说一件事。']

    segments = []
    for index, text in enumerate(raw_parts[:18]):
        if index == 0:
            emotion = '开场钩子，有冲击力'
            speed = 1.08 if '快' in style or '钩子' in style else 1.03
            pause = 520
        elif index >= len(raw_parts[:18]) - 2:
            emotion = '收束转化，坚定可信'
            speed = 0.98
            pause = 650
        else:
            emotion = '痛点推进，真实有压迫感' if '压迫' in style or '老板' in style else '自然讲述'
            speed = 1.0
            pause = 420
        if intensity == '强烈':
            pause += 120
            speed += 0.03
        elif intensity == '轻微':
            pause = max(250, pause - 120)
            speed -= 0.03
        segments.append({
            'text': text,
            'emotion': emotion,
            'speed_ratio': round(max(0.85, min(1.2, speed)), 2),
            'volume_ratio': 1.08 if index == 0 else 1.0,
            'pitch_ratio': 1.0,
            'pause_after_ms': pause,
        })
    return {
        'style': style,
        'director_notes': ['DeepSeek 配音导演不可用时生成的兜底分段。', '已尽量按短句、停顿和情绪递进处理。'],
        'rewritten_script': '\n'.join(x['text'] for x in segments),
        'segments': segments,
    }


async def generate_voice_director(settings: Settings, req: 'VoiceDirectorRequest') -> 'VoiceDirectorResponse':
    from app.schemas import VoiceDirectorRequest, VoiceDirectorResponse, VoiceSegment

    system = (
        '你是短视频配音导演，专门把普通口播稿改成更像真人老板口播的分段配音稿。'
        '你必须输出严格 JSON。不要输出 Markdown。不要照抄长书面句。'
    )
    user = f'''
请把下面口播稿改造成“更有语调、更有停顿、更有情绪递进”的配音导演稿。

原始口播稿：
{req.script}

配音风格：{req.style}
情绪强度：{req.intensity}
目标时长：{req.target_seconds} 秒
目标客户：{req.audience or '未填写'}
核心卖点：{req.selling_points or '未填写'}

要求：
1. 不要变成广告腔，要像真人老板在镜头前说话。
2. 使用短句，适合 TTS 分段生成。
3. 第一段必须是强钩子；中段痛点逐步推进；结尾给明确行动引导。
4. 不要添加 [停顿]、括号、SSML 标签，因为这些会被读出来。
5. 每段 text 控制在 8 到 45 个汉字左右。
6. speed_ratio 范围 0.85-1.20；pitch_ratio 范围 0.92-1.08；volume_ratio 范围 0.90-1.20；pause_after_ms 范围 200-1200。

输出 JSON：
{{
  "style": "风格名",
  "director_notes": ["给操作者看的配音建议"],
  "rewritten_script": "所有分段合并后的最终口播稿",
  "segments": [
    {{"text":"分段口播文本","emotion":"这一段的情绪/说法","speed_ratio":1.05,"volume_ratio":1.05,"pitch_ratio":1.0,"pause_after_ms":500}}
  ]
}}
'''.strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.72, timeout=90)
    except Exception:
        payload = _fallback_voice_segments(req.script, req.style, req.intensity)

    raw_segments = payload.get('segments') or []
    segments: list[VoiceSegment] = []
    if isinstance(raw_segments, list):
        for item in raw_segments[:24]:
            if not isinstance(item, dict):
                continue
            text = str(item.get('text') or '').strip()
            if not text:
                continue
            segments.append(VoiceSegment(
                text=text,
                emotion=str(item.get('emotion') or '自然可信')[:80],
                speed_ratio=_clamp_float(item.get('speed_ratio'), 1.0, 0.5, 2.0),
                volume_ratio=_clamp_float(item.get('volume_ratio'), 1.0, 0.2, 3.0),
                pitch_ratio=_clamp_float(item.get('pitch_ratio'), 1.0, 0.5, 2.0),
                pause_after_ms=_clamp_int(item.get('pause_after_ms'), 350, 0, 3000),
            ))
    if not segments:
        payload = _fallback_voice_segments(req.script, req.style, req.intensity)
        segments = [VoiceSegment(**x) for x in payload['segments']]

    rewritten_script = str(payload.get('rewritten_script') or '\n'.join(seg.text for seg in segments)).strip()
    notes = payload.get('director_notes') or []
    if isinstance(notes, str):
        notes = [notes]
    notes = [str(x) for x in notes if str(x).strip()][:8]
    return VoiceDirectorResponse(
        style=str(payload.get('style') or req.style),
        director_notes=notes,
        rewritten_script=rewritten_script,
        segments=segments,
    )
