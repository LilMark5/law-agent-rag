"""LangGraph 多 Agent 编排

图结构（真的带循环，不是线性 if/else）：

    START → identify ─→ retrieve ─→ {civil|criminal|labor|admin|general} ─→ review
                                                                              │
                                        ┌─────────────────────────────────────┤
                                        │ passed / 超出重试 → END              │
                                        └─ 未通过 → 回到对应领域节点重生成 ────┘

三个角色：
- 协调者（identify）：判断领域与意图
- 领域专家（5 个节点，共享 DomainAgent 实现，prompt 由 YAML 区分）
- 审查者（review）：检查引用一致性，不通过则带着问题清单回炉

为什么要用图而不是三个函数调用：
    "生成 → 审查 → 不通过 → 带反馈重生成"是一个有环的控制流，
    用图表达可以显式限制重试次数（recursion_limit + attempts），
    并且能把节点执行过程直接映射成前端的流式步骤。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.domain_agent import DomainAgent, build_sources
from src.agents.reviewer import review_answer
from src.config import load_config
from src.retrieval.fusion import hybrid_search

logger = logging.getLogger(__name__)

DOMAINS = ["civil_law", "criminal_law", "labor_law", "admin_law", "general"]


class AgentState(TypedDict, total=False):
    """图状态：节点只增量返回自己产出的字段"""

    question: str
    history: list[dict]
    domain: str
    domain_zh: str
    intent: str
    keywords: list[str]
    context_docs: list
    answer: str
    sources: list[str]
    review: dict
    feedback: str | None
    attempts: int


# --------------------------------------------------------------------------
# 节点
# --------------------------------------------------------------------------
def identify_node(state: AgentState) -> dict:
    from src.agents.coordinator import identify_domain

    question = state["question"]
    history = state.get("history") or []
    if history:
        context = "\n".join(
            f"问：{item.get('question', '')}\n答：{item.get('answer', '')}"
            for item in history[-3:]
        )
        question = f"对话历史：\n{context}\n\n当前问题：{question}"

    result = identify_domain(question)
    return {
        "domain": result.get("domain", "general"),
        "domain_zh": result.get("domain_zh", "通用"),
        "intent": result.get("intent", ""),
        "keywords": result.get("keywords", []),
    }


def retrieve_node(state: AgentState) -> dict:
    """检索只执行一次，结果在整个图内复用"""
    docs = hybrid_search(state["question"])
    return {"context_docs": docs, "sources": build_sources(docs)}


def make_domain_node(domain: str):
    def domain_node(state: AgentState) -> dict:
        agent = DomainAgent(domain)
        result = agent.answer(
            question=state["question"],
            intent=state.get("intent", ""),
            keywords=state.get("keywords", []),
            context_docs=state.get("context_docs"),
            review_feedback=state.get("feedback"),
            history=state.get("history"),
        )
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "attempts": state.get("attempts", 0) + 1,
        }

    return domain_node


def review_node(state: AgentState) -> dict:
    config = load_config()
    review_cfg = config.get("review", {})

    if not review_cfg.get("enabled", True):
        return {"review": {"passed": True, "issues": [], "score": 1.0, "mode": "disabled"}}

    result = review_answer(
        state.get("answer", ""),
        state.get("sources", []),
        state.get("context_docs", []),
    )
    feedback = None if result["passed"] else "；".join(result["issues"])
    if feedback:
        logger.info("审查未通过（第 %s 版）：%s", state.get("attempts", 1), feedback)
    return {"review": result, "feedback": feedback}


# --------------------------------------------------------------------------
# 路由
# --------------------------------------------------------------------------
def route_by_domain(state: AgentState) -> str:
    domain = state.get("domain") or "general"
    return domain if domain in DOMAINS else "general"


def route_after_review(state: AgentState) -> str:
    review = state.get("review") or {}
    if review.get("passed", True):
        return END

    config = load_config()
    max_retry = int(config.get("review", {}).get("max_retry", 1))
    if state.get("attempts", 0) > max_retry:
        logger.warning("已达最大重试次数 %s，返回当前回答", max_retry)
        return END

    return route_by_domain(state)


# --------------------------------------------------------------------------
# 图构建
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def build_agent_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("identify", identify_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("review", review_node)
    for domain in DOMAINS:
        workflow.add_node(domain, make_domain_node(domain))

    workflow.add_edge(START, "identify")
    workflow.add_edge("identify", "retrieve")
    workflow.add_conditional_edges(
        "retrieve", route_by_domain, {domain: domain for domain in DOMAINS}
    )
    for domain in DOMAINS:
        workflow.add_edge(domain, "review")
    workflow.add_conditional_edges(
        "review",
        route_after_review,
        {**{domain: domain for domain in DOMAINS}, END: END},
    )

    return workflow.compile()


def initial_state(question: str, history: list[dict] | None = None) -> AgentState:
    return {
        "question": question,
        "history": history or [],
        "domain": "",
        "domain_zh": "",
        "intent": "",
        "keywords": [],
        "context_docs": [],
        "answer": "",
        "sources": [],
        "review": {},
        "feedback": None,
        "attempts": 0,
    }


GRAPH_STREAM_CONFIG = {"recursion_limit": 25}


def run_agent(question: str, history: list[dict] | None = None) -> dict:
    """同步执行整张图（Streamlit / 脚本使用）"""
    return build_agent_graph().invoke(
        initial_state(question, history), config=GRAPH_STREAM_CONFIG
    )


async def astream_agent(question: str, history: list[dict] | None = None):
    """流式执行：逐节点产出 (节点名, 状态增量)

    编排层据此把节点执行映射成 SSE 事件，前端无需感知 LangGraph。
    """
    graph = build_agent_graph()
    async for chunk in graph.astream(
        initial_state(question, history),
        config=GRAPH_STREAM_CONFIG,
        stream_mode="updates",
    ):
        for node, update in chunk.items():
            yield node, update or {}
