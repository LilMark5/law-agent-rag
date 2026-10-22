from langchain_core.documents import Document

from src.agents.domain_agent import DomainAgent, build_context_blocks


def test_domain_agent_loads_criminal_law_config():
    agent = DomainAgent("criminal_law")
    assert agent.domain == "criminal_law"
    assert "刑法" in agent.system_prompt


def test_domain_agent_falls_back_to_general():
    agent = DomainAgent("nonexistent_domain")
    assert agent.domain == "nonexistent_domain"
    assert "法律咨询" in agent.system_prompt


def _law_doc(article: str) -> Document:
    return Document(
        page_content=f"中华人民共和国刑法 {article}：故意伤害他人身体的……",
        metadata={"source_type": "law", "law_name": "中华人民共和国刑法", "article_number": article},
    )


def _case_doc(case_id: str, fact: str = "被告人持刀伤人", judgment: str = "有期徒刑2年") -> Document:
    return Document(
        page_content=f"案例{case_id}：{fact} 判决：{judgment}",
        metadata={
            "source_type": "case",
            "case_id": case_id,
            "crime": "故意伤害",
            "fact": fact,
            "judgment": judgment,
        },
    )


def test_context_blocks_separate_laws_and_cases():
    """法条与案例必须分区，混在一段里模型会把个案刑期说成普遍标准"""
    text = build_context_blocks([_law_doc("第二百三十四条"), _case_doc("CAIL-000001")])

    assert "【法律条文】" in text
    assert "【类案参考】" in text
    assert text.index("【法律条文】") < text.index("【类案参考】")
    # 编号连续，回答里的 [n] 引用才不会指错
    assert "[1]" in text and "[2]" in text


def test_context_blocks_truncates_long_fact():
    long_fact = "事实" * 500
    text = build_context_blocks([_case_doc("CAIL-000002", fact=long_fact)], fact_chars=50)

    assert "…" in text
    assert long_fact not in text


def test_context_blocks_limits_case_count():
    docs = [_case_doc(f"CAIL-{i:06d}") for i in range(5)]
    text = build_context_blocks(docs, case_limit=2)

    assert text.count("案例 CAIL-") == 2


def test_context_blocks_handles_empty_context():
    assert "未检索到相关资料" in build_context_blocks([])