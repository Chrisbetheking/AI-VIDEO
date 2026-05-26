from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.services.llm import LLMError, chat_json, test_llm
from app.schemas import CopyRequest, EditPlanRequest, EditPlanResponse, GeneratedCopy, RewriteFromInspirationRequest, VoiceDirectorRequest, VoiceDirectorResponse, LeadAcquisitionRequest, LeadAcquisitionPlanResponse, LeadChannelPlaybook, LeadDataSource, LeadInterceptionOpportunity


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
    try:
        return await chat_json(settings, system, user, temperature=temperature, timeout=timeout)
    except LLMError as exc:
        raise DeepSeekError(str(exc)) from exc


async def test_deepseek(settings: Settings, api_key_override: Optional[str] = None) -> Dict[str, Any]:
    try:
        return await test_llm(settings, api_key_override=api_key_override)
    except LLMError as exc:
        raise DeepSeekError(str(exc)) from exc


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


async def generate_lead_acquisition_plan(settings: Settings, req: LeadAcquisitionRequest) -> LeadAcquisitionPlanResponse:
    channels = req.channels or ['热度雷达', '抖音养号', '采集目标客户', '自动监听', '自动回复', '目标用户导流私域']
    system = '你是海外房产行业的增长数据分析负责人，目标不是拍摄，而是通过真实搜索词、评论、竞品内容和线索表单发现高热度获客机会。必须输出严格 JSON，不能编造已采集数据；没有真实接入时要标注为待接入/待验证。'
    user = f"""
请为以下业务生成一套可执行的每日热度雷达与获客机会图。
行业：{req.industry or '海外房产置业 / 第二家园'}
目标客户：{req.audience or '有海外置业、第二家园、子女教育、养老度假和资产配置需求的人群'}
核心卖点：{req.selling_points or '海外第二家园规划、项目筛选、置业流程、生活配套与长期服务'}
内容风格：{req.style or '专业可信、真实案例、顾问式成交'}
获客地域/人群：{req.lead_region or '华人家庭、企业主、高净值人群、海外生活规划人群'}
转化目标：{req.conversion_goal or '私信咨询 / 表单留资 / 进入微信私域'}
业务定位：{req.business_positioning or req.industry or '中国人在海外房产置业'}
客户分层：{req.customer_segments or req.fixed_options or '教育规划家庭、资产配置家庭、养老度假家庭、第二居所家庭'}
私域承接物：{req.private_domain_assets or '避坑报告、预算测算表、置业流程图、国际学校清单'}
内容栏目：{req.content_pillars or '避坑、流程、预算、教育、身份、案例、说明会'}
拍摄/提示词要求：{req.shooting_brief or '给出可拍镜头、口播提词、B-roll 和封面标题'}
报告/微信承接方式：{req.report_delivery or '评论关键词或私信领取资料，再进入微信做需求筛选'}
可选固定人群/场景：{req.fixed_options or '无'}
重点数据源/渠道：{', '.join(channels)}
用户选择的数据源：{', '.join(req.data_sources or []) or '未配置'}
竞品账号：{', '.join(req.competitor_accounts or []) or '未录入'}
手动导入搜索/评论数据：{req.search_query_import or '暂无'}
同行/内容沉淀：
{req.competitor_notes or '暂无'}
监控关键词：{req.trend_keywords or '海外房产,第二家园,海外置业,移居,资产配置'}
历史记忆：
{req.existing_context or '暂无'}

输出 JSON 字段：
{{
  "overview": "一句话总策略",
  "audience_segments": ["目标客户分层"],
  "channel_playbook": [{{"channel":"渠道名", "goal":"目标", "actions":["动作"], "automation":["自动化动作"], "required_inputs":["需要录入的数据"], "success_metric":"判断指标"}}],
  "listening_keywords": ["监听关键词"],
  "content_triggers": ["触发拍摄/发视频的条件"],
  "reply_templates": ["评论/私信自动回复模板"],
  "private_domain_sop": ["私域承接步骤"],
  "daily_automation_tasks": ["每天后台自动执行任务"],
  "next_actions": ["下一步人工确认事项"],
  "content_matrix": ["可直接生成的选题/栏目"],
  "lead_magnets": ["可领取的报告/清单/测算表"],
  "shooting_prompts": ["把热度机会转成口播/图文的方向，不要写成拍摄任务"],
  "required_integrations": ["真实数据需要接入的平台/API/人工导入表"],
  "data_sources": [{{"name":"数据源", "status":"已接入/待接入", "purpose":"用途", "required_fields":["需要的环境变量或授权"], "next_step":"下一步"}}],
  "interception_opportunities": [{{"score":90, "source":"平台/来源", "keyword":"真实或待验证关键词", "intent":"客户意图", "action":"截流动作", "asset":"承接资料包"}}],
  "monitoring_sop": ["每天如何采集、去重、评分、分发给内容/私域"],
  "compliance_notes": ["采集/投放/回复需要注意的合规边界"]
}}

要求：
1. 热度雷达只输出“数据源、关键词、评论问题、竞品流量、承接动作”，不要把拍摄任务混在这里。
2. 真实数据没有接入时，必须写“待接入/待验证”，不要装成已经采集。
3. 重点围绕资格判断、城市比较、项目筛选、税费测算、MM2H/第二家园这五类高意向场景。
4. 自动化要落到系统能执行的动作：API授权、关键词监听、评论采集、线索表单、网页报告、私信/企微承接。
5. 合规提醒要明确：只处理公开/授权数据，微信海外房产更适合私域承接而不是直接买量。
6. 语气专业，不要出现“我认为”“可能可以”这种犹豫表达。
""".strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.62, timeout=90)
        playbook = []
        for item in payload.get('channel_playbook') or []:
            if isinstance(item, dict):
                playbook.append(LeadChannelPlaybook(
                    channel=str(item.get('channel') or '获客渠道'),
                    goal=str(item.get('goal') or ''),
                    actions=_as_list(item, 'actions'),
                    automation=_as_list(item, 'automation'),
                    required_inputs=_as_list(item, 'required_inputs'),
                    success_metric=str(item.get('success_metric') or ''),
                ))
        if not playbook:
            raise ValueError('empty playbook')
        data_sources = []
        for item in payload.get('data_sources') or []:
            if isinstance(item, dict):
                data_sources.append(LeadDataSource(
                    name=str(item.get('name') or '数据源'),
                    status=str(item.get('status') or '待接入'),
                    purpose=str(item.get('purpose') or ''),
                    required_fields=_as_list(item, 'required_fields'),
                    next_step=str(item.get('next_step') or ''),
                ))
        opportunities = []
        for item in payload.get('interception_opportunities') or []:
            if isinstance(item, dict):
                opportunities.append(LeadInterceptionOpportunity(
                    score=int(item.get('score') or 70),
                    source=str(item.get('source') or ''),
                    keyword=str(item.get('keyword') or ''),
                    intent=str(item.get('intent') or ''),
                    action=str(item.get('action') or ''),
                    asset=str(item.get('asset') or ''),
                ))
        return LeadAcquisitionPlanResponse(
            overview=_as_str(payload, 'overview', '以同行打法为输入，围绕海外第二家园客户建立内容、互动、私域三段式获客闭环。'),
            audience_segments=_as_list(payload, 'audience_segments') or ['子女教育家庭', '资产配置型企业主', '养老度假型家庭', '海外生活规划人群'],
            channel_playbook=playbook,
            listening_keywords=_as_list(payload, 'listening_keywords') or ['海外置业', '第二家园', '海外房产', '子女教育', '退休养老'],
            content_triggers=_as_list(payload, 'content_triggers') or ['同行爆款出现高频痛点', '评论区集中询问国家/预算/身份', '政策/汇率/项目节点变化'],
            reply_templates=_as_list(payload, 'reply_templates') or ['可以先看你的预算、家庭规划和目标国家，再判断适不适合。', '这个问题不能只看房价，要一起看生活半径、持有成本和退出路径。'],
            private_domain_sop=_as_list(payload, 'private_domain_sop') or ['评论区识别意向', '私信发送筛选问题', '进入微信后做需求表', '按预算和国家生成方案'],
            daily_automation_tasks=_as_list(payload, 'daily_automation_tasks') or ['采集同行新视频', '汇总评论区高频问题', '生成今日选题', '更新自动回复模板'],
            next_actions=_as_list(payload, 'next_actions') or ['补充竞品账号', '确认目标国家和项目类型', '录入客户常见问题'],
            content_matrix=_as_list(payload, 'content_matrix') or ['避坑类：海外置业最容易踩的 3 个坑', '教育类：国际学校和第二家园怎么一起规划', '预算类：几百万预算如何配置海外资产', '流程类：中国人买房从咨询到交付完整流程'],
            lead_magnets=_as_list(payload, 'lead_magnets') or ['《海外置业避坑报告》', '《第二家园身份规划清单》', '《预算测算表》', '《国际学校择校清单》'],
            shooting_prompts=_as_list(payload, 'shooting_prompts') or ['把税费/流程/资格判断转成 30 秒口播', '把城市比较转成 5 页图文', '把 MM2H 问题转成 FAQ 视频'],
            required_integrations=_as_list(payload, 'required_integrations') or ['百度营销/关键词规划师', '巨量引擎 Marketing API', '抖音开放平台评论/关键词视频搜索', '小红书数据源或 CSV 导入', '企业微信/SCRM'],
            data_sources=data_sources or [
                LeadDataSource(name='百度搜索 / 百度营销', status='待接入', purpose='搜索词、关键词规划和线索', required_fields=['BAIDU_MARKETING_APP_ID','BAIDU_MARKETING_SECRET','BAIDU_MARKETING_ACCESS_TOKEN'], next_step='申请百度营销开发者并授权广告账号'),
                LeadDataSource(name='巨量引擎 / 抖音搜索', status='待接入', purpose='抖音搜索、广告报表、线索表单和内容热度', required_fields=['OCEANENGINE_APP_ID','OCEANENGINE_SECRET','OCEANENGINE_ACCESS_TOKEN'], next_step='开通巨量引擎开放平台 Marketing API'),
            ],
            interception_opportunities=opportunities or [
                LeadInterceptionOpportunity(score=92, source='百度搜索', keyword='马来西亚买房税费怎么算', intent='税费测算/交易前教育', action='做税费测算页 + 评论/私信领取测算表', asset='《马来西亚买房税费测算表》'),
                LeadInterceptionOpportunity(score=88, source='抖音搜索/评论', keyword='马来西亚第二家园一定要买房吗', intent='MM2H/身份规划', action='做问答短视频 + 私信“身份”领取对照表', asset='《MM2H 与购房要求对照表》'),
            ],
            monitoring_sop=_as_list(payload, 'monitoring_sop') or ['每日拉取关键词/评论/线索表', 'AI 去重并按转化意图评分', '高分机会推送到内容生产和私域回复', '转化数据回写行业档案'],
            compliance_notes=_as_list(payload, 'compliance_notes') or ['只采集公开或授权数据', '竞品内容只能学习结构，不能照抄', '微信生态优先做私域承接和资料发送'],
        )
    except Exception:
        return LeadAcquisitionPlanResponse(
            overview='围绕海外第二家园客户建立“同行打法学习—内容触发—评论私信承接—微信私域跟进”的获客闭环。',
            audience_segments=['子女教育规划家庭', '企业主资产配置人群', '养老度假第二居所人群', '海外生活方式升级人群'],
            channel_playbook=[
                LeadChannelPlaybook(channel='抖音热度获客', goal='承接同行内容下的同类需求', actions=['监控同行爆款选题和评论高频问题', '用同结构不同表达发布观点型视频', '在评论和私信中引导做需求筛选'], automation=['自动采集同行口令/视频', '提炼钩子公式', '生成对应海外置业选题'], required_inputs=['竞品账号', '目标国家', '客户预算段'], success_metric='私信率、留资率、微信添加率'),
                LeadChannelPlaybook(channel='博主联动流量', goal='通过同领域内容形成关联曝光', actions=['建立相关博主库', '围绕相同热点做不同角度视频', '用评论区问题反推下一条内容'], automation=['自动学习博主钩子和选题节奏', '生成联动选题清单'], required_inputs=['博主主页链接', '账号定位备注'], success_metric='关联话题播放量、评论转私信数量'),
                LeadChannelPlaybook(channel='自动监听', goal='持续发现潜在线索和选题机会', actions=['监听海外房产、第二家园、子女教育、养老度假等关键词', '记录高频疑问', '触发内容生产'], automation=['每日后台采集学习', '生成行业雷达', '更新回复模板'], required_inputs=['关键词', '目标客群', '服务国家/城市'], success_metric='每日有效选题数、线索问题命中率'),
                LeadChannelPlaybook(channel='自动回复', goal='把评论和私信导向需求诊断', actions=['准备不同客户分层回复', '优先问预算、国家、用途、时间', '把泛流量筛成有效咨询'], automation=['生成评论回复模板', '生成私信筛选问题', '沉淀高意向话术'], required_inputs=['FAQ', '服务边界', '顾问联系方式'], success_metric='回复率、有效需求表完成率'),
                LeadChannelPlaybook(channel='私域承接', goal='把短视频流量转成可跟进客户', actions=['微信承接后发需求表', '根据预算和用途分层', '安排资料包或顾问咨询'], automation=['生成私域欢迎语', '生成客户分层标签', '生成下一步跟进提醒'], required_inputs=['微信话术', '客户标签', '项目资料'], success_metric='微信添加率、有效咨询率、预约率'),
            ],
            listening_keywords=['海外房产', '第二家园', '海外置业', '子女教育', '养老度假', '资产配置', '移居规划', '海外生活'],
            content_triggers=['同行出现高互动钩子', '评论区集中问预算/国家/流程', '项目政策或汇率变化', '客户案例可讲述'],
            reply_templates=['你这个情况要先看用途：自住、教育、养老还是资产配置，不同目的选法完全不同。', '可以先发我预算区间和目标国家，我帮你判断适合看哪类第二家园方案。', '海外置业不能只看价格，生活半径、持有成本和后期退出都要一起看。'],
            private_domain_sop=['评论区用问题筛选意向', '私信发送 4 个需求问题', '加微信后打标签：教育/养老/投资/自住', '发送匹配资料包', '安排顾问沟通或项目说明'],
            daily_automation_tasks=['采集同行账号新视频', '提炼今日钩子公式', '整理评论区高频问题', '生成 3 个海外第二家园选题', '更新自动回复模板'],
            next_actions=['录入 5 个同领域博主账号', '确认主推国家/城市', '整理常见客户问题', '准备 3 个真实案例素材'],
            content_matrix=['避坑类：海外买房别只看价格', '教育类：国际学校和第二家园怎么一起规划', '预算类：几百万预算怎么配置海外资产', '身份类：第二家园适合哪些家庭', '案例类：真实客户从咨询到落地的过程'],
            lead_magnets=['《马来西亚第二家园避坑报告》', '《海外置业预算测算表》', '《马来西亚国际学校择校清单》', '《置业流程图》', '《线下说明会名额》'],
            shooting_prompts=['把高分截流词转成口播/图文选题', '把评论区高频疑问转成 FAQ 内容', '把资料包钩子接到发布文案和私信回复'],
            required_integrations=['百度营销/关键词规划师', '巨量引擎 Marketing API', '抖音开放平台评论/关键词视频搜索', '小红书数据源或 CSV 导入', '企业微信/SCRM'],
            data_sources=[
                LeadDataSource(name='百度搜索 / 百度营销', status='待接入', purpose='搜索词、关键词规划和线索', required_fields=['BAIDU_MARKETING_APP_ID','BAIDU_MARKETING_SECRET','BAIDU_MARKETING_ACCESS_TOKEN'], next_step='申请百度营销开发者并授权广告账号'),
                LeadDataSource(name='巨量引擎 / 抖音搜索', status='待接入', purpose='抖音搜索、广告报表、线索表单和内容热度', required_fields=['OCEANENGINE_APP_ID','OCEANENGINE_SECRET','OCEANENGINE_ACCESS_TOKEN'], next_step='开通巨量引擎开放平台 Marketing API'),
                LeadDataSource(name='抖音开放平台', status='可接入', purpose='关键词视频搜索和授权评论管理', required_fields=['DOUYIN_CLIENT_KEY','DOUYIN_CLIENT_SECRET','DOUYIN_ACCESS_TOKEN'], next_step='申请关键词视频搜索和评论管理能力'),
                LeadDataSource(name='小红书数据源', status='建议第三方/导入', purpose='笔记标题、评论问题和图文趋势', required_fields=['CSV 导入或数据服务商 Key'], next_step='先用 CSV/链接导入，后续接合规数据商'),
            ],
            interception_opportunities=[
                LeadInterceptionOpportunity(score=92, source='百度搜索', keyword='马来西亚买房税费怎么算', intent='税费测算/交易前教育', action='做税费测算页 + 评论/私信领取测算表', asset='《马来西亚买房税费测算表》'),
                LeadInterceptionOpportunity(score=88, source='抖音搜索/评论', keyword='马来西亚第二家园一定要买房吗', intent='MM2H/身份规划', action='做问答短视频 + 私信“身份”领取对照表', asset='《MM2H 与购房要求对照表》'),
                LeadInterceptionOpportunity(score=86, source='小红书图文', keyword='Mont Kiara 国际学校附近公寓', intent='教育家庭/城市筛选', action='做 5 页图文包 + 私信“学校”领取清单', asset='《马来西亚国际学校择校清单》'),
                LeadInterceptionOpportunity(score=84, source='竞品评论区', keyword='吉隆坡和新山哪里更值得买', intent='城市比较/项目筛选', action='做对比内容 + 领取城市对比表', asset='《吉隆坡 vs 新山选盘表》'),
            ],
            monitoring_sop=['每日拉取关键词/评论/线索表', 'AI 去重并按转化意图评分', '高分机会推送到内容生产和私域回复', '转化数据回写行业档案'],
            compliance_notes=['只采集公开或授权数据', '竞品内容只能学习结构，不能照抄', '微信生态优先做私域承接和资料发送'],
        )


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


async def refine_copy_with_instruction(settings: Settings, req: 'CopyRefineRequest') -> GeneratedCopy:
    from app.schemas import CopyRefineRequest

    system = '你是短视频文案总监，负责按用户细节要求精修文案。必须输出严格 JSON，不要 Markdown。'
    user = f'''
请按用户修改要求精修下面短视频文案。

用户修改要求：{req.instruction}
行业：{req.industry or '未填写'}
目标客户：{req.audience or '未填写'}
核心卖点：{req.selling_points or '未填写'}

当前标题：{req.title}
当前开头钩子：{req.hook}
当前口播稿：
{req.script}

当前简介：{req.description}
当前标签：{', '.join(req.tags)}
当前镜头建议：{', '.join(req.shots)}

要求：
1. 可以细改标题、钩子、口播、简介、标签和镜头建议。
2. 不要变书面稿，要像真人老板短视频口播。
3. 不要增加无法证明的夸大承诺。
4. 输出 JSON 字段：title, hook, script, description, tags, shots, kb_refs。
'''.strip()
    payload = await _chat_json(settings, system, user, temperature=0.68, timeout=90)
    result = normalize_copy(payload, req.title or '精修短视频文案')
    result.kb_refs = (result.kb_refs or []) + [f'已按要求精修：{req.instruction[:80]}']
    return result


async def video_edit_chat_advice(settings: Settings, instruction: str, title: str = '', script: str = '', asset_summary: str = '') -> dict:
    system = '你是短视频后期剪辑导演，会把用户自然语言修改要求转成可执行剪辑动作和人工建议。必须输出严格 JSON。'
    user = f'''
当前视频标题：{title or '未填写'}
当前口播稿：
{script or '未填写'}
可用素材：{asset_summary or '未填写'}
用户修改要求：{instruction}

请输出 JSON：
{{
  "assistant_message": "给用户看的简短回复",
  "summary": "本次修改/建议摘要",
  "actions": ["执行或建议的动作"],
  "warnings": ["限制或风险提示"]
}}

注意：如果用户要求自动发布、下载非授权视频、搬运，请提醒只做授权素材和原创改写。
'''.strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.55, timeout=60)
    except Exception:
        payload = {
            'assistant_message': '我会按你的要求尽量用插件修改视频；复杂剪辑会先给出可执行建议。',
            'summary': '已接收剪辑修改要求。',
            'actions': ['根据关键词尝试裁剪、调速、加字幕或重新导出 9:16 视频'],
            'warnings': [],
        }
    return {
        'assistant_message': str(payload.get('assistant_message') or '已收到剪辑修改要求。'),
        'summary': str(payload.get('summary') or '已生成剪辑建议。'),
        'actions': [str(x) for x in (payload.get('actions') or []) if str(x).strip()][:10],
        'warnings': [str(x) for x in (payload.get('warnings') or []) if str(x).strip()][:10],
    }


async def generate_trend_radar(settings: Settings, req: 'TrendRadarRequest') -> 'TrendRadarResponse':
    from app.schemas import TrendItem, TrendRadarRequest, TrendRadarResponse

    system = '你是短视频行业趋势和本地获客运营分析师。必须输出严格 JSON，不要 Markdown。'
    user = f'''
请基于下面信息生成“行业爆点/选题雷达”。不要编造实时平台数据；如果没有实时数据，就基于行业常见趋势和用户提供的同行内容做可执行选题建议。

行业：{req.industry or '未填写'}
目标客户：{req.audience or '未填写'}
地域/市场：{req.region or '未填写'}
监控关键词：{', '.join(req.keywords) or '未填写'}
同行备注/采集内容：
{req.competitor_notes or '未填写'}

输出 JSON：
{{
  "summary":"整体判断",
  "hot_topics":[{{"title":"爆点/选题","reason":"为什么值得做","heat":80,"angle":"切入角度","suggested_hook":"前三秒钩子","risk":"风险提示"}}],
  "content_angles":["可持续拍的内容角度"],
  "shooting_suggestions":["今天/本周建议拍什么"],
  "monitor_keywords":["后续监控关键词"],
  "next_actions":["下一步动作"]
}}
'''.strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.68, timeout=90)
    except Exception:
        payload = {
            'summary': f'{req.industry or "当前行业"}建议围绕客户痛点、同行截流、降本增效和真实案例做选题。',
            'hot_topics': [
                {'title': '客户被同行截走', 'reason': '焦虑感强，适合本地老板获客场景', 'heat': 82, 'angle': '先指出损失，再给解决路径', 'suggested_hook': '不是客户少了，是他们还没找到你就被同行截走了。', 'risk': '避免夸大承诺'},
                {'title': '自然流量不稳定', 'reason': '能引出内容+投流组合方案', 'heat': 76, 'angle': '对比等流量和主动获客', 'suggested_hook': '还在等自然流量？同行已经开始主动拿客户了。', 'risk': '不要暗示必须投流才有效'},
            ],
            'content_angles': ['老板口播痛点拆解', '客户案例复盘', '同行打法对比', '拍摄/投流误区纠正'],
            'shooting_suggestions': ['拍老板正面口播 3 条', '补拍办公室/客户沟通/产品细节 B-roll', '拍一条真实案例流程'],
            'monitor_keywords': req.keywords or ['获客', '投流', '同城', '客户', '转化'],
            'next_actions': ['采集 5 条同行爆款', '生成 3 个钩子版本', '做 1 条低成本测试视频'],
        }
    items = []
    for item in (payload.get('hot_topics') or [])[:12]:
        if isinstance(item, dict):
            items.append(TrendItem(
                title=str(item.get('title') or '行业选题'),
                reason=str(item.get('reason') or ''),
                heat=_clamp_int(item.get('heat'), 60, 0, 100),
                angle=str(item.get('angle') or ''),
                suggested_hook=str(item.get('suggested_hook') or ''),
                risk=str(item.get('risk') or ''),
            ))
    return TrendRadarResponse(
        summary=str(payload.get('summary') or '已生成行业选题雷达。'),
        hot_topics=items,
        content_angles=[str(x) for x in (payload.get('content_angles') or []) if str(x).strip()][:12],
        shooting_suggestions=[str(x) for x in (payload.get('shooting_suggestions') or []) if str(x).strip()][:12],
        monitor_keywords=[str(x) for x in (payload.get('monitor_keywords') or []) if str(x).strip()][:20],
        next_actions=[str(x) for x in (payload.get('next_actions') or []) if str(x).strip()][:12],
    )


async def generate_shooting_plan(settings: Settings, req: 'ShootingPlanRequest') -> 'ShootingPlanResponse':
    from app.schemas import ShootingPlanRequest, ShootingPlanResponse, ShotTask

    system = '你是短视频拍摄导演，负责把口播文案变成老板和员工能照着拍的拍摄任务单。必须输出严格 JSON。'
    user = f'''
请生成一份拍摄任务单。
标题：{req.title or '未填写'}
口播稿：
{req.script or '未填写'}
行业：{req.industry or '未填写'}
目标客户：{req.audience or '未填写'}
卖点：{req.selling_points or '未填写'}
现有素材：{req.available_assets or '未填写'}
目标时长：{req.duration_seconds} 秒

输出 JSON：
{{
  "summary":"拍摄策略摘要",
  "shot_tasks":[{{"scene":"镜头场景","duration":"建议时长","camera":"拍摄方式/构图","content":"拍什么/怎么演","props":"需要准备什么","priority":"必拍/可选"}}],
  "broll_list":["补充素材清单"],
  "teleprompter":["提词器短句"],
  "checklist":["拍摄前检查"]
}}
'''.strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.62, timeout=90)
    except Exception:
        payload = {
            'summary': '先拍老板正面口播，再补产品、环境、客户沟通和案例画面，保证每句口播都有对应画面。',
            'shot_tasks': [
                {'scene': '老板正面口播', 'duration': '8-12秒', 'camera': '竖屏半身，眼睛看镜头', 'content': '说开头痛点和核心判断', 'props': '干净背景/品牌墙', 'priority': '必拍'},
                {'scene': '办公室/门头环境', 'duration': '4-6秒', 'camera': '缓慢推进或横移', 'content': '展示公司真实环境', 'props': '门头/工位/会议室', 'priority': '必拍'},
                {'scene': '客户沟通/服务流程', 'duration': '6-10秒', 'camera': '侧拍，避免隐私信息', 'content': '体现服务过程和可信度', 'props': '电脑/文件/沟通场景', 'priority': '必拍'},
            ],
            'broll_list': ['产品细节', '员工操作', '证书荣誉', '客户案例截图打码', '老板走路/看文件'],
            'teleprompter': [req.script[:60] if req.script else '你有没有发现，最近客户越来越难找了？'],
            'checklist': ['竖屏 9:16', '收音清楚', '背景干净', '避免客户隐私', '每个镜头多拍 2 遍'],
        }
    tasks = []
    for item in (payload.get('shot_tasks') or [])[:20]:
        if isinstance(item, dict):
            tasks.append(ShotTask(
                scene=str(item.get('scene') or '补充镜头'),
                duration=str(item.get('duration') or '3-5秒'),
                camera=str(item.get('camera') or '竖屏稳定拍摄'),
                content=str(item.get('content') or ''),
                props=str(item.get('props') or ''),
                priority=str(item.get('priority') or '必拍'),
            ))
    return ShootingPlanResponse(
        summary=str(payload.get('summary') or '已生成拍摄任务单。'),
        shot_tasks=tasks,
        broll_list=[str(x) for x in (payload.get('broll_list') or []) if str(x).strip()][:20],
        teleprompter=[str(x) for x in (payload.get('teleprompter') or []) if str(x).strip()][:20],
        checklist=[str(x) for x in (payload.get('checklist') or []) if str(x).strip()][:20],
    )


async def generate_subtitle_emphasis(settings: Settings, req: 'SubtitleEmphasisRequest') -> 'SubtitleEmphasisResponse':
    from app.schemas import SubtitleEmphasisRequest, SubtitleEmphasisResponse, SubtitleKeyword

    system = '你是短视频字幕设计师，负责识别需要高亮的重点字，并给出字幕和封面建议。必须输出严格 JSON。'
    user = f'''
请分析下面口播稿，自动挑出需要重点高亮的词句。
字幕风格：{req.style}
品牌色：{req.brand_color}
口播稿：
{req.script}

输出 JSON：
{{
  "template":"字幕模板描述",
  "keywords":[{{"word":"重点词","reason":"为什么突出","effect":"放大/变色/描边/震动/逐字出现"}}],
  "srt_tips":["字幕制作建议"],
  "cover_text_options":["封面大字方案"]
}}
'''.strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.55, timeout=60)
    except Exception:
        words = []
        for w in ['客户', '同行', '获客', '投流', '成本', '转化', '案例', '私信']:
            if w in req.script:
                words.append({'word': w, 'reason': '转化相关关键词', 'effect': '放大高亮'})
        payload = {
            'template': '大号白字底部居中，关键词使用品牌色描边，高痛点词轻微震动。',
            'keywords': words or [{'word': '客户', 'reason': '目标结果关键词', 'effect': '放大高亮'}],
            'srt_tips': ['每行不超过 16 个字', '重点词单独成行', '前三秒字幕更大'],
            'cover_text_options': ['客户正在被同行截走', '别再等自然流量', '本地老板获客新打法'],
        }
    keywords = []
    for item in (payload.get('keywords') or [])[:18]:
        if isinstance(item, dict):
            keywords.append(SubtitleKeyword(
                word=str(item.get('word') or '').strip()[:40],
                reason=str(item.get('reason') or ''),
                effect=str(item.get('effect') or '放大高亮'),
            ))
    return SubtitleEmphasisResponse(
        template=str(payload.get('template') or '大号白字，重点词高亮。'),
        keywords=[k for k in keywords if k.word],
        srt_tips=[str(x) for x in (payload.get('srt_tips') or []) if str(x).strip()][:12],
        cover_text_options=[str(x) for x in (payload.get('cover_text_options') or []) if str(x).strip()][:12],
    )


async def generate_growth_decision(settings: Settings, req: 'GrowthDecisionRequest') -> 'GrowthDecisionResponse':
    from app.schemas import GrowthDecisionRequest, GrowthDecisionResponse

    m = req.metrics
    engagement = 0.0
    if m.views:
        engagement = (m.likes + m.comments * 3 + m.shares * 4 + m.follows * 5 + m.leads * 12) / max(1, m.views) * 100
    lead_cost = (m.spend / m.leads) if m.leads else None
    system = '你是短视频投流增长分析师，负责根据早期数据判断是否加热、停投、改封面或重剪。必须输出严格 JSON。'
    user = f'''
请判断这条视频是否值得继续投流/加热。
标题：{req.title or '未填写'}
行业：{req.industry or '未填写'}
目标：{req.objective}
口播稿：
{req.script or '未填写'}

数据：
播放 {m.views}，点赞 {m.likes}，评论 {m.comments}，分享 {m.shares}，关注 {m.follows}，线索 {m.leads}，完播率 {m.completion_rate}%，消耗 {m.spend}，发布后 {m.hours_after_publish} 小时。
互动加权率约 {engagement:.2f}%，线索成本 {lead_cost if lead_cost is not None else '暂无'}。

输出 JSON：
{{
  "score":0-100,
  "decision":"继续观察/小额加热/加投/停投重剪/换封面再测",
  "reason":"原因",
  "recommended_budget":"预算建议",
  "actions":["立即动作"],
  "alerts":["风险提醒"],
  "next_test":["下一轮测试建议"]
}}
'''.strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.48, timeout=60)
    except Exception:
        score = 35
        alerts = []
        if m.views > 0:
            score += min(20, int(m.completion_rate / 4))
            if engagement > 1.5: score += 15
            if m.leads > 0: score += 20
        if m.views < 500 and m.hours_after_publish >= 3:
            alerts.append('自然流量样本偏小，先不要大额投流。')
        if m.completion_rate < 20 and m.views > 300:
            alerts.append('完播率偏低，优先改前三秒和节奏。')
        decision = '小额加热' if score >= 65 else ('换封面再测' if score >= 45 else '停投重剪')
        payload = {
            'score': max(0, min(100, score)),
            'decision': decision,
            'reason': '根据播放、完播、互动和线索数据给出的规则判断。',
            'recommended_budget': '先 100-300 元小额测试' if score >= 45 else '暂不建议加投',
            'actions': ['检查前三秒钩子', '换 2 张封面 A/B', '保留高互动评论词做下一条选题'],
            'alerts': alerts,
            'next_test': ['同钩子换素材', '同素材换标题', '同人群小额测试 3 小时'],
        }
    return GrowthDecisionResponse(
        score=_clamp_int(payload.get('score'), 50, 0, 100),
        decision=str(payload.get('decision') or '继续观察'),
        reason=str(payload.get('reason') or '已生成投流判断。'),
        recommended_budget=str(payload.get('recommended_budget') or '先小额测试'),
        actions=[str(x) for x in (payload.get('actions') or []) if str(x).strip()][:12],
        alerts=[str(x) for x in (payload.get('alerts') or []) if str(x).strip()][:12],
        next_test=[str(x) for x in (payload.get('next_test') or []) if str(x).strip()][:12],
    )
