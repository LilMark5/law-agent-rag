"""GET /api/system/stats —— 运维面板的数据源

管理页此前展示的是 ``lib/data.ts`` 里写死的四个指标（「图谱覆盖 18.4k」等），
与库里的真实规模对不上。这里把**可真实查到**的运维数据一次性给全：

    graph        Neo4j 节点/关系规模 + 法规部数 + 各法规条数 Top K
    vectorIndex  FAISS 索引文件是否存在、多大
    llm/embedding 是否已配置、用哪个模型（只回模型名，绝不回 Key）

任何一路查询失败都降级成空值 + 200，前端据此显示「未连接」，不中断整页。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

TOP_LAW_BOOKS = 6


def _scalar(session, cypher: str) -> int:
    try:
        record = session.run(cypher).single()
        return int(record[0]) if record else 0
    except Exception as exc:
        logger.warning("运维统计查询失败（%s）：%s", cypher.split("RETURN")[-1].strip(), exc)
        return 0


def _graph_stats() -> tuple[dict, list[dict]]:
    """返回 (规模统计, 法规条数 top K)。Neo4j 不可用时返回零值。"""
    graph = {"laws": 0, "cases": 0, "relations": 0, "lawBooks": 0, "available": False}
    top: list[dict] = []

    try:
        from src.data.kg_builder import get_neo4j_driver

        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j 驱动创建失败：%s", exc)
        return graph, top

    try:
        with driver.session() as session:
            graph["laws"] = _scalar(session, "MATCH (l:Law) RETURN count(l)")
            graph["cases"] = _scalar(session, "MATCH (c:Case) RETURN count(c)")
            graph["relations"] = _scalar(
                session, "MATCH (:Case)-[r:APPLIES]->(:Law) RETURN count(r)"
            )
            graph["lawBooks"] = _scalar(
                session, "MATCH (l:Law) RETURN count(DISTINCT l.law_name)"
            )
            try:
                for record in session.run(
                    "MATCH (l:Law) RETURN l.law_name AS name, count(l) AS articles "
                    "ORDER BY articles DESC LIMIT $limit",
                    {"limit": TOP_LAW_BOOKS},
                ):
                    top.append(
                        {"name": record["name"] or "", "articles": int(record["articles"])}
                    )
            except Exception as exc:
                logger.warning("法规分布查询失败：%s", exc)
        graph["available"] = bool(graph["laws"] or graph["cases"])
    except Exception as exc:
        logger.warning("Neo4j 连接失败：%s", exc)
    finally:
        try:
            driver.close()
        except Exception:
            pass

    return graph, top


def _vector_index_stats(cfg: dict) -> dict:
    """FAISS 索引文件状态。只读文件元信息，不加载模型。"""
    info = {"exists": False, "sizeMb": 0.0}
    try:
        from src.retrieval.fusion import _resolve_index_path

        index_dir = _resolve_index_path(
            (cfg.get("retrieval") or {}).get("index_path", "data/embeddings")
        )
        index_file = Path(index_dir) / "index.faiss"
        if index_file.exists():
            info["exists"] = True
            info["sizeMb"] = round(index_file.stat().st_size / 1024 / 1024, 1)
    except Exception as exc:
        logger.warning("向量索引状态检查失败：%s", exc)
    return info


@router.get("/system/stats")
async def system_stats():
    from src.config import load_config

    cfg = load_config()
    graph, top_law_books = _graph_stats()

    llm_cfg = cfg.get("llm") or {}
    embedding_cfg = cfg.get("embedding") or {}
    review_cfg = cfg.get("review") or {}
    retrieval_cfg = cfg.get("retrieval") or {}

    return {
        "graph": graph,
        "topLawBooks": top_law_books,
        "vectorIndex": _vector_index_stats(cfg),
        "llm": {
            "configured": bool(llm_cfg.get("api_key")),
            "model": llm_cfg.get("model", ""),
        },
        "embedding": {
            "configured": bool(embedding_cfg.get("api_key")),
            "model": embedding_cfg.get("model", ""),
            "dimension": int(embedding_cfg.get("dimension", 0) or 0),
        },
        "review": {
            "enabled": bool(review_cfg.get("enabled", True)),
            "mode": "llm" if review_cfg.get("use_llm") else "rule",
            "max_retry": int(review_cfg.get("max_retry", 0) or 0),
        },
        "retrieval": {
            "fusion": retrieval_cfg.get("fusion_strategy", "rrf"),
            "finalTopK": int(retrieval_cfg.get("final_top_k", 0) or 0),
            "graphHop": int(retrieval_cfg.get("graph_hop", 0) or 0),
        },
    }
