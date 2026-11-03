import pytest

from src.retrieval.graph_search import (
    build_graph_query,
    extract_article_numbers,
    extract_entities,
    int_to_cn,
)


def test_build_graph_query_is_parameterized():
    """实体值必须走 $param，不能拼进 Cypher 字符串"""
    entities = {
        "article_numbers": ["第二百三十二条"],
        "crimes": ["故意杀人"],
        "legal_terms": ["中华人民共和国刑法"],
    }
    cypher, params = build_graph_query(entities, hop=2)

    assert cypher
    assert "MATCH" in cypher
    assert "第二百三十二条" not in cypher
    assert "中华人民共和国刑法" not in cypher
    assert params["articles"] == ["第二百三十二条"]
    assert params["law_names"] == ["中华人民共和国刑法"]


def test_build_graph_query_rejects_injection_payload():
    """恶意输入只会成为参数值，不会改变查询结构"""
    payload = 'x"}) DETACH DELETE (n) //'
    entities = {"article_numbers": ["第一条"], "legal_terms": [payload]}
    cypher, params = build_graph_query(entities, hop=1)

    assert "DETACH DELETE" not in cypher
    assert payload in params["law_names"]


def test_build_graph_query_without_entities_returns_empty():
    cypher, params = build_graph_query(
        {"article_numbers": [], "crimes": [], "legal_terms": []}
    )
    assert cypher == ""
    assert params == {}


def test_build_graph_query_crimes_alone_does_not_query_laws():
    """只有罪名、没有条号时不查法条

    用 ``l.content CONTAINS 术语`` 召回过：那是把 BM25 重做一遍且没有排序，
    进入融合后反而挤掉向量检索的正确答案（MRR 0.741 → 0.644）。
    """
    cypher, params = build_graph_query(
        {"article_numbers": [], "crimes": ["盗窃"], "legal_terms": []}
    )
    assert cypher == ""
    assert params == {}


@pytest.mark.parametrize(
    "number,expected",
    [
        (1, "一"),
        (10, "十"),
        (11, "十一"),
        (20, "二十"),
        (105, "一百零五"),
        (232, "二百三十二"),
        (1001, "一千零一"),
        (1260, "一千二百六十"),
    ],
)
def test_int_to_cn(number, expected):
    assert int_to_cn(number) == expected


def test_extract_article_numbers_normalizes_arabic():
    """用户写"第232条"，语料里是"第二百三十二条"，必须归一化才能命中"""
    assert extract_article_numbers("刑法第232条怎么规定的？") == ["第二百三十二条"]
    assert extract_article_numbers("劳动合同法第82条") == ["第八十二条"]


def test_extract_article_numbers_supports_sub_articles():
    """刑法有 53 个"之一"条文，正则不能把它截断成基础条"""
    assert extract_article_numbers("刑法第一百三十三条之一") == ["第一百三十三条之一"]


def test_extract_entities_finds_article_numbers():
    entities = extract_entities("刑法第232条怎么规定的？")
    assert "第二百三十二条" in entities["article_numbers"]


def test_extract_entities_finds_crimes():
    entities = extract_entities("盗窃罪和诈骗罪有什么区别？")
    assert "盗窃" in entities["crimes"]


def test_extract_entities_does_not_call_llm_by_default():
    """默认配置下实体抽取是纯规则计算，不应产生网络调用"""
    entities = extract_entities("公司不给我签劳动合同怎么办")
    assert entities == {"article_numbers": [], "crimes": [], "legal_terms": []}


def test_extract_entities_recognizes_law_name():
    entities = extract_entities("劳动合同法是怎么规定的")
    assert any("劳动合同法" in term for term in entities["legal_terms"])


class _FakeSession:
    """记录执行过的 Cypher，不真的连库"""

    def __init__(self, queries: list) -> None:
        self.queries = queries

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def run(self, cypher: str, params: dict):
        self.queries.append((cypher, params))
        return []


class _FakeDriver:
    def __init__(self) -> None:
        self.queries: list = []
        self.connected = 0

    def session(self):
        self.connected += 1
        return _FakeSession(self.queries)

    def close(self) -> None:
        pass


def test_graph_search_runs_case_query_when_only_crime(monkeypatch):
    """只提到罪名、没有条号时必须走案例检索

    回归测试：此前该分支引用了未定义的 ``terms``，NameError 被外层 except
    吞成"Neo4j 查询失败"，案例通道静默失效。
    """
    from src.data import kg_builder
    from src.retrieval import graph_search as graph_search_module

    fake = _FakeDriver()
    monkeypatch.setattr(kg_builder, "get_neo4j_driver", lambda: fake)

    result = graph_search_module.graph_search("故意伤害罪的量刑标准是什么？", top_k=5)

    assert result == []
    assert fake.connected == 1
    assert any("MATCH (c:Case)" in cypher for cypher, _ in fake.queries)
    assert fake.queries[0][1]["terms"] == ["故意伤害"]


def test_graph_search_skips_neo4j_without_entities(monkeypatch):
    """没有任何实体时不该白连一次数据库"""
    from src.data import kg_builder
    from src.retrieval import graph_search as graph_search_module

    fake = _FakeDriver()
    monkeypatch.setattr(kg_builder, "get_neo4j_driver", lambda: fake)

    assert graph_search_module.graph_search("公司不给我签劳动合同怎么办", top_k=5) == []
    assert fake.connected == 0


def test_graph_search_queries_cases_by_article_after_expand(monkeypatch):
    """有条号时：先二跳，再按条号捞类案——顺序错了二跳会被案例挤掉"""

    class _LawSession(_FakeSession):
        def run(self, cypher: str, params: dict):
            self.queries.append((cypher, params))
            if "MATCH (l:Law)" in cypher and "RETURN l\n" in cypher:
                return [_law_record(234)]
            if cypher.strip().startswith("MATCH (c:Case)-[:APPLIES]"):
                return [_case_record("CAIL-000001", "故意伤害")]
            return []

    class _LawDriver(_FakeDriver):
        def session(self):
            self.connected += 1
            return _LawSession(self.queries)

    from src.data import kg_builder
    from src.retrieval import graph_search as graph_search_module

    fake = _LawDriver()
    monkeypatch.setattr(kg_builder, "get_neo4j_driver", lambda: fake)

    results = graph_search_module.graph_search("刑法第二百三十四条如何量刑", top_k=5)

    cyphers = [cypher for cypher, _ in fake.queries]
    assert any("RETURN l2" in c for c in cyphers), "二跳查询应被触发"
    assert any(c.strip().startswith("MATCH (c:Case)-[:APPLIES]") for c in cyphers)
    # 二跳必须排在案例查询之前
    expand_idx = next(i for i, c in enumerate(cyphers) if "RETURN l2" in c)
    case_idx = next(
        i for i, c in enumerate(cyphers) if c.strip().startswith("MATCH (c:Case)-[:APPLIES]")
    )
    assert expand_idx < case_idx
    assert [node["type"] for node in results] == ["Law", "Case"]


def _law_record(article: int) -> dict:
    """构造一条 Neo4j 记录，键为 RETURN 的字段名"""
    law = _FakeNode("Law", {"law_name": "中华人民共和国刑法", "article_number": f"第{article}条"})
    return {"l": law}


def _case_record(case_id: str, crime: str) -> dict:
    case = _FakeNode("Case", {"case_id": case_id, "crime": crime})
    return {"c": case}


class _FakeNode:
    """模拟 neo4j Node：有 labels 且可转 dict"""

    def __init__(self, label: str, props: dict) -> None:
        self.labels = frozenset({label})
        self._props = props

    def __iter__(self):
        return iter(self._props)

    def __getitem__(self, key):
        return self._props[key]

    def keys(self):
        return self._props.keys()
