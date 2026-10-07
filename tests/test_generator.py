from generator import build_prompt, parse_response


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