from __future__ import annotations

import json
from typing import Any, Dict, List

from app.config import Settings
from app.schemas import (
    EditPlanResponse,
    GeneratedCopy,
    OneClickGenerateRequest,
    OneClickGenerateResponse,
    ShootingPlanResponse,
    ShotTask,
    SubtitleEmphasisResponse,
    SubtitleKeyword,
    VoiceDirectorResponse,
    VoiceSegment,
)
from app.services.deepseek import normalize_copy, _as_list, _as_str
from app.services.llm import LLMError, chat_json


def _voice_segment_from_dict(item: Dict[str, Any]) -> VoiceSegment:
    return VoiceSegment(
        text=str(item.get('text') or item.get('content') or '这里补充一段口播。')[:800],
        emotion=str(item.get('emotion') or '自然可信')[:80],
        speed_ratio=float(item.get('speed_ratio') or 1.0),
        volume_ratio=float(item.get('volume_ratio') or 1.0),
        pitch_ratio=float(item.get('pitch_ratio') or 1.0),
        pause_after_ms=int(item.get('pause_after_ms') or 380),
    )


def _fallback(req: OneClickGenerateRequest, warning: str = '') -> OneClickGenerateResponse:
    topic = req.industry or '行业获客短视频'
    hook = f'如果你正在考虑{topic}，先别急着做决定。'
    script = f'''{hook}
很多人一上来只看价格、只看表面资料，最后真正影响结果的关键点反而没搞清楚。
我们会先看你的目标、预算、时间、家庭规划和风险边界，再判断什么方案适合你。
这件事不是让你马上成交，而是先帮你少走弯路。
如果你也想做一次清晰的判断，可以先私信我，把你的情况简单说一下。'''
    copy = GeneratedCopy(
        title=f'{topic}别只看表面',
        hook=hook,
        script=script,
        description='先做需求判断，再决定方案；适合正在认真比较的人。',
        tags=['老板口播', '获客', '咨询', topic[:12]],
        shots=['老板正面口播', '痛点大字字幕', '服务流程截图', '客户咨询场景', '结尾私信引导'],
        kb_refs=[],
    )
    segments = [VoiceSegment(text=x.strip(), emotion='提醒感', speed_ratio=1.0, volume_ratio=1.0, pitch_ratio=1.0, pause_after_ms=420) for x in script.split('\n') if x.strip()]
    return OneClickGenerateResponse(
        project_title=copy.title,
        summary='已生成一套可同步到文案、配音、拍摄、剪辑和发布模块的一键方案。',
        copy=copy,
        voice_director=VoiceDirectorResponse(style=req.style, director_notes=['开头压痛点，中段给判断标准，结尾引导私信。'], rewritten_script=script, segments=segments),
        shooting_plan=ShootingPlanResponse(
            summary='围绕老板口播 + 资料/B-roll 快切完成拍摄。',
            shot_tasks=[ShotTask(scene='老板开场口播', duration='0-5秒', camera='正面半身，轻微推近', content=hook, props='干净背景/办公桌', priority='必拍')],
            broll_list=['客户咨询截图打码', '服务流程图', '案例资料局部', '行业城市/项目环境素材'],
            teleprompter=[s.text for s in segments],
            checklist=['确认真人形象/声音授权', '确认违禁词和夸大承诺', '确认结尾 CTA'],
        ),
        edit_plan=EditPlanResponse(
            rhythm='前 3 秒强痛点，中段每 4-6 秒切一个素材，结尾 CTA 定格。',
            timeline=['0-3秒：痛点字幕放大', '3-18秒：老板口播 + 素材快切', '18-30秒：流程/信任背书', '结尾：私信咨询引导'],
            broll_keywords=['咨询', '资料', '流程', '案例', '城市/行业场景'],
            subtitle_style='抖音口播大字字幕，关键词高亮，短句分行，重点词放大。',
            music_style='低音量轻节奏，不压人声。',
            cover_ideas=[copy.title, hook[:20]],
            warnings=[],
        ),
        subtitle=SubtitleEmphasisResponse(
            template='大字居中 + 关键词高亮 + 逐句弹出',
            keywords=[SubtitleKeyword(word='先别急', reason='制造停顿', effect='放大高亮'), SubtitleKeyword(word='少走弯路', reason='痛点承诺', effect='描边高亮')],
            srt_tips=['用 ASR 重新识别最终音频生成时间戳', '每行不超过 12 个汉字', '痛点词、数字和 CTA 做高亮'],
            cover_text_options=[copy.title, '先别急着决定', '少走弯路'],
        ),
        image_prompts=[f'中文商业短视频封面，主题：{copy.title}，大字标题，干净专业，竖版 9:16'],
        publish_title=copy.title,
        publish_description=copy.description,
        next_actions=['同步到文案模块细改', '生成配音分段', '选择数字人或素材混剪', '用 ASR 校对字幕后合成视频'],
        warnings=[warning] if warning else [],
        raw={},
    )


def _normalize_oneclick(req: OneClickGenerateRequest, payload: Dict[str, Any]) -> OneClickGenerateResponse:
    copy = normalize_copy(payload.get('copy') or payload, req.industry or '一键短视频')
    voice = payload.get('voice_director') or {}
    raw_segments = voice.get('segments') or payload.get('segments') or []
    segments = [_voice_segment_from_dict(x) for x in raw_segments if isinstance(x, dict)]
    if not segments:
        segments = [VoiceSegment(text=x.strip(), emotion='自然可信', speed_ratio=1.0, volume_ratio=1.0, pitch_ratio=1.0, pause_after_ms=380) for x in copy.script.split('\n') if x.strip()]
    if not segments:
        segments = [VoiceSegment(text=copy.script[:700], emotion='自然可信', speed_ratio=1.0, volume_ratio=1.0, pitch_ratio=1.0, pause_after_ms=380)]

    shooting = payload.get('shooting_plan') or {}
    shot_tasks: List[ShotTask] = []
    for item in shooting.get('shot_tasks') or []:
        if isinstance(item, dict):
            shot_tasks.append(ShotTask(
                scene=str(item.get('scene') or '口播镜头'),
                duration=str(item.get('duration') or '3-5秒'),
                camera=str(item.get('camera') or '正面口播'),
                content=str(item.get('content') or ''),
                props=str(item.get('props') or ''),
                priority=str(item.get('priority') or '必拍'),
            ))
    if not shot_tasks:
        shot_tasks = [ShotTask(scene='老板口播', duration='0-8秒', camera='正面半身', content=copy.hook, props='办公室/服务资料', priority='必拍')]

    edit = payload.get('edit_plan') or {}
    subtitle = payload.get('subtitle') or {}
    keywords = []
    for item in subtitle.get('keywords') or []:
        if isinstance(item, dict):
            keywords.append(SubtitleKeyword(word=str(item.get('word') or ''), reason=str(item.get('reason') or ''), effect=str(item.get('effect') or '放大高亮')))
        elif str(item).strip():
            keywords.append(SubtitleKeyword(word=str(item), reason='重点词', effect='高亮'))
    return OneClickGenerateResponse(
        project_title=str(payload.get('project_title') or copy.title),
        summary=str(payload.get('summary') or '一键方案已生成，可同步到各步骤模块。'),
        copy=copy,
        voice_director=VoiceDirectorResponse(
            style=str(voice.get('style') or req.style),
            director_notes=_as_list(voice, 'director_notes') or ['开头强钩子，中段短句推进，结尾明确行动。'],
            rewritten_script=str(voice.get('rewritten_script') or copy.script),
            segments=segments[:30],
        ),
        shooting_plan=ShootingPlanResponse(
            summary=str(shooting.get('summary') or '按口播分段补拍素材。'),
            shot_tasks=shot_tasks[:20],
            broll_list=_as_list(shooting, 'broll_list') or copy.shots,
            teleprompter=_as_list(shooting, 'teleprompter') or [s.text for s in segments],
            checklist=_as_list(shooting, 'checklist') or ['确认授权', '确认口播', '确认字幕和封面'],
        ),
        edit_plan=EditPlanResponse(
            rhythm=str(edit.get('rhythm') or '前 3 秒强钩子，中段快切，结尾 CTA。'),
            timeline=_as_list(edit, 'timeline') or ['0-3 秒：痛点钩子', '3-25 秒：方案解释', '结尾：私信引导'],
            broll_keywords=_as_list(edit, 'broll_keywords') or copy.shots,
            subtitle_style=str(edit.get('subtitle_style') or '大字口播字幕，关键词高亮。'),
            music_style=str(edit.get('music_style') or '轻节奏，不压人声。'),
            cover_ideas=_as_list(edit, 'cover_ideas') or [copy.title, copy.hook[:24]],
            warnings=_as_list(edit, 'warnings'),
        ),
        subtitle=SubtitleEmphasisResponse(
            template=str(subtitle.get('template') or '抖音口播大字字幕，关键词高亮。'),
            keywords=keywords[:20],
            srt_tips=_as_list(subtitle, 'srt_tips') or ['最终以 ASR 时间戳为准', '短句分行', '重点词放大高亮'],
            cover_text_options=_as_list(subtitle, 'cover_text_options') or [copy.title, copy.hook[:18]],
        ),
        image_prompts=_as_list(payload, 'image_prompts') or [f'中文短视频封面，主题：{copy.title}，竖版 9:16，醒目大字，商业获客风格'],
        publish_title=str(payload.get('publish_title') or copy.title),
        publish_description=str(payload.get('publish_description') or copy.description),
        next_actions=_as_list(payload, 'next_actions') or ['同步文案', '生成配音', '选择数字人/素材', '合成视频'],
        warnings=_as_list(payload, 'warnings'),
        raw=payload,
    )


async def generate_one_click(settings: Settings, req: OneClickGenerateRequest) -> OneClickGenerateResponse:
    system = '你是短视频获客生产线总导演。负责一次性生成文案、分镜、配音导演、剪辑计划、字幕风格、图文海报提示词和发布文案。必须输出严格 JSON，不能输出 markdown。'
    user = f'''
请为以下项目生成一套可以直接同步到系统各模块的“一键生成方案”。
行业：{req.industry or '未填写'}
目标客户：{req.audience or '未填写'}
核心卖点：{req.selling_points or '未填写'}
内容风格：{req.style}
目标时长：{req.duration_seconds} 秒
转化目标：{req.goal}
输出类型：{req.output_type}
素材方式：{req.material_mode}
已选素材：{', '.join(req.selected_asset_names) or '暂无'}
参考内容/历史上下文：
{req.reference_text or '暂无'}
额外要求：
{req.instruction or '适合老板口播、数字人或素材混剪；字幕要有抖音口播效果，不要太干。'}

输出 JSON 顶层字段：
project_title, summary, copy, voice_director, shooting_plan, edit_plan, subtitle, image_prompts, publish_title, publish_description, next_actions, warnings。

字段要求：
copy={{title, hook, script, description, tags, shots, kb_refs}}
voice_director={{style, director_notes, rewritten_script, segments}}，segments 每项必须有 text, emotion, speed_ratio, volume_ratio, pitch_ratio, pause_after_ms。
shooting_plan={{summary, shot_tasks, broll_list, teleprompter, checklist}}，shot_tasks 每项必须有 scene, duration, camera, content, props, priority。
edit_plan={{rhythm, timeline, broll_keywords, subtitle_style, music_style, cover_ideas, warnings}}
subtitle={{template, keywords, srt_tips, cover_text_options}}，keywords 每项必须有 word, reason, effect。
image_prompts 给 3 条中文海报/封面生成提示词，适合 Qwen-Image 或即梦图片生成。
'''.strip()
    try:
        payload = await chat_json(settings, system, user, temperature=0.68, timeout=120)
        return _normalize_oneclick(req, payload)
    except Exception as exc:
        return _fallback(req, f'AI 一键生成调用失败，已用本地兜底方案：{type(exc).__name__}: {str(exc)[:300]}')


async def revise_one_click(settings: Settings, current: OneClickGenerateResponse, instruction: str, *, industry: str = '', audience: str = '', selling_points: str = '') -> OneClickGenerateResponse:
    system = '你是短视频项目修改助手。用户会给出当前完整方案和修改意见，你要只修改必要字段，同时保持结构完整。必须输出严格 JSON。'
    user = f'''
当前行业：{industry}
目标客户：{audience}
核心卖点：{selling_points}
用户修改要求：{instruction}

当前方案 JSON：
{json.dumps(current.model_dump(), ensure_ascii=False)}

请输出与当前方案同结构 JSON：project_title, summary, copy, voice_director, shooting_plan, edit_plan, subtitle, image_prompts, publish_title, publish_description, next_actions, warnings。
要求：
1. 文案修改必须同步更新配音分段、字幕关键词、发布文案。
2. 如果用户只要求改字幕/封面，不要大改口播脚本。
3. 保持中文口语化、抖音口播感、合规不夸大。
'''.strip()
    try:
        payload = await chat_json(settings, system, user, temperature=0.55, timeout=120)
        return _normalize_oneclick(OneClickGenerateRequest(industry=industry, audience=audience, selling_points=selling_points), payload)
    except Exception as exc:
        out = current.model_copy(deep=True)
        out.warnings.append(f'AI 修改失败，保留原方案：{type(exc).__name__}: {str(exc)[:300]}')
        return out
