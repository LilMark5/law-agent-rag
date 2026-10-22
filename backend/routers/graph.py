"""GET /api/graph —— 知识图谱只读接口

把 Neo4j 里的真实图数据透给前端图谱页，替换掉原来 ``lib/data.ts`` 里
5 个硬编码节点。两个端点：

    GET /api/graph/stats                     → 全局节点/边统计
    GET /api/graph/subgraph?article=第二百三十二条 → 按条号捞一个局部子图

子图结构 = 命中法条 + 适用它的案例 + 这些案例涉及的其他法条（二跳）。
这正是 GraphRAG「沿关系找到向量找不到的结构」的最小可交互展示。
Neo4j 未启动时返回空结构 + 200，前端据此渲染空态，不报错。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter()

# 子图最多带回的节点数：法条数量有限，案例是热门法条会挂上千条，必须截断。
MAX_NODES = 60


def _stats_queries(session) -> tuple[int, int, int]:
    """返回 (law 数, case 数, applies 边数)，任一查询失败降级为 0。"""
    counts: list[int] = []

    def scalar(cypher: str) -> int:
        try:
            record = session.run(cypher).single()
            return int(record[0]) if record else 0
        except Exception as exc:
            logger.warning("图谱统计查询失败：%s", exc)
            return 0

    counts.append(scalar("MATCH (l:Law) RETURN count(l)"))
    counts.append(scalar("MATCH (c:Case) RETURN count(c)"))
    counts.append(scalar("MATCH (:Case)-[r:APPLIES]->(:Law) RETURN count(r)"))
    return counts[0], counts[1], counts[2]


_SUBGRAPH_QUERY = """
MATCH (l:Law {article_number: $article})
WHERE $law = '' OR l.law_name CONTAINS $law
OPTIONAL MATCH (c:Case)-[:APPLIES]->(l)
WITH l, collect(DISTINCT c)[..$case_limit] AS cases
UNWIND cases AS c
OPTIONAL MATCH (c)-[:APPLIES]->(other:Law)
WHERE other.article_number <> l.article_number
RETURN l, collect(DISTINCT c) AS cases, collect(DISTINCT other) AS others
LIMIT 1
"""


def _node_to_dict(node) -> dict:
    props = dict(node)
    labels = list(node.labels)
    if "Law" in labels:
        return {
            "id": f"law:{props.get('law_name', '')}:{props.get('article_number', '')}",
            "type": "law",
            "label": props.get("article_number", ""),
            "law_name": props.get("law_name", ""),
            "chapter": props.get("chapter", ""),
            "content": (props.get("content") or "")[:120],
        }
    return {
        "id": f"case:{props.get('case_id', '')}",
        "type": "case",
        "label": props.get("case_id", ""),
        "crime": props.get("crime", ""),
        "judgment": props.get("judgment", ""),
        "fact": (props.get("fact") or "")[:80],
    }


@router.get("/graph/stats")
async def graph_stats():
    try:
        from src.data.kg_builder import get_neo4j_driver

        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j 驱动创建失败，返回空统计：%s", exc)
        return {"laws": 0, "cases": 0, "relations": 0, "available": False}

    try:
        with driver.session() as session:
            laws, cases, relations = _stats_queries(session)
    except Exception as exc:
        logger.warning("Neo4j 连接失败，返回空统计：%s", exc)
        laws = cases = relations = 0
    finally:
        try:
            driver.close()
        except Exception:
            pass

    return {
        "laws": laws,
        "cases": cases,
        "relations": relations,
        "available": bool(laws or cases),
    }


@router.get("/graph/subgraph")
async def graph_subgraph(
    article: str = Query(..., min_length=1, max_length=32),
    law: str = Query("", max_length=64),
):
    """按条号返回局部子图。

    条号用中文数字（如「第二百六十四条」）。条号跨法重名（民法典/刑法
    都有第 X 条），可选传 ``law``（法名关键词，如「刑法」）收窄到某一部法。
    """
    try:
        from src.data.kg_builder import get_neo4j_driver

        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j 驱动创建失败：%s", exc)
        return {"nodes": [], "edges": [], "available": False, "article": article}

    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    def add_node(node) -> None:
        if node is None:
            return
        item = _node_to_dict(node)
        if item["id"] in node_ids:
            return
        node_ids.add(item["id"])
        nodes.append(item)

    try:
        with driver.session() as session:
            record = session.run(
                _SUBGRAPH_QUERY,
                {"article": article, "law": law, "case_limit": MAX_NODES},
            ).single()
            if record:
                law_node, cases, others = record["l"], record["cases"], record["others"]
                add_node(law_node)
                for case in cases or []:
                    add_node(case)
                    if case is not None:
                        edges.append(
                            {
                                "from": _node_to_dict(case)["id"],
                                "to": _node_to_dict(law_node)["id"],
                                "label": "适用",
                            }
                        )
                for other in others or []:
                    add_node(other)
                    if other is not None and cases:
                        # 案例指向其他法条
                        for case in cases:
                            if case is None:
                                continue
                            edges.append(
                                {
                                    "from": _node_to_dict(case)["id"],
                                    "to": _node_to_dict(other)["id"],
                                    "label": "适用",
                                }
                            )
    except Exception as exc:
        logger.warning("子图查询失败：%s", exc)
    finally:
        try:
            driver.close()
        except Exception:
            pass

    # 截断保护：热门法条会挂上千案例，这里只保留前 N 个
    nodes = nodes[:MAX_NODES]
    kept_ids = {n["id"] for n in nodes}
    edges = [
        e for e in edges if e["from"] in kept_ids and e["to"] in kept_ids
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "available": bool(nodes),
        "article": article,
    }
