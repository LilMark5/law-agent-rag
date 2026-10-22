"""结果融合模块：向量 + 图双路检索结果合并

两种融合策略：

- ``rrf``（默认）：Reciprocal Rank Fusion，``score = Σ 1/(k + rank)``。
  只依赖名次，不依赖各路原始分数的量纲，避免"向量余弦距离"和"图检索命中"
  不可比的问题（原实现 ``weight * 1/(rank+1)`` 让图路结果永远排不到第一）。
- ``weighted``：先按名次做线性归一化再做加权，保留原配置语义，便于做对比实验。
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.documents import Document

from src.config import get_project_root, load_config

logger = logging.getLogger(__name__)

DEFAULT_RRF_K = 60


# --------------------------------------------------------------------------
# 结构转换
# --------------------------------------------------------------------------
def graph_node_to_document(node: dict) -> Document | None:
    """把 Neo4j 节点字典转成与向量检索同构的 Document"""
    properties = node.get("properties") or {}
    node_type = node.get("type", "")

    if node_type == "Law":
        content = (
            f"{properties.get('law_name', '')} "
            f"{properties.get('article_number', '')}：{properties.get('content', '')}"
        )
        metadata = {
            "source_type": "law",
            "law_name": properties.get("law_name", ""),
            "article_number": properties.get("article_number", ""),
            "retrieved_by": "graph",
        }
    elif node_type == "Case":
        content = (
            f"案例{properties.get('case_id', '')}：{properties.get('fact', '')} "
            f"判决：{properties.get('judgment', '')}"
        )
        metadata = {
            "source_type": "case",
            "case_id": properties.get("case_id", ""),
            "crime": properties.get("crime", ""),
            # 结构化字段单独带出来：prompt 组装时要按长度截断事实，
            # 从拼好的正文里反解既脆弱又容易把「判决：」截掉
            "fact": properties.get("fact", ""),
            "judgment": properties.get("judgment", ""),
            "retrieved_by": "graph",
        }
    else:
        return None

    return Document(page_content=content, metadata=metadata)


def doc_key(doc: Document) -> tuple:
    """去重键：法条按（法名 + 条号），案例按 case_id，其余按正文前缀"""
    meta = doc.metadata or {}
    if meta.get("source_type") == "law":
        return ("law", meta.get("law_name", ""), meta.get("article_number", ""))
    if meta.get("source_type") == "case":
        return ("case", meta.get("case_id", ""))
    return ("text", doc.page_content[:120])


def _merge_metadata(primary: Document, other: Document) -> None:
    """合并元数据；正文取更长的一份（图检索的正文更完整）"""
    merged = dict(other.metadata or {})
    merged.update(primary.metadata or {})
    primary.metadata = merged
    if len(other.page_content) > len(primary.page_content):
        primary.page_content = other.page_content


# --------------------------------------------------------------------------
# 融合策略
# --------------------------------------------------------------------------
def fuse_many(
    channels: dict[str, list[Document]],
    top_k: int,
    rrf_k: int,
    weights: dict[str, float] | None = None,
) -> list[Document]:
    """多路加权 RRF 融合

    RRF 只使用名次、不使用原始分数，因此 BM25 的分数（无上界）、
    余弦相似度（0~1）、图检索的跳数打分（人为设定）可以直接合并，
    不需要做量纲归一化。

    为什么要带权重：等权 RRF 有一个反直觉的坑——当某一路明显更弱时，
    它带来的"噪声提名"会和强通道的有效提名等值累加，融合后**低于**单路最优。
    实测本项目（33 条 gold）：向量 0.848 / BM25 0.727 / 等权融合 0.818。
    给弱通道降权后融合才真正有增益。

    Args:
        channels: {通道名: 已按相关性降序排好的文档}
        top_k: 返回条数
        rrf_k: RRF 平滑常数，越大越削弱头部优势
        weights: {通道名: 权重}，缺省按 1.0 处理

    Returns:
        去重并按融合分降序排列的文档
    """
    scores: dict[tuple, float] = {}
    best: dict[tuple, Document] = {}
    weights = weights or {}

    for name, docs in channels.items():
        weight = float(weights.get(name, 1.0))
        if weight <= 0:
            continue
        for rank, doc in enumerate(docs or [], start=1):
            key = doc_key(doc)
            scores[key] = scores.get(key, 0.0) + weight / (rrf_k + rank)
            if key in best:
                _merge_metadata(best[key], doc)
            else:
                best[key] = doc

    ordered = sorted(best.values(), key=lambda d: scores[doc_key(d)], reverse=True)
    return ordered[:top_k]


def _rrf_fuse(
    vector_results: list[Document],
    graph_results: list[dict],
    top_k: int,
    rrf_k: int,
    bm25_results: list[Document] | None = None,
    weights: dict[str, float] | None = None,
) -> list[Document]:
    channels: dict[str, list[Document]] = {}
    if vector_results:
        channels["vector"] = list(vector_results)
    if bm25_results:
        channels["bm25"] = list(bm25_results)

    graph_docs = [
        doc
        for node in (graph_results or [])
        if (doc := graph_node_to_document(node)) is not None
    ]
    if graph_docs:
        channels["graph"] = graph_docs

    return fuse_many(channels, top_k=top_k, rrf_k=rrf_k, weights=weights)


def _normalized_rank_scores(size: int) -> list[float]:
    """名次归一化：第一名 1.0，最后一名 0.0"""
    if size <= 1:
        return [1.0] * size
    return [1.0 - i / (size - 1) for i in range(size)]


def _weighted_fuse(
    vector_results: list[Document],
    graph_results: list[dict],
    top_k: int,
    weights: dict,
    bm25_results: list[Document] | None = None,
) -> list[Document]:
    vector_weight = float(weights.get("vector", 0.6))
    graph_weight = float(weights.get("graph", 0.4))
    bm25_weight = float(weights.get("bm25", 0.4))

    graph_docs = [
        doc
        for node in (graph_results or [])
        if (doc := graph_node_to_document(node)) is not None
    ]

    scores: dict[tuple, float] = {}
    best: dict[tuple, Document] = {}

    for docs, weight in (
        (vector_results, vector_weight),
        (graph_docs, graph_weight),
        (bm25_results or [], bm25_weight),
    ):
        if not docs:
            continue
        for doc, rank_score in zip(docs, _normalized_rank_scores(len(docs))):
            key = doc_key(doc)
            scores[key] = scores.get(key, 0.0) + weight * rank_score
            if key in best:
                _merge_metadata(best[key], doc)
            else:
                best[key] = doc

    ordered = sorted(best.values(), key=lambda d: scores[doc_key(d)], reverse=True)
    return ordered[:top_k]


def reserve_case_slots(
    docs: list[Document],
    graph_results: list[dict] | None,
    top_k: int,
    case_slots: int,
) -> list[Document]:
    """在融合结果后面额外附上类案

    为什么不能靠排序自然带出：法条同时被向量和 BM25 命中，两路 RRF 分数相加；
    案例只出现在图通道且权重较低（0.5），排序上永远打不过法条，
    融合后必然被挤出 top-K——类案检索就等于没做。

    为什么是"额外附加"而不是"占名额"：占位会挤掉排名靠后的法条，
    直接拉低法条召回（评测集按法条计 Recall@K）。类案是新增的一路信息，
    不该拿法条的位置去换。
    """
    if not docs or not graph_results or case_slots <= 0:
        return docs

    head = docs[:top_k]
    seen = {doc_key(doc) for doc in docs}
    already = sum(1 for doc in head if (doc.metadata or {}).get("source_type") == "case")
    room = max(0, case_slots - already)

    cases: list[Document] = []
    for node in graph_results:
        if len(cases) >= room:
            break
        if node.get("type") != "Case":
            continue
        doc = graph_node_to_document(node)
        if doc is None or doc_key(doc) in seen:
            continue
        seen.add(doc_key(doc))
        cases.append(doc)

    return head + cases


def fuse_results(
    vector_results: list[Document],
    graph_results: list[dict],
    top_k: int = 8,
    strategy: str | None = None,
    rrf_k: int | None = None,
    bm25_results: list[Document] | None = None,
) -> list[Document]:
    """融合多路检索结果并去重排序

    Args:
        vector_results: 向量检索返回的 Document 列表
        graph_results: 图检索返回的节点字典列表
        top_k: 最终返回数量
        strategy: "rrf" | "weighted"，默认读配置
        rrf_k: RRF 平滑常数，默认读配置
        bm25_results: 词汇检索结果（可选，作为第三路）

    Returns:
        去重、排序后的 Document 列表
    """
    config = load_config()
    retrieval_cfg = config.get("retrieval", {})
    strategy = strategy or retrieval_cfg.get("fusion_strategy", "rrf")
    rrf_k = rrf_k or int(retrieval_cfg.get("rrf_k", DEFAULT_RRF_K))

    if strategy == "weighted":
        weights = retrieval_cfg.get("fusion_weights", {"vector": 0.6, "graph": 0.4})
        return _weighted_fuse(vector_results, graph_results, top_k, weights, bm25_results)

    # 加权 RRF：权重来自配置，弱通道降权才能让融合优于单路
    weights = retrieval_cfg.get("fusion_weights") or {}
    return _rrf_fuse(
        vector_results, graph_results, top_k, rrf_k, bm25_results, weights=weights
    )


# --------------------------------------------------------------------------
# 离线兜底：无 Embedding Key / 无 Neo4j 时仍能演示
# --------------------------------------------------------------------------
def _bigrams(text: str) -> set[str]:
    text = "".join(ch for ch in text if not ch.isspace())
    return {text[i : i + 2] for i in range(len(text) - 1)}


def fallback_keyword_search(question: str, top_k: int = 8) -> list[Document]:
    """字符二元组重叠度的离线检索（仅用于双路都不可用时的降级演示）"""
    from src.data.collector import load_cases, load_laws
    from src.retrieval.vector_search import build_documents

    docs = build_documents(load_laws(), source_type="law") + build_documents(
        load_cases(), source_type="case"
    )

    query_grams = _bigrams(question)
    if not query_grams:
        return []

    scored: list[tuple[float, Document]] = []
    for doc in docs:
        doc_grams = _bigrams(doc.page_content)
        if not doc_grams:
            continue
        overlap = len(query_grams & doc_grams) / len(query_grams)
        if overlap > 0:
            doc.metadata = {**doc.metadata, "retrieved_by": "fallback"}
            scored.append((overlap, doc))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [doc for _, doc in scored[:top_k]]


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------
def _resolve_index_path(raw: str) -> str:
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    return str(get_project_root() / path)


def hybrid_search(
    question: str,
    top_k: int | None = None,
    enable_graph: bool = True,
) -> list[Document]:
    """多路检索 + 融合的完整流程（任一路不可用时自动降级）

    Args:
        question: 用户问题
        top_k: 最终返回条数，默认读配置
        enable_graph: 是否启用图检索。评测/消融实验里关掉它，
            可以把"检索算法本身的贡献"与"LLM 实体抽取延迟"分开看
    """
    config = load_config()
    retrieval_cfg = config.get("retrieval", {})
    top_k = top_k or int(retrieval_cfg.get("final_top_k", 8))

    vector_results: list[Document] = []
    graph_results: list[dict] = []
    bm25_results: list[Document] = []

    # 词汇检索：纯本地计算，无 Key 无 Neo4j 也能跑，作为兜底的一路
    try:
        from src.retrieval.bm25 import bm25_search

        bm25_results = bm25_search(
            question, top_k=int(retrieval_cfg.get("bm25_top_k", 8))
        )
    except Exception as exc:  # 语料缺失等异常不应阻断整条链路
        logger.warning("BM25 检索不可用，本次跳过：%s", exc)

    try:
        from src.retrieval.vector_search import get_engine

        index_dir = Path(
            _resolve_index_path(retrieval_cfg.get("index_path", "data/embeddings"))
        )
        # 先判文件再建客户端：构造 Embedding 客户端要几秒，索引不在时没必要付这个代价
        if not (index_dir / "index.faiss").exists():
            raise FileNotFoundError(
                f"向量索引不存在：{index_dir}，请先运行 python scripts/build_index.py"
            )

        # 引擎按路径缓存：建索引要跑 3942 条 Embedding，绝不能发生在请求线程里
        engine = get_engine(index_dir)
        vector_results = engine.query(question, top_k=int(retrieval_cfg.get("vector_top_k", 5)))
    except Exception as exc:  # 索引缺失 / 无 Embedding Key → 退化为单路
        logger.warning("向量检索不可用，本次跳过：%s", exc)

    if enable_graph:
        try:
            from src.retrieval.graph_search import graph_search

            graph_results = graph_search(
                question, top_k=int(retrieval_cfg.get("graph_top_k", 5))
            )
        except Exception as exc:  # Neo4j 未启动 / 连接失败 → 退化为单路
            logger.warning("图检索不可用，本次跳过：%s", exc)

    if not vector_results and not graph_results and not bm25_results:
        logger.warning("三路检索均无结果，使用离线兜底检索")
        return fallback_keyword_search(question, top_k=top_k)

    fused = fuse_results(
        vector_results, graph_results, top_k=top_k, bm25_results=bm25_results
    )
    return reserve_case_slots(
        fused,
        graph_results,
        top_k=top_k,
        case_slots=int(retrieval_cfg.get("graph_case_limit", 2)),
    )


def build_vector_index(include_cases: bool | None = None) -> int:
    """从当前语料重建 FAISS 索引，返回文档条数

    语料优先取 data/processed/laws.json（由 scripts/fetch_laws.py 生成），
    缺失时回退内置示例。

    Args:
        include_cases: 是否把案例一起向量化。None 时读
            ``retrieval.include_cases_in_text_search``（默认 False）。
            1.7 万条案例会产生上千次 Embedding 调用，而图检索按条号/罪名
            召回类案本就更准，所以默认不入索引。
    """
    from src.data.collector import load_cases, load_laws
    from src.retrieval.vector_search import (
        VectorSearchEngine,
        build_documents,
        reset_engine_cache,
    )

    config = load_config()
    index_path = _resolve_index_path(
        config.get("retrieval", {}).get("index_path", "data/embeddings")
    )

    if include_cases is None:
        include_cases = bool(
            (config.get("retrieval") or {}).get("include_cases_in_text_search", False)
        )

    docs = build_documents(load_laws(), source_type="law")
    if include_cases:
        docs += build_documents(load_cases(), source_type="case")

    engine = VectorSearchEngine()
    engine.build_index(docs)
    engine.save_index(index_path)
    # 同一进程内重建后，旧引擎持有的还是旧索引
    reset_engine_cache()
    return len(docs)
