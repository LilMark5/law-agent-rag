from langchain_core.documents import Document

from src.retrieval.fusion import doc_key, fallback_keyword_search, fuse_results


def _law(article: str, law: str = "中华人民共和国刑法", content: str = "") -> Document:
    return Document(
        page_content=content or f"{law} {article}：内容",
        metadata={"source_type": "law", "law_name": law, "article_number": article},
    )


def test_fuse_results_deduplicates():
    doc1 = _law("第二百三十二条")
    vector_results = [doc1]
    graph_results = [
        {
            "type": "Law",
            "properties": {
                "article_number": "第二百三十二条",
                "law_name": "中华人民共和国刑法",
                "content": "故意杀人的...",
            },
        }
    ]

    fused = fuse_results(vector_results, graph_results, top_k=5)
    keys = [doc_key(doc) for doc in fused]
    assert keys.count(doc_key(doc1)) == 1


def test_fuse_results_respects_top_k():
    docs = [_law(f"第{i}条", law="测试法") for i in range(10)]
    graph_results = [
        {
            "type": "Law",
            "properties": {"article_number": f"第{i}条", "law_name": "测试法", "content": f"内容{i}"},
        }
        for i in range(10)
    ]
    fused = fuse_results(docs[:5], graph_results[:5], top_k=3)
    assert len(fused) == 3


def test_rrf_rewards_dual_recall():
    """同一文档被两路同时召回时，应排在只被单路召回的前面"""
    shared = _law("第八十二条", law="中华人民共和国劳动合同法")
    vector_only = _law("第十条", law="中华人民共和国劳动合同法")
    graph_only = {
        "type": "Law",
        "properties": {
            "article_number": "第八十二条",
            "law_name": "中华人民共和国劳动合同法",
            "content": "用人单位自用工之日起超过一个月不满一年未与劳动者订立书面劳动合同的...",
        },
    }

    fused = fuse_results(
        [vector_only, shared], [graph_only], top_k=5, strategy="rrf"
    )
    assert fused[0].metadata["article_number"] == "第八十二条"


def test_weighted_strategy_still_supported():
    docs = [_law("第十条", law="劳动合同法")]
    fused = fuse_results(docs, [], top_k=5, strategy="weighted")
    assert len(fused) == 1


def test_fallback_search_hits_expected_article():
    """离线兜底检索：无需任何 Key 也能命中内置语料"""
    docs = fallback_keyword_search("未签书面劳动合同要付双倍工资吗", top_k=3)
    assert docs
    assert any("第八十二条" in doc.page_content for doc in docs)


def _case_node(case_id: str) -> dict:
    return {
        "type": "Case",
        "properties": {
            "case_id": case_id,
            "crime": "故意伤害",
            "fact": "被告人持刀伤人",
            "judgment": "有期徒刑2年",
        },
    }


def test_reserve_case_slots_keeps_cases_in_top_k():
    """法条两路加分必然排在案例前面，不额外附加的话案例永远进不了上下文"""
    from src.retrieval.fusion import reserve_case_slots

    laws = [_law(f"第{i}条") for i in range(1, 9)]
    cases = [_case_node("CAIL-000001"), _case_node("CAIL-000002")]

    result = reserve_case_slots(laws, cases, top_k=8, case_slots=2)

    # 法条名额不动，案例额外附加——占位会直接拉低法条召回
    assert len(result) == 10
    assert [d.metadata["source_type"] for d in result[:8]] == ["law"] * 8
    assert [d.metadata["source_type"] for d in result[-2:]] == ["case", "case"]


def test_reserve_case_slots_ignores_duplicate_cases():
    from src.retrieval.fusion import reserve_case_slots

    cases = [_case_node("CAIL-000001")]
    fused = [
        *[_law(f"第{i}条") for i in range(1, 4)],
        Document(
            page_content="案例CAIL-000001：已在上下文里",
            metadata={"source_type": "case", "case_id": "CAIL-000001"},
        ),
    ]

    result = reserve_case_slots(fused, cases, top_k=8, case_slots=2)

    assert len(result) == 4
    assert sum(1 for d in result if d.metadata["source_type"] == "case") == 1


def test_reserve_case_slots_counts_existing_cases_toward_quota():
    """fused 里已经排进来的案例要占名额，不能重复补"""
    from src.retrieval.fusion import reserve_case_slots

    fused = [
        _law("第二百三十四条"),
        Document(
            page_content="案例CAIL-000009：已经排进前八",
            metadata={"source_type": "case", "case_id": "CAIL-000009"},
        ),
    ]

    result = reserve_case_slots(fused, [_case_node("CAIL-000001")], top_k=8, case_slots=2)

    assert len(result) == 3
    assert result[-1].metadata["case_id"] == "CAIL-000001"


def test_reserve_case_slots_noop_without_cases():
    from src.retrieval.fusion import reserve_case_slots

    laws = [_law(f"第{i}条") for i in range(1, 4)]
    assert reserve_case_slots(laws, [], top_k=8, case_slots=2) == laws
