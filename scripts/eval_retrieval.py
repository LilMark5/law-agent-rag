"""检索质量评测脚本

用法：
    # 离线（无需任何 API Key / Neo4j，走字符匹配兜底）
    python scripts/eval_retrieval.py --mode offline

    # 向量单路（需要 DASHSCOPE_API_KEY）
    python scripts/eval_retrieval.py --mode vector --build-index

    # 双路混合（向量 + 图谱，Neo4j 可选）
    python scripts/eval_retrieval.py --mode hybrid

指标：
    Recall@k  期望**法名+条号**是否出现在前 k 条结果中
    MRR       第一个命中结果的名次倒数
    Coverage  期望条文是否存在于当前语料（低 Coverage 说明缺数据，不是算法问题）

为什么要按「法名+条号」配对：
    24 部法规里有大量重复条号（第八十二条、第三十条……），
    只比对条号会让任意一部法的同名条款都算命中，指标虚高且不可信。

为什么先做检索评测而不是端到端评测：
    生成质量受 prompt 与模型波动影响大，检索指标更稳定，也更能定位问题。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.documents import Document  # noqa: E402


def load_gold(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def corpus_articles() -> set[tuple[str, str]]:
    """当前语料覆盖的 (法名, 条号) 集合，用于 Coverage 指标"""
    from src.data.collector import load_laws

    return {(law["law_name"], law["article_number"]) for law in load_laws()}


def retrieve(question: str, mode: str, top_k: int, enable_graph: bool = True) -> list[Document]:
    if mode == "offline":
        from src.retrieval.fusion import fallback_keyword_search

        return fallback_keyword_search(question, top_k=top_k)

    if mode == "bm25":
        from src.retrieval.bm25 import bm25_search

        return bm25_search(question, top_k=top_k)

    if mode == "hybrid":
        from src.retrieval.fusion import hybrid_search

        return hybrid_search(question, top_k=top_k, enable_graph=enable_graph)

    if mode == "vector":
        from src.config import load_config
        from src.retrieval.fusion import _resolve_index_path
        from src.retrieval.vector_search import get_engine

        cfg = load_config().get("retrieval", {})
        # 用缓存引擎：既避免"每次查询重建客户端"，也避免在评测里误触发建索引
        engine = get_engine(_resolve_index_path(cfg.get("index_path", "data/embeddings")))
        return engine.query(question, top_k=top_k)

    if mode == "graph":
        from src.retrieval.fusion import graph_node_to_document
        from src.retrieval.graph_search import graph_search

        nodes = graph_search(question, top_k=top_k)
        return [doc for node in nodes if (doc := graph_node_to_document(node))]

    raise ValueError(f"未知模式：{mode}")


def hit(doc: Document, item: dict) -> bool:
    """判断一条检索结果是否命中期望条文（法名 + 条号都要对上）

    法律问答存在等价引用：同一个行为可能被多部法规同时规范
    （例如拖欠工资，劳动合同法、劳动法、调解仲裁法都有对应条款）。
    因此 gold 支持 ``also_accept`` 声明可接受的替代条文。
    """
    meta = doc.metadata or {}
    law_name = str(meta.get("law_name") or "")
    if not law_name:
        # 兜底：Document 正文以法名开头
        law_name = doc.page_content
    article = str(meta.get("article_number") or "").replace(" ", "")

    for target in [item, *(item.get("also_accept") or [])]:
        if target["law"] not in law_name:
            continue
        if article:
            if article == target["article"]:
                return True
        elif target["article"] in doc.page_content:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量评测")
    parser.add_argument(
        "--mode",
        default="offline",
        choices=["offline", "bm25", "vector", "graph", "hybrid"],
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--gold", default=str(PROJECT_ROOT / "data" / "eval" / "gold.json"))
    parser.add_argument("--build-index", action="store_true", help="先用当前语料重建向量索引")
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="hybrid 模式下关闭图检索：把检索算法本身的贡献与 LLM 实体抽取延迟分开看",
    )
    parser.add_argument("--verbose", action="store_true", help="打印每条用例的命中条文")
    args = parser.parse_args()

    from src.data.collector import corpus_stats

    stats = corpus_stats()
    if args.build_index:
        from src.retrieval.fusion import build_vector_index

        count = build_vector_index()
        print(f"索引重建完成：{count} 条文档")

    gold = load_gold(Path(args.gold))
    covered = corpus_articles()

    recalls: list[float] = []
    rrs: list[float] = []
    coverages: list[float] = []
    latencies: list[int] = []
    by_domain: dict[str, list[float]] = defaultdict(list)
    misses: list[str] = []

    print(
        f"语料：{stats['source']}｜{stats['laws']} 部法规｜{stats['articles']} 条条文"
        f"｜{stats['chars']:,} 字"
    )
    print(f"mode={args.mode}  top_k={args.top_k}  gold={len(gold)} 条\n")
    header = f"{'id':<9}{'命中':<6}{'位次':<6}{'语料覆盖':<10}{'耗时(ms)':<10}question"
    print(header)
    print("-" * 100)

    for item in gold:
        started = time.perf_counter()
        docs = retrieve(
            item["question"], args.mode, args.top_k, enable_graph=not args.no_graph
        )
        latency = int((time.perf_counter() - started) * 1000)
        latencies.append(latency)

        first_rank = None
        for rank, doc in enumerate(docs, start=1):
            if hit(doc, item):
                first_rank = rank
                break

        recall = 1.0 if first_rank else 0.0
        recalls.append(recall)
        rrs.append(1.0 / first_rank if first_rank else 0.0)
        by_domain[item.get("domain", "general")].append(recall)

        targets = [(item["law"], item["article"])] + [
            (alt["law"], alt["article"]) for alt in item.get("also_accept") or []
        ]
        covered_now = any(t in covered for t in targets)
        coverages.append(1.0 if covered_now else 0.0)
        if not first_rank:
            misses.append(item["id"])

        print(
            f"{item['id']:<9}{'OK' if first_rank else '--':<6}"
            f"{(first_rank or '-'):<6}{'是' if covered_now else '否(缺数据)':<10}"
            f"{latency:<10}{item['question']}"
        )
        if args.verbose and docs:
            top = docs[0].metadata or {}
            print(
                f"          top1 = {top.get('law_name', '?')} "
                f"{top.get('article_number', '?')} "
                f"[{top.get('retrieved_by', 'vector')}]"
            )

    total = len(gold)
    print("-" * 100)
    print(f"Recall@{args.top_k}   : {sum(recalls) / total:.3f}  ({sum(recalls):.0f}/{total})")
    print(f"MRR             : {sum(rrs) / total:.3f}")
    print(f"Corpus coverage : {sum(coverages) / total:.3f}")
    print(f"平均检索耗时     : {sum(latencies) / total:.0f} ms")

    print("\n分领域 Recall：")
    for domain, values in sorted(by_domain.items()):
        print(f"  {domain:<12} {sum(values) / len(values):.3f}  ({len(values)} 条)")

    if misses:
        print(f"\n未命中用例：{', '.join(misses)}")
    uncovered = [item["id"] for item, cov in zip(gold, coverages) if not cov]
    if uncovered:
        print(f"期望条文不在语料中的用例：{', '.join(uncovered)}")
        print("这些不是检索算法的问题，而是数据缺口 —— 先补语料，再调参。")


if __name__ == "__main__":
    main()
