import pytest
from unittest.mock import MagicMock, patch

from src.data.kg_builder import (
    build_cypher_for_case_node,
    build_cypher_for_law_node,
    build_cypher_for_relation,
    parse_applicable_law,
)


def test_build_cypher_for_law_node():
    law = {
        "law_name": "中华人民共和国刑法",
        "chapter": "第二编 分则",
        "article_number": "第二百三十二条",
        "content": "故意杀人的，处死刑...",
    }
    cypher, params = build_cypher_for_law_node(law)
    assert "CREATE" in cypher or "MERGE" in cypher
    assert params["law_name"] == "中华人民共和国刑法"
    assert params["article_number"] == "第二百三十二条"


def test_build_cypher_for_case_node():
    case = {
        "case_id": "CASE001",
        "case_type": "刑事",
        "crime": "故意杀人",
        "fact": "被告人李某持刀杀人",
        "judgment": "判处无期徒刑",
        "applicable_law": "刑法第二百三十二条",
    }
    cypher, params = build_cypher_for_case_node(case)
    assert "CREATE" in cypher or "MERGE" in cypher
    assert params["case_id"] == "CASE001"


def test_build_cypher_for_relation():
    cypher, params = build_cypher_for_relation(
        from_label="Case", from_id_field="case_id", from_id_value="CASE001",
        to_label="Law", to_id_field="article_number", to_id_value="第二百三十二条",
        relation_type="APPLIES",
    )
    assert "APPLIES" in cypher


def test_parse_applicable_law_single():
    assert parse_applicable_law("刑法第二百三十二条") == [("刑法", "第二百三十二条")]


def test_parse_applicable_law_multiple_articles():
    """多法条案例曾因 pattern.search 只取第一个而丢边"""
    assert parse_applicable_law("刑法第二百六十四条、刑法第三百一十二条") == [
        ("刑法", "第二百六十四条"),
        ("刑法", "第三百一十二条"),
    ]


def test_parse_applicable_law_inherits_law_hint():
    """第二段没写全法名时要继承，否则会拿去全库匹配出名同实异的条款"""
    assert parse_applicable_law("劳动合同法第八十二条、第八十五条") == [
        ("劳动合同法", "第八十二条"),
        ("劳动合同法", "第八十五条"),
    ]


def test_parse_applicable_law_keeps_sub_articles():
    assert parse_applicable_law("刑法第一百三十三条之一") == [("刑法", "第一百三十三条之一")]


def test_parse_applicable_law_ignores_garbage():
    assert parse_applicable_law("") == []
    assert parse_applicable_law("无适用法条") == []