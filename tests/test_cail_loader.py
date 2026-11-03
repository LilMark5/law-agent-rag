import json

import pytest

from src.data.cail_loader import (
    convert_record,
    load_cases,
    normalize_articles,
    render_applicable_law,
    render_judgment,
    to_article_int,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (264, 264),
        ("264", 264),
        ("第264条", 264),
        (0, None),
        ("", None),
        ("第二百六十四条", None),
        (True, None),
        (None, None),
    ],
)
def test_to_article_int(value, expected):
    """两个 split 一个存 int 一个存 str，必须都能归一化"""
    assert to_article_int(value) == expected


def test_normalize_articles_dedupes_and_keeps_order():
    assert normalize_articles([264, "264", 232, None, 0]) == [264, 232]


@pytest.mark.parametrize(
    "term,expected",
    [
        ({"death_penalty": True, "life_imprisonment": False, "imprisonment": 12}, "死刑"),
        ({"death_penalty": False, "life_imprisonment": True, "imprisonment": 0}, "无期徒刑"),
        ({"death_penalty": False, "life_imprisonment": False, "imprisonment": 6}, "有期徒刑6个月"),
        ({"death_penalty": False, "life_imprisonment": False, "imprisonment": 12}, "有期徒刑1年"),
        ({"death_penalty": False, "life_imprisonment": False, "imprisonment": 38}, "有期徒刑3年2个月"),
        # 三者皆否：可能是免予处罚/管制/拘役，CAIL 没区分，留空不猜
        ({"death_penalty": False, "life_imprisonment": False, "imprisonment": 0}, ""),
        (None, ""),
    ],
)
def test_render_judgment(term, expected):
    assert render_judgment(term) == expected


def test_render_applicable_law_uses_chinese_numbers():
    assert render_applicable_law([264, 232]) == "刑法第二百六十四条、刑法第二百三十二条"


def test_convert_record_maps_all_fields():
    record = {
        "fact": "被告人张某某秘密窃取他人财物，价值2210元。",
        "meta": {
            "relevant_articles": [264, "312"],
            "accusation": ["盗窃", "掩饰、隐瞒犯罪所得"],
            "term_of_imprisonment": {"imprisonment": 8, "death_penalty": False, "life_imprisonment": False},
        },
    }
    case = convert_record(record, 1)

    assert case["case_id"] == "CAIL-000001"
    assert case["case_type"] == "刑事"
    assert case["crime"] == "盗窃、掩饰、隐瞒犯罪所得"
    assert case["judgment"] == "有期徒刑8个月"
    assert case["applicable_law"] == "刑法第二百六十四条、刑法第三百一十二条"
    assert case["article_numbers"] == [264, 312]


def test_convert_record_skips_record_without_articles():
    """没有条号就建不出 APPLIES 边，导进去只是孤立节点"""
    record = {"fact": "某事实", "meta": {"relevant_articles": [], "accusation": ["盗窃"]}}
    assert convert_record(record, 1) is None


def test_convert_record_skips_record_without_fact():
    record = {"fact": "  ", "meta": {"relevant_articles": [264], "accusation": ["盗窃"]}}
    assert convert_record(record, 1) is None


def test_load_cases_reads_jsonl(tmp_path):
    path = tmp_path / "sample.jsonl"
    rows = [
        {"fact": "事实一", "meta": {"relevant_articles": [264], "accusation": ["盗窃"]}},
        {"fact": "", "meta": {"relevant_articles": [232], "accusation": ["故意伤害"]}},
        {"fact": "事实三", "meta": {"relevant_articles": ["234"], "accusation": ["故意伤害"]}},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    cases = load_cases(path)

    assert len(cases) == 2
    assert [c["case_id"] for c in cases] == ["CAIL-000001", "CAIL-000002"]
    assert cases[1]["article_numbers"] == [234]


def test_load_cases_reads_json_array(tmp_path):
    """first_stage 的成员是标准 JSON 数组，不能只认 JSONL"""
    path = tmp_path / "sample.json"
    path.write_text(
        json.dumps([{"fact": "事实", "meta": {"relevant_articles": [232], "accusation": ["故意伤害"]}}], ensure_ascii=False),
        encoding="utf-8",
    )

    assert len(load_cases(path)) == 1


def test_load_cases_respects_limit(tmp_path):
    path = tmp_path / "sample.jsonl"
    rows = [
        {"fact": f"事实{i}", "meta": {"relevant_articles": [264], "accusation": ["盗窃"]}}
        for i in range(10)
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    assert len(load_cases(path, limit=3)) == 3
