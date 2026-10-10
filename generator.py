"""OpenAI domain generator.

Generates domain candidates related to a user description, with reasoning.
"""
from __future__ import annotations

import json
import re
from typing import TypedDict

class DomainCandidate(TypedDict, total=False):
    domain: str  # without TLD, e.g. "mythforge"
    reason: str  # 一句话理由（兼容旧版）
    meaning: str  # 【寓意】字面意思 + 象征
    suitable_for: str  # 【适合场景】品牌定位 / 目标用户
    vibe: str  # 【调性】几个关键词，如 "简约·科技·温暖"


class GenerateParams(TypedDict, total=False):
    description: str
    min_len: int
    max_len: int
    count: int
    domain_style: str  # "letters"（纯字母）或 "letters_and_digits"（字母+数字）
    api_key: str
    base_url: str
    model: str


# 域名字符风格常量
STYLE_LETTERS = "letters"             # 纯字母（默认）
STYLE_LETTERS_AND_DIGITS = "letters_and_digits"  # 字母+数字
VALID_STYLES = (STYLE_LETTERS, STYLE_LETTERS_AND_DIGITS)


SYSTEM_PROMPT = """你是一位顶尖的域名策划大师，擅长从用户描述中提炼核心概念，创造与品牌内容高度相关、易于记忆与传播、富有故事感和文化内涵的域名。

你评估域名的五项硬性原则（按重要性排序）：

【原则 1｜词数越少越好】
- 1 个词：最佳（如 apple.com、stripe.com）
- 2 个词：优秀（如 bluehost.com、facebook.com）
- 3 个词：一般，除非必要
- 4 个词以上：基本不适合做主域名
判定方法：把候选按 1 / 2 / 3 / 4+ 词数分类，**优先 1 词，其次 2 词**。

【原则 2｜字符组成优先级】
- 纯字母 > 纯数字 > 字母+数字 > 带连字符
  - 纯字母：最好读、最好拼。
  - 纯数字：短号可以，但品牌感弱（如 360.com 是例外）。
  - 字母+数字：易混淆（0/o、1/l/I），如非必要不用。
  - 连字符 "-"：**强烈避免**，口述时容易漏掉（如 best-shoes.com）。
- 不要使用下划线、空格或任何非 [a-z0-9-] 字符。
- 本轮 user 指令中 STYLE 段决定可用的字符集：
  - STYLE=letters：仅使用 a-z 小写字母。
  - STYLE=letters_and_digits：使用 a-z 小写字母 + 0-9 数字。
    仅当词根末尾追加 1-3 位**与品牌语义呼应**的数字（如 "7" 寓意"七天"、"42" 指代"生命、宇宙与一切"）时使用；
    数字必须出现在末尾、不要嵌入词中打断读音，禁止随机凑数（如 92831）。

【原则 3｜电话测试：能读出来、能听写】
- 域名要能通过"电话测试"：你在电话里说一遍，对方能一次拼对。
- 如果要说"是 b 不是 d，是 1 不是 l"，那就不是好域名。
- 避免连续 3 个及以上辅音字母（如 "strght"、"kchrn"）。
- 避免生僻缩写、专有名词、非通用词根。

【原则 4｜品牌感 > 关键词】
- 搜索引擎更看重品牌，关键词堆砌反而掉价。
- 好：notion.so、figma.com、shopify.com —— 简洁、有故事、有产品定位。
- 差：best-cheap-online-shoes-store-2026.com —— 长、像广告、无品牌感。
- 优先选择有"产品定位感"或"概念感"的词根（mythforge、quest、neo），而非堆砌描述。

【原则 5｜含义正面、无歧义】
- 避免负面联想、容易读成脏话或奇怪词。
- 避免与知名品牌太像（商标风险）。
- 避免在不同语言里引发尴尬含义。
- 域名应蕴含背景故事，让人产生联想（避免浅显直白的拼凑）。

【输出规范】
1. 严格输出 JSON 数组，不要包含任何解释性文字、Markdown 包裹或前后缀。
2. 每个候选必须包含 5 个字段：
   - domain: 域名主体（不含 TLD）
   - reason: 一句话推荐理由（≤80 字，含词源/组合方式 + 与描述的关联 + 记忆点）
   - meaning: 【寓意】字面意思 + 象征含义（≤60 字；可提及文化背景、神话、隐喻）
   - suitable_for: 【适合场景】这个域名适合什么样的品牌/产品/目标用户（≤50 字）
   - vibe: 【调性】3-5 个关键词描述整体感觉，如 "简约·科技·温暖"、"复古·硬核·专业"
3. reason/meaning/suitable_for 用中文撰写。
4. 候选按品牌感从高到低排序（1 词 + 纯字母 + 故事性强 的排最前）。"""


def _style_directive(style: str) -> str:
    """生成 USER_PROMPT 顶部的字符风格说明段。"""
    if style == STYLE_LETTERS_AND_DIGITS:
        return (
            "- 【字符风格】STYLE=letters_and_digits：可使用 a-z + 0-9。"
            "仅在词根末尾追加 1-3 位**有语义**的数字（与品牌/产品相关联），"
            "禁止纯无意义随机数（如 92831）。数字必须出现在词根末尾，不要打断读音。\n"
        )
    return "- 【字符风格】STYLE=letters：仅使用 a-z 小写字母。\n"


USER_PROMPT_TEMPLATE = """请根据以下用户描述，生成 {count} 个与描述内容强相关、易记、好拼、好念、有故事、有内涵的域名。

【五大评估原则（按重要性）】
1. 词数越少越好：1 词 > 2 词 > 3 词 > 4+ 词
2. 字符组成：纯字母 > 纯数字 > 字母+数字；**绝不使用连字符 -**
3. 电话测试：对方听一次就能拼对；避免连续 3+ 辅音、生僻缩写
4. 品牌感 > 关键词：避免长描述堆砌
5. 含义正面、无歧义：避免负面联想、与知名品牌撞名、不同语言尴尬含义
{style_directive}
【核心要求】
- 域名主体长度：{min_len}-{max_len} 个字符（不含 TLD 后缀）
- 每个域名必须与用户描述存在明确关联（词义/主题/隐喻）
- **不要使用连字符 "-"**（哪怕只是为了分隔两个词）
- 候选按品牌感从高到低排序：1 词纯字母、有故事性的排最前

【用户描述】
{description}

【输出格式（严格遵守）】
仅输出一个 JSON 数组，不要有其他任何文字：
[
  {{
    "domain": "mythforge",
    "reason": "由 myth(神话) + forge(锻造) 组合，呼应'打造开发者神话工具'的核心诉求；纯字母、电话测试一次过，1 词组合好记。",
    "meaning": "锻造神话——既指开发者用它'锻造代码神话'，也暗喻产品本身将成为行业传奇；北欧神话中 smith 神锻造的传说也呼应'匠人精神'。",
    "suitable_for": "面向开发者的 IDE、代码生成工具、技术社区平台，目标用户是追求极客精神的专业工程师。",
    "vibe": "硬核·史诗·匠人·神秘"
  }}
]

注意：
- reason/meaning/suitable_for/vibe 全部用中文
- meaning 给出具体的词源/文化背景/隐喻，不要只写'好记、有内涵'这种空话
- vibe 用 3-5 个关键词，词与词之间用 ·（中点）或空格分隔
- reason 控制在 80 字以内，meaning 60 字内，suitable_for 50 字内"""


def build_prompt(params: GenerateParams) -> list[dict]:
    """Construct the OpenAI messages list."""
    style = params.get("domain_style") or STYLE_LETTERS
    if style not in VALID_STYLES:
        style = STYLE_LETTERS
    user_content = USER_PROMPT_TEMPLATE.format(
        count=params["count"],
        min_len=params["min_len"],
        max_len=params["max_len"],
        style_directive=_style_directive(style),
        description=params["description"],
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def parse_response(raw: str) -> list[DomainCandidate]:
    """Parse OpenAI's text response into a list of DomainCandidate.

    Robust against:
    - ```json ... ``` code fence wrapping
    - surrounding explanatory text

    Raises ValueError if no JSON array can be found or parsed.
    """
    if not raw or not raw.strip():
        raise ValueError("empty response from OpenAI")

    text = raw.strip()

    # Strip ```json ... ``` code fence if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try direct parse first
    try:
        data = json.loads(text)
        return _validate_candidates(data)
    except json.JSONDecodeError:
        pass

    # Fallback: extract first [...] block
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        raise ValueError(f"no JSON array found in response: {raw[:200]!r}")

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in response: {e}") from e

    return _validate_candidates(parsed)


def _validate_candidates(data) -> list[DomainCandidate]:
    """校验 AI 输出的 JSON 数组。

    必填：domain（字符串）、reason（字符串）
    选填：meaning / suitable_for / vibe（缺失或非字符串时填空串）
    """
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array, got {type(data).__name__}")
    result: list[DomainCandidate] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        domain = item.get("domain")
        reason = item.get("reason")
        if not (isinstance(domain, str) and domain and isinstance(reason, str)):
            continue
        cand: DomainCandidate = {
            "domain": domain,
            "reason": reason,
        }
        # 可选字段：缺失或非字符串 → 空串
        for key in ("meaning", "suitable_for", "vibe"):
            v = item.get(key)
            if isinstance(v, str) and v.strip():
                cand[key] = v.strip()  # type: ignore[literal-required]
            else:
                cand[key] = ""  # type: ignore[literal-required]
        result.append(cand)
    if not result:
        raise ValueError("no valid candidates in response")
    return result


class OpenAIGenerator:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4o-mini"):
        # Import inside __init__ so tests can use parse_response without openai installed
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def generate(self, description: str, min_len: int, max_len: int,
                 count: int, domain_style: str = STYLE_LETTERS
                 ) -> list[DomainCandidate]:
        messages = build_prompt({
            "description": description,
            "min_len": min_len,
            "max_len": max_len,
            "count": count,
            "domain_style": domain_style,
            "api_key": "",
            "base_url": "",
            "model": self.model,
        })
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.8,
        )
        content = resp.choices[0].message.content or ""
        candidates = parse_response(content)
        # 客户端二次校验：剔除不符合字符风格的产物，避免大模型偶尔越界
        return [c for c in _filter_by_style(candidates, domain_style)]


_LETTERS_RE = re.compile(r"^[a-z]+$")
_LETTERS_AND_DIGITS_RE = re.compile(r"^[a-z0-9]+$")


def _filter_by_style(candidates: list[DomainCandidate],
                     style: str) -> list[DomainCandidate]:
    """按字符风格过滤：letters 必须是纯 a-z；letters_and_digits 允许 0-9。

    同时清洗 reason 中的非 ASCII 标点（保留字母数字和基本标点）。"""
    pat = (_LETTERS_AND_DIGITS_RE if style == STYLE_LETTERS_AND_DIGITS
           else _LETTERS_RE)
    out = []
    for c in candidates:
        d = c["domain"].strip().lower()
        if not pat.match(d):
            continue
        c["domain"] = d
        out.append(c)
    return out