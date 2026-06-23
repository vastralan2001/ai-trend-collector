from src.core.llm import LLMClient


def test_parse_json_plain() -> None:
    raw = '{"chinese_summary": "test", "product_impact": "impact"}'
    parsed = LLMClient._parse_json(raw)
    assert parsed == {"chinese_summary": "test", "product_impact": "impact"}


def test_parse_json_markdown() -> None:
    raw = '```json\n{"chinese_summary": "test", "product_impact": "impact"}\n```'
    parsed = LLMClient._parse_json(raw)
    assert parsed == {"chinese_summary": "test", "product_impact": "impact"}


def test_parse_json_invalid() -> None:
    raw = "not json"
    parsed = LLMClient._parse_json(raw)
    assert parsed is None
