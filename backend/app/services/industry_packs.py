"""Industry packs for AI Video Growth Studio MVP."""

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class IndustryPack:
    industry_name: str
    pain_points: List[str] = field(default_factory=list)
    hook_templates: List[str] = field(default_factory=list)
    copy_templates: List[str] = field(default_factory=list)
    cta_templates: List[str] = field(default_factory=list)
    asset_keywords: List[str] = field(default_factory=list)
    lead_keywords: List[str] = field(default_factory=list)
    reply_templates: Dict[str, str] = field(default_factory=dict)
    forbidden_words: List[str] = field(default_factory=list)


REAL_ESTATE = IndustryPack(
    industry_name="real_estate",
    pain_points=[
        "区域选错，几百万打水漂",
        "马来西亚买房不能贷款？其实是方法不对",
        "第二家园 vs 工作签证，哪个更适合你",
        "海外置业最怕买到烂尾楼",
        "学区房怎么选才不踩坑",
    ],
    hook_templates=[
        "来马来西亚买房，{pain_point}",
        "90%的人在马来西亚买房都忽略了{key_point}",
        "别再被中介忽悠了，{truth}",
        "花3分钟看完，{benefit}",
    ],
    copy_templates=[
        "如果你正在考虑{keyword}，先别急着做决定。\n今天告诉你3个避坑标准。",
        "很多人一上来只看价格，真正影响结果的{key_point}反而没搞清楚。",
        "{pain_point}，但你知道吗，{solution}",
    ],
    cta_templates=[
        "想知道你的预算能买哪里？私信我，帮你做一份免费的置业分析。",
        "拿不定主意？把你的情况发我，我来帮你判断。",
        "想看具体区域对比？回复{keyword}我发你资料。",
    ],
    asset_keywords=[
        "马来西亚房产", "海外置业", "第二家园", "养老", "国际学校",
        "租金回报", "永久产权", "KLCC", "TRX", "首付", "贷款",
        "区域选择", "学区房", "别墅", "公寓", "投资回报",
    ],
    lead_keywords=[
        "多少钱", "价格", "能贷款吗", "首付多少", "月供",
        "有资料吗", "发来看看", "怎么联系", "私信", "微信",
    ],
    reply_templates={
        "price": "可以的，我发你区域和价格表，你更关注自住还是投资？",
        "loan": "外国人也可以贷款，具体看你的收入和房产类型。方便说下你的预算吗？",
        "catalog": "有的，发你最新房源资料。你倾向KLCC还是TRX周边？",
        "contact": "好的，你可以加我微信或者WhatsApp，我详细跟你说。",
        "general": "感谢关注！想了解更多关于{keyword}的信息吗？私信我详聊。",
    },
    forbidden_words=[
        "保证升值", "百分百回报", "稳赚不赔", "包租", "必涨",
        "零风险", "绝对", "最便宜", "史上最低",
    ],
)


FOREIGN_TRADE = IndustryPack(
    industry_name="foreign_trade",
    pain_points=[
        "发了100封开发信，只有1个回复",
        "工厂报价太高，客户直接不回",
        "样品寄了就没下文",
        "客户嫌MOQ太高",
        "物流太慢丢客户",
    ],
    hook_templates=[
        "Looking for reliable {product} supplier? {pain_point}",
        "Stop wasting time on unqualified leads. {solution}",
        "Why your factory quotes get ignored: {truth}",
    ],
    copy_templates=[
        "We are a professional {product} manufacturer with {years} years of experience.\nMOQ flexible, free sample available.",
        "Tired of high MOQ? We offer small batch orders with competitive pricing.\nDM for catalog and quote.",
    ],
    cta_templates=[
        "Send me a DM for free catalog and sample. MOQ flexible.",
        "WhatsApp me for quick quote: we reply within 2 hours.",
        "Want to see our factory video? Comment 'factory' below.",
    ],
    asset_keywords=[
        "factory", "supplier", "wholesale", "MOQ", "sample", "catalog",
        "shipping", "custom logo", "quote", "delivery time", "OEM", "ODM",
        "manufacturer", "export", "FOB", "CIF", "production",
    ],
    lead_keywords=[
        "price", "MOQ", "catalog", "sample", "quote", "cost",
        "shipping", "delivery", "order", "buy", "wholesale",
        "factory", "OEM", "custom", "logo",
    ],
    reply_templates={
        "price": "Sure! Can you tell me the quantity you need? I'll send the best quote.",
        "catalog": "Of course, sending our latest catalog now. Any specific product you're interested in?",
        "sample": "Yes, we offer free samples. What's your shipping address?",
        "moq": "Our MOQ is flexible. Small trial orders are welcome. What quantity are you thinking?",
        "quote": "Happy to quote! Please share your target quantity and any custom requirements.",
        "general": "Thanks for reaching out! We specialize in {keyword}. How can I help you today?",
    },
    forbidden_words=[
        "cheapest", "guaranteed lowest price", "no quality issues",
        "100% perfect", "zero defect", "we are the best",
    ],
)


INDUSTRY_PACKS: Dict[str, IndustryPack] = {
    "real_estate": REAL_ESTATE,
    "foreign_trade": FOREIGN_TRADE,
}


def get_pack(industry: str) -> IndustryPack:
    pack = INDUSTRY_PACKS.get(industry)
    if pack is None:
        raise ValueError(f"Unknown industry: {industry}. Available: {list(INDUSTRY_PACKS.keys())}")
    return pack


def list_packs() -> List[Dict[str, Any]]:
    return [
        {
            "industry": p.industry_name,
            "pain_points_count": len(p.pain_points),
            "hook_templates_count": len(p.hook_templates),
            "cta_templates_count": len(p.cta_templates),
            "asset_keywords_count": len(p.asset_keywords),
        }
        for p in INDUSTRY_PACKS.values()
    ]
