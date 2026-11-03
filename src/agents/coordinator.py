"""协调 Agent：领域识别 + 对外入口

图编排已迁移到 ``src/agents/graph.py``。本模块只负责：
1. 用一次 LLM 调用做领域/意图识别；
2. 提供 ``ask_agent()`` 这个同步入口（Streamlit、脚本使用）。
"""

from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

from src.agents.graph import DOMAINS, build_agent_graph, initial_state
from src.config import load_config

logger = logging.getLogger(__name__)

DOMAIN_MAP = {
    "民法": "civil_law",
    "民事": "civil_law",
    "合同": "civil_law",
    "婚姻": "civil_law",
    "继承": "civil_law",
    "侵权": "civil_law",
    "刑法": "criminal_law",
    "刑事": "criminal_law",
    "犯罪": "criminal_law",
    "量刑": "criminal_law",
    "盗窃": "criminal_law",
    "杀人": "criminal_law",
    "劳动": "labor_law",
    "劳动合同": "labor_law",
    "工资": "labor_law",
    "社保": "labor_law",
    "工伤": "labor_law",
    "行政": "admin_law",
    "行政处罚": "admin_law",
    "行政诉讼": "admin_law",
}

# 内部标识 → 展示名，用于关键词兜底时回填中文领域
DOMAIN_ZH = {
    "civil_law": "民法",
    "criminal_law": "刑法",
    "labor_law": "劳动法",
    "admin_law": "行政法",
    "general": "通用",
}

INTENT_PROMPT = """分析以下法律问题，返回 JSON 格式：
{{
  "domain": "民事/刑事/劳动/行政/通用 中的一个",
  "intent": "法条查询/案例分析/法律建议/概念解释 中的一个",
  "keywords": ["提取的关键词列表"]
}}

问题：{question}

只返回 JSON，不要其他内容。"""


def _map_domain(domain_zh: str) -> str:
    """中文领域 → 内部标识

    按命中关键词的总长度打分，而非按字典顺序取第一个命中：
    "未签劳动合同" 同时命中"劳动"和"合同"，前者更长/更多，应判为劳动法。
    """
    scores: dict[str, int] = {}
    for zh_key, en_val in DOMAIN_MAP.items():
        if zh_key in domain_zh:
            scores[en_val] = scores.get(en_val, 0) + len(zh_key)

    if not scores:
        return "general"
    return max(scores, key=lambda domain: scores[domain])


def identify_domain(question: str) -> dict:
    """识别问题所属领域与意图；LLM 异常时降级为关键词匹配

    Returns:
        {"domain", "domain_zh", "intent", "keywords"}
    """
    config = load_config()

    if not config["llm"].get("api_key"):
        # 没有 Key 时直接走关键词，避免白等一次网络超时
        logger.warning("未配置 LLM API Key，领域识别降级为关键词匹配")
        domain = _map_domain(question)
        return {
            "domain": domain,
            "domain_zh": DOMAIN_ZH.get(domain, "通用"),
            "intent": "法律建议",
            "keywords": [],
        }

    try:
        client = OpenAI(
            api_key=config["llm"]["api_key"],
            base_url=config["llm"]["base_url"],
        )
        response = client.chat.completions.create(
            model=config["llm"]["model"],
            messages=[{"role": "user", "content": INTENT_PROMPT.format(question=question)}],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        result = json.loads(content)

        domain_zh = result.get("domain", "通用")
        return {
            "domain": _map_domain(domain_zh),
            "domain_zh": domain_zh,
            "intent": result.get("intent", "法律建议"),
            "keywords": result.get("keywords", []),
        }
    except Exception as exc:
        # 意图识别是链路的入口，失败时用关键词兜底，别让整个请求挂掉
        logger.warning("意图识别失败，降级为关键词匹配：%s", exc)
        domain = _map_domain(question)
        return {
            "domain": domain,
            "domain_zh": DOMAIN_ZH.get(domain, "通用"),
            "intent": "法律建议",
            "keywords": [],
        }


def ask_agent(question: str, history: list[dict] | None = None) -> dict:
    """多 Agent 问答入口（同步）

    Args:
        question: 用户问题
        history: 对话历史，每项含 question / answer

    Returns:
        {"answer", "sources", "domain", "domain_zh", "review"}
    """
    result = build_agent_graph().invoke(
        initial_state(question, history),
        config={"recursion_limit": 25},
    )
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "domain": result.get("domain", "general"),
        "domain_zh": result.get("domain_zh", "通用"),
        "review": result.get("review", {}),
    }


__all__ = ["DOMAINS", "DOMAIN_MAP", "ask_agent", "identify_domain"]
