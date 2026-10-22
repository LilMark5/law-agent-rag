from src.agents.coordinator import DOMAIN_MAP, identify_domain
from src.agents.graph import DOMAINS, route_after_review, route_by_domain


def test_domain_map_covers_all_internal_domains():
    mapped_values = set(DOMAIN_MAP.values())
    for domain in ["civil_law", "criminal_law", "labor_law", "admin_law"]:
        assert domain in mapped_values


def test_all_routed_domains_are_registered():
    """路由可能返回的领域必须都在图节点里注册过，否则图会抛 KeyError"""
    for domain in DOMAIN_MAP.values():
        assert domain in DOMAINS


def test_route_by_domain_falls_back_to_general():
    assert route_by_domain({"domain": "unknown_law"}) == "general"
    assert route_by_domain({}) == "general"
    assert route_by_domain({"domain": "labor_law"}) == "labor_law"


def test_route_after_review_ends_when_passed():
    from langgraph.graph import END

    state = {"review": {"passed": True}, "domain": "labor_law", "attempts": 1}
    assert route_after_review(state) == END


def test_route_after_review_retries_then_gives_up():
    from langgraph.graph import END

    failing = {"passed": False, "issues": ["缺少引用"]}

    # 第一次未通过 → 回到领域节点重生成
    assert route_after_review({"review": failing, "domain": "labor_law", "attempts": 1}) == "labor_law"

    # 超过 max_retry（默认 1）→ 结束，避免无限循环
    assert route_after_review({"review": failing, "domain": "labor_law", "attempts": 2}) == END


def test_identify_domain_degrades_without_api_key(monkeypatch):
    """意图识别不应把整条链路带崩：LLM 抛错时回落到关键词匹配"""
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("src.agents.coordinator.OpenAI", boom)
    result = identify_domain("未签劳动合同怎么维权")

    assert result["domain"] == "labor_law"
    assert result["intent"]
