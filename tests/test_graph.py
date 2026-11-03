"""图结构测试：不调用任何模型，只验证编排拓扑正确"""

from src.agents.graph import DOMAINS, build_agent_graph


def _edges(graph) -> set[tuple[str, str]]:
    drawable = graph.get_graph()
    edges = set()
    for edge in drawable.edges:
        source = getattr(edge, "source", None)
        target = getattr(edge, "target", None)
        if source and target:
            edges.add((source, target))
    return edges


def test_graph_compiles_with_all_domain_nodes():
    graph = build_agent_graph()
    nodes = set(graph.get_graph().nodes)

    assert {"identify", "retrieve", "review"} <= nodes
    for domain in DOMAINS:
        assert domain in nodes


def test_retrieve_fans_out_to_every_domain():
    edges = _edges(build_agent_graph())
    for domain in DOMAINS:
        assert ("retrieve", domain) in edges


def test_every_domain_flows_into_review():
    edges = _edges(build_agent_graph())
    for domain in DOMAINS:
        assert (domain, "review") in edges


def test_review_can_loop_back_to_domains():
    """审查未通过时必须有回边，否则反思回路不成立"""
    edges = _edges(build_agent_graph())
    for domain in DOMAINS:
        assert ("review", domain) in edges


def test_graph_is_cached():
    """图编译有成本，必须复用同一实例"""
    assert build_agent_graph() is build_agent_graph()
