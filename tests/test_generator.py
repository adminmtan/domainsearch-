from generator import (
    STYLE_LETTERS,
    STYLE_LETTERS_AND_DIGITS,
    VALID_STYLES,
    _filter_by_style,
    build_prompt,
    parse_response,
)


def test_build_prompt_contains_constraints():
    messages = build_prompt({
        "description": "面向开发者的 AI 工具",
        "min_len": 4, "max_len": 10, "count": 5,
        "api_key": "x", "base_url": "y", "model": "z",
    })
    text = " ".join(m["content"] for m in messages)
    assert "面向开发者的 AI 工具" in text
    assert "4" in text and "10" in text
    assert "强相关" in text  # 强相关性是核心要求


def test_parse_response_plain_json():
    raw = '[{"domain":"mythforge","reason":"myth+forge 呼应神话工具"}]'
    result = parse_response(raw)
    assert len(result) == 1
    assert result[0]["domain"] == "mythforge"


def test_parse_response_wrapped_in_code_block():
    raw = '```json\n[{"domain":"a","reason":"b"}]\n```'
    result = parse_response(raw)
    assert result[0]["domain"] == "a"


def test_parse_response_with_surrounding_text():
    raw = '下面是结果：\n[{"domain":"a","reason":"b"}]\n请查收'
    result = parse_response(raw)
    assert result[0]["domain"] == "a"


def test_parse_response_invalid_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_response("not json at all")


def test_build_prompt_default_style_is_letters():
    messages = build_prompt({
        "description": "AI 工具",
        "min_len": 4, "max_len": 10, "count": 5,
        "api_key": "x", "base_url": "y", "model": "z",
    })
    user_text = next(m["content"] for m in messages if m["role"] == "user")
    # user 段默认应该用 letters，且不应出现 digits 描述
    assert "STYLE=letters" in user_text
    assert "STYLE=letters_and_digits" not in user_text


def test_build_prompt_with_letters_and_digits_style():
    messages = build_prompt({
        "description": "AI 工具",
        "min_len": 4, "max_len": 10, "count": 5,
        "domain_style": STYLE_LETTERS_AND_DIGITS,
        "api_key": "x", "base_url": "y", "model": "z",
    })
    user_text = next(m["content"] for m in messages if m["role"] == "user")
    # user 段应当包含 digits 指令
    assert "STYLE=letters_and_digits" in user_text
    # system 段原则 2 提到 digits 模式语义
    sys_text = next(m["content"] for m in messages if m["role"] == "system")
    assert "品牌语义呼应" in sys_text
    assert "纯字母" in sys_text


def test_build_prompt_invalid_style_falls_back_to_letters():
    messages = build_prompt({
        "description": "AI 工具",
        "min_len": 4, "max_len": 10, "count": 5,
        "domain_style": "garbage",
        "api_key": "x", "base_url": "y", "model": "z",
    })
    user_text = next(m["content"] for m in messages if m["role"] == "user")
    assert "STYLE=letters" in user_text


def test_filter_by_style_letters_drops_digits():
    cands = [
        {"domain": "mythforge", "reason": "r"},
        {"domain": "quest7", "reason": "r"},
        {"domain": "neo42", "reason": "r"},
    ]
    out = _filter_by_style(cands, STYLE_LETTERS)
    assert [c["domain"] for c in out] == ["mythforge"]


def test_filter_by_style_letters_and_digits_keeps_both():
    cands = [
        {"domain": "mythforge", "reason": "r"},
        {"domain": "quest7", "reason": "r"},
        {"domain": "neo42", "reason": "r"},
        {"domain": "bad-name!", "reason": "r"},  # 非法字符
    ]
    out = _filter_by_style(cands, STYLE_LETTERS_AND_DIGITS)
    assert [c["domain"] for c in out] == ["mythforge", "quest7", "neo42"]


def test_valid_styles_constant():
    assert set(VALID_STYLES) == {STYLE_LETTERS, STYLE_LETTERS_AND_DIGITS}