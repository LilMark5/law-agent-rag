"""审查 Agent：对生成回答做质量校验

两级审查：

- ``rule``（默认，零成本）：正则检查法条引用、引用一致性、免责声明。
- ``llm``：让模型充当审查官，判断是否存在无来源支撑的断言（幻觉），
  输出结构化问题清单，供编排层触发二次生成。

审查结果统一为 ``{"passed", "issues", "score", "mode"}``，
``issues`` 会作为反馈拼进下一次生成的 prompt，形成反思回路。
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from openai import OpenAI

from src.config import load_config


@lru_cache(maxsize=1)
def _corpus_article_numbers() -> frozenset[str]:
    """全量语料中的条号集合，用于区分"编造条号"与"真实但未召回"

    语料缺失（只有示例数据）时返回空集合，调用方会退化为保守判定。
    """
    try:
        from src.data.collector import load_laws

        return frozenset(item["article_number"] for item in load_laws())
    except Exception as exc:  # 语料读取失败不应让审查整体不可用
        logger.warning("读取语料条号失败，跳过存在性校验：%s", exc)
        return frozenset()

logger = logging.getLogger(__name__)

CITATION_PATTERN = re.compile(r"第[一二三四五六七八九十百零\d]+条")
LAW_NAME_PATTERN = re.compile(r"《.+?》")
DISCLAIMER_HINTS = ("仅供参考", "不构成法律意见")


def normalize_article(article: str) -> str:
    """把「第10条」统一成「第十条」

    模型经常写阿拉伯数字，而语料里存的是中文数字。不归一化的话，
    「第10条」会被判成"语料中不存在，疑似编造"——这是**假阳性**，
    会让审查回路把一条完全正确的回答打回重写（实测每问多花 8 秒）。
    """
    match = re.fullmatch(r"第(\d+)条", article)
    if not match:
        return article

    from src.retrieval.graph_search import int_to_cn

    return f"第{int_to_cn(int(match.group(1)))}条"


def check_has_citation(answer: str) -> bool:
    """回答是否包含法条引用"""
    return bool(CITATION_PATTERN.search(answer) or LAW_NAME_PATTERN.search(answer))


def check_citation_accuracy(answer: str, sources: list[str]) -> dict:
    """区分两类引用问题

    - ``unknown``：全量语料里根本不存在该条号 → 真幻觉，判不通过
    - ``unretrieved``：语料里存在、只是没进本次检索结果 → 不做否定依据

    原实现把两者混为一谈，导致「引用正确但未被召回」也被判幻觉：
    《劳动合同法》第三十八条这类关键条款经常不在 top-8 里，于是每个问题都要
    多跑一次生成，延迟翻倍。
    """
    cited = CITATION_PATTERN.findall(answer)
    if not cited:
        return {"accurate": True, "unknown": [], "unretrieved": []}

    source_text = " ".join(sources)
    corpus = _corpus_article_numbers()

    unknown: list[str] = []
    unretrieved: list[str] = []
    for raw in dict.fromkeys(cited):
        article = normalize_article(raw)
        if article in source_text or raw in source_text:
            continue
        # 语料为空（未抓取）时无法判定存在性，维持保守策略
        if corpus and article in corpus:
            unretrieved.append(raw)
        else:
            unknown.append(raw)

    return {"accurate": not unknown, "unknown": unknown, "unretrieved": unretrieved}


def rule_review(answer: str, sources: list[str]) -> dict:
    """规则审查，返回结构化结果"""
    issues: list[str] = []

    if not check_has_citation(answer):
        issues.append("回答未包含任何法条引用")
        if not sources:
            issues.append("无检索来源支持，回答可能脱离知识库")

    citation_check = check_citation_accuracy(answer, sources)
    if not citation_check["accurate"]:
        unmatched = "、".join(citation_check["unknown"])
        issues.append(f"以下条号在语料中不存在，疑似编造：{unmatched}")

    if not any(hint in answer for hint in DISCLAIMER_HINTS):
        issues.append("缺少免责声明")

    return {
        "passed": not issues,
        "issues": issues,
        "score": max(0.0, 1.0 - 0.3 * len(issues)),
        "mode": "rule",
        # 供可观测性使用：存在但未被召回的引用，不算问题
        "unretrieved": citation_check["unretrieved"],
    }


LLM_REVIEW_PROMPT = """你是一名严格的法律回答审查员。请审查下面这份回答：

【检索到的参考资料】
{context}

【回答】
{answer}

请检查三点：
1. 回答中的事实与法条引用是否都能在参考资料中找到依据；
2. 是否存在参考资料未支持却以确定语气给出的断言（幻觉）；
3. 是否存在遗漏免责声明、越界给出胜诉承诺等问题。

只返回 JSON，格式：
{{
  "passed": true 或 false,
  "score": 0 到 1 之间的小数,
  "issues": ["具体问题，每条一句话；没有问题则为空数组"]
}}"""


def llm_review(answer: str, sources: list[str], context_docs: list | None = None) -> dict:
    """LLM 审查：判断有无无依据断言"""
    config = load_config()
    client = OpenAI(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"]["base_url"],
    )

    if context_docs:
        context = "\n\n".join(f"[{i + 1}] {doc.page_content}" for i, doc in enumerate(context_docs))
    else:
        context = "\n".join(sources) or "（无检索结果）"

    prompt = LLM_REVIEW_PROMPT.format(context=context, answer=answer)

    try:
        response = client.chat.completions.create(
            model=config["llm"]["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        data = json.loads(content)
        issues = data.get("issues") or []
        return {
            "passed": bool(data.get("passed", not issues)),
            "issues": issues,
            "score": float(data.get("score", 1.0 if not issues else 0.5)),
            "mode": "llm",
        }
    except Exception as exc:
        logger.warning("LLM 审查失败，回退规则审查：%s", exc)
        return rule_review(answer, sources)


def review_answer(
    answer: str,
    sources: list[str],
    context_docs: list | None = None,
    use_llm: bool | None = None,
) -> dict:
    """审查入口：按配置选择规则审查或 LLM 审查

    Returns:
        {"passed": bool, "issues": list[str], "score": float, "mode": str,
         "reason": str}  # reason 为 issues 拼接，兼容旧调用方
    """
    config = load_config()
    review_cfg = config.get("review", {})
    if use_llm is None:
        use_llm = bool(review_cfg.get("use_llm", False))

    result = (
        llm_review(answer, sources, context_docs)
        if use_llm
        else rule_review(answer, sources)
    )
    result["reason"] = "；".join(result["issues"]) if result["issues"] else "审查通过"
    return result
