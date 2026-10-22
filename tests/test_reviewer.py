from src.agents import reviewer
from src.agents.reviewer import review_answer, rule_review


def test_review_answer_passes_with_citations():
    answer = "根据刑法第二百三十二条，故意杀人的，处死刑、无期徒刑或者十年以上有期徒刑。以上分析仅供参考，不构成法律意见。"
    sources = ["中华人民共和国刑法 第二百三十二条"]
    context_docs = []
    result = review_answer(answer, sources, context_docs)
    assert result["passed"] is True


def test_review_answer_fails_without_citations():
    answer = "故意杀人罪会被判处很重的刑罚。"
    sources = []
    context_docs = []
    result = review_answer(answer, sources, context_docs)
    assert result["passed"] is False
    assert "引用" in result["reason"] or "法条" in result["reason"]


def test_existing_but_unretrieved_article_is_not_treated_as_hallucination(monkeypatch):
    """条号在语料中存在、只是没被召回 —— 不应判为幻觉

    《劳动合同法》第三十八条是常见引用，但经常不在 top-8 检索结果里。
    原实现会因此判不通过并触发一次无意义的重生成。
    """
    monkeypatch.setattr(
        reviewer, "_corpus_article_numbers", lambda: frozenset({"第三十八条"})
    )
    answer = (
        "根据《劳动合同法》第三十八条，用人单位未及时足额支付劳动报酬的，"
        "劳动者可以解除劳动合同。以上仅供参考，不构成法律意见。"
    )

    result = rule_review(answer, ["中华人民共和国劳动合同法 第十六条"])

    assert result["passed"] is True
    assert result["unretrieved"] == ["第三十八条"]


def test_fabricated_article_fails(monkeypatch):
    """条号在语料里根本不存在 —— 判为疑似编造"""
    monkeypatch.setattr(
        reviewer, "_corpus_article_numbers", lambda: frozenset({"第三十八条"})
    )
    answer = "根据《劳动合同法》第九百九十九条，用人单位应当赔偿。以上仅供参考。"

    result = rule_review(answer, ["中华人民共和国劳动合同法 第十六条"])

    assert result["passed"] is False
    assert any("不存在" in issue for issue in result["issues"])


def test_corpus_numbers_available():
    """真实语料应能提供条号集合，否则存在性校验会静默失效"""
    numbers = reviewer._corpus_article_numbers()
    assert isinstance(numbers, frozenset)
    assert len(numbers) > 100


def test_arabic_citations_are_not_reported_as_hallucination():
    """模型写「第10条」而语料是「第十条」时，不能判成编造

    实测踩过：审查把一条完全正确的劳动合同法回答打回重写，
    仅因为条号写成阿拉伯数字，每问白多花 8 秒。
    """
    answer = (
        "根据《劳动合同法》第10条，建立劳动关系应当订立书面劳动合同。"
        "以上分析仅供参考，不构成法律意见。"
    )
    result = rule_review(answer, [])

    assert result["passed"] is True, result["issues"]


def test_normalize_article_converts_arabic():
    assert reviewer.normalize_article("第10条") == "第十条"
    assert reviewer.normalize_article("第82条") == "第八十二条"
    assert reviewer.normalize_article("第一百三十三条之一") == "第一百三十三条之一"
