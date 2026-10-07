"""OpenAI domain generator.

Generates domain candidates related to a user description, with reasoning.
"""
from __future__ import annotations

import json
import re
from typing import TypedDict


class DomainCandidate(TypedDict):
    domain: str  # without TLD, e.g. "mythforge"
    reason: str


class GenerateParams(TypedDict):
    description: str
    min_len: int
    max_len: int
    count: int
    api_key: str
    base_url: str
    model: str


SYSTEM_PROMPT = """你是一位顶尖的域名策划大师，擅长从用户描述中提炼核心概念，创造与品牌内容高度相关、富有故事感和文化内涵的域名。

你的工作原则：
1. 【强相关性是首位要求】每个域名必须与用户描述存在明确的关联（词义关联、主题关联、隐喻关联三者之一）。
2. 每个域名都应蕴含背景故事，让人产生联想。
3. 每个域名都应有文化或语义深度，避免浅显直白的拼凑。
4. 避免无意义的字母组合（如 xqzk、abcmn）。
5. 严格输出 JSON 数组，不要包含任何解释性文字、Markdown 包裹或前后缀。
6. 推荐理由必须包含三要素：域名构造拆解（词源、组合方式）、与用户描述的关联点、寓意解读。"""


USER_PROMPT_TEMPLATE = """请根据以下用户描述，生成 {count} 个与描述内容强相关、有故事、有内涵的域名。

【核心要求】
- 每个域名必须与用户描述存在明确关联（词义/主题/隐喻）
- 域名主体长度：{min_len}-{max_len} 个字符（不含 TLD 后缀）
- 避免无意义字母组合

【用户描述】
{description}

【输出格式（严格遵守）】
仅输出一个 JSON 数组，不要有其他任何文字：
[
  {{"domain": "mythforge", "reason": "由 myth(神话) + forge(锻造) 组合而成，呼应描述中'打造开发者神话工具'的核心诉求；forge 暗示工匠精神，myth 暗示产品的传奇色彩，整体表达'锻造开发者神话'的品牌愿景。"}}
]"""


def build_prompt(params: GenerateParams) -> list[dict]:
    """Construct the OpenAI messages list."""
    user_content = USER_PROMPT_TEMPLATE.format(
        count=params["count"],
        min_len=params["min_len"],
        max_len=params["max_len"],
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
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array, got {type(data).__name__}")
    result: list[DomainCandidate] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        domain = item.get("domain")
        reason = item.get("reason")
        if isinstance(domain, str) and domain and isinstance(reason, str):
            result.append({"domain": domain, "reason": reason})
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
                 count: int) -> list[DomainCandidate]:
        messages = build_prompt({
            "description": description,
            "min_len": min_len,
            "max_len": max_len,
            "count": count,
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
        return parse_response(content)