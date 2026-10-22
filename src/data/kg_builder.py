"""知识图谱构建模块：提取实体关系并写入Neo4j

语料规模上来后（数千条条文），逐条 ``session.run`` 会变成数千次网络往返，
写入时间以十分钟计。因此导入统一走 ``UNWIND $rows`` 批量提交。
"""

from __future__ import annotations

import re

from src.config import load_config

BATCH_SIZE = 500

_ARTICLE_PATTERN = re.compile(
    r"(第[一二三四五六七八九十百千零〇]+条(?:之[一二三四五六七八九十]{1,3})?)"
)
_SEGMENT_SEPARATORS = re.compile(r"[、，,；;]")


def parse_applicable_law(raw: str) -> list[tuple[str, str]]:
    """把 applicable_law 拆成多组 (法名提示, 条号)

    一条案例常同时适用多个法条（CAIL2018 里占 17.4%）。原实现用
    ``pattern.search`` 只取第一个，后面的边全部丢失——而多法条关联
    正是图谱二跳检索的价值来源。

    「刑法第二百六十四条、第三百一十二条」的第二段没有法名，
    需要继承上一段的法名；否则「第三百一十二条」会拿去全库匹配，
    在 24 部法规里命中十几条同名条号，连出一堆错边。
    """
    results: list[tuple[str, str]] = []
    last_hint = ""

    for segment in _SEGMENT_SEPARATORS.split(raw or ""):
        match = _ARTICLE_PATTERN.search(segment)
        if not match:
            continue

        hint = segment[: match.start()].strip(" 《》　")
        hint = hint or last_hint
        last_hint = hint

        item = (hint, match.group(1))
        if item not in results:
            results.append(item)

    return results


def get_neo4j_driver():
    """获取Neo4j驱动"""
    from neo4j import GraphDatabase

    config = load_config()
    driver = GraphDatabase.driver(
        config["neo4j"]["uri"],
        auth=(config["neo4j"]["username"], config["neo4j"]["password"]),
    )
    return driver


def ensure_constraints(driver) -> None:
    """建立唯一约束与检索索引

    MERGE 依赖 (law_name, article_number) 唯一性；没有索引时每次 MERGE
    都要全表扫描，批量导入会退化成平方复杂度。
    """
    statements = [
        "CREATE CONSTRAINT law_key IF NOT EXISTS "
        "FOR (l:Law) REQUIRE (l.law_name, l.article_number) IS UNIQUE",
        "CREATE CONSTRAINT case_key IF NOT EXISTS "
        "FOR (c:Case) REQUIRE c.case_id IS UNIQUE",
        "CREATE INDEX law_name_idx IF NOT EXISTS FOR (l:Law) ON (l.law_name)",
        "CREATE INDEX law_domain_idx IF NOT EXISTS FOR (l:Law) ON (l.domain)",
        # 建关系时按条号反查法条。复合约束 (law_name, article_number) 的首列是
        # law_name，单独用 article_number 查用不上它，2 万条案例逐行扫全表会很慢。
        "CREATE INDEX law_article_idx IF NOT EXISTS FOR (l:Law) ON (l.article_number)",
    ]
    with driver.session() as session:
        for statement in statements:
            session.run(statement)


def build_cypher_for_law_node(law: dict) -> tuple[str, dict]:
    """构建法规节点的Cypher语句和参数"""
    cypher = """
    MERGE (l:Law {article_number: $article_number, law_name: $law_name})
    SET l.chapter = $chapter, l.content = $content
    """
    params = {
        "law_name": law["law_name"],
        "chapter": law.get("chapter", ""),
        "article_number": law["article_number"],
        "content": law["content"],
    }
    return cypher, params


def build_cypher_for_case_node(case: dict) -> tuple[str, dict]:
    """构建案例节点的Cypher语句和参数"""
    cypher = """
    MERGE (c:Case {case_id: $case_id})
    SET c.case_type = $case_type, c.crime = $crime,
        c.fact = $fact, c.judgment = $judgment,
        c.applicable_law = $applicable_law
    """
    params = {
        "case_id": case["case_id"],
        "case_type": case.get("case_type", ""),
        "crime": case.get("crime", ""),
        "fact": case.get("fact", ""),
        "judgment": case.get("judgment", ""),
        "applicable_law": case.get("applicable_law", ""),
    }
    return cypher, params


def build_cypher_for_relation(
    from_label: str, from_id_field: str, from_id_value: str,
    to_label: str, to_id_field: str, to_id_value: str,
    relation_type: str,
) -> tuple[str, dict]:
    """构建关系边的Cypher语句和参数"""
    cypher = f"""
    MATCH (a:{from_label} {{{from_id_field}: $from_id}})
    MATCH (b:{to_label} {{{to_id_field}: $to_id}})
    MERGE (a)-[:{relation_type}]->(b)
    """
    params = {"from_id": from_id_value, "to_id": to_id_value}
    return cypher, params


def import_laws(laws: list[dict], driver=None, batch_size: int = BATCH_SIZE) -> int:
    """批量导入法规节点到Neo4j

    Args:
        laws: 条文列表（law_name/article_number/content 必需）
        driver: 已有驱动，None 时新建
        batch_size: 每批 UNWIND 的条数

    Returns:
        成功导入的节点数量
    """
    if not laws:
        return 0
    if driver is None:
        driver = get_neo4j_driver()

    cypher = """
    UNWIND $rows AS row
    MERGE (l:Law {law_name: row.law_name, article_number: row.article_number})
    SET l.content = row.content,
        l.chapter = row.chapter,
        l.part = row.part,
        l.section = row.section,
        l.chapter_path = row.chapter_path,
        l.article_index = row.article_index,
        l.domain = row.domain
    """

    def to_row(law: dict) -> dict:
        return {
            "law_name": law["law_name"],
            "article_number": law["article_number"],
            "content": law["content"],
            "chapter": law.get("chapter", ""),
            "part": law.get("part", ""),
            "section": law.get("section", ""),
            "chapter_path": law.get("chapter_path", ""),
            "article_index": law.get("article_index", 0),
            "domain": law.get("domain", ""),
        }

    count = 0
    with driver.session() as session:
        for start in range(0, len(laws), batch_size):
            chunk = laws[start : start + batch_size]
            session.run(cypher, rows=[to_row(law) for law in chunk])
            count += len(chunk)
    return count


def import_cases(cases: list[dict], driver=None, batch_size: int = BATCH_SIZE) -> int:
    """批量导入案例节点到Neo4j

    Returns:
        成功导入的节点数量
    """
    if not cases:
        return 0
    if driver is None:
        driver = get_neo4j_driver()

    cypher = """
    UNWIND $rows AS row
    MERGE (c:Case {case_id: row.case_id})
    SET c.case_type = row.case_type, c.crime = row.crime,
        c.fact = row.fact, c.judgment = row.judgment,
        c.applicable_law = row.applicable_law
    """
    rows = [
        {
            "case_id": case["case_id"],
            "case_type": case.get("case_type", ""),
            "crime": case.get("crime", ""),
            "fact": case.get("fact", ""),
            "judgment": case.get("judgment", ""),
            "applicable_law": case.get("applicable_law", ""),
        }
        for case in cases
    ]

    count = 0
    with driver.session() as session:
        for start in range(0, len(rows), batch_size):
            session.run(cypher, rows=rows[start : start + batch_size])
            count += len(rows[start : start + batch_size])
    return count


def import_relations(cases: list[dict], driver=None, batch_size: int = BATCH_SIZE) -> int:
    """根据案例的 applicable_law 建立「案例-法条」关系

    applicable_law 形如「劳动合同法第八十二条」，一条案例可能同时适用多个法条
    （以顿号分隔）。语料扩到多部法规后，单靠条号匹配会同时命中多部法的同名条款
    （第八十二条在 24 部法里出现了十几次），因此必须带上法名限定。

    Returns:
        成功创建的关系数量
    """
    if not cases:
        return 0
    if driver is None:
        driver = get_neo4j_driver()

    rows = []
    for case in cases:
        for law_hint, article_number in parse_applicable_law(
            case.get("applicable_law", "")
        ):
            rows.append(
                {
                    "case_id": case["case_id"],
                    "article_number": article_number,
                    "law_hint": law_hint,
                }
            )

    if not rows:
        return 0

    cypher = """
    UNWIND $rows AS row
    MATCH (c:Case {case_id: row.case_id})
    MATCH (l:Law {article_number: row.article_number})
    WHERE row.law_hint = '' OR l.law_name CONTAINS row.law_hint
    MERGE (c)-[:APPLIES]->(l)
    """
    count = 0
    with driver.session() as session:
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            result = session.run(cypher, rows=chunk)
            summary = result.consume()
            count += summary.counters.relationships_created
    return count


def build_knowledge_graph(laws: list[dict], cases: list[dict]) -> dict:
    """构建完整知识图谱：建约束 + 导入节点 + 建立关系

    Returns:
        统计信息字典
    """
    driver = get_neo4j_driver()
    try:
        ensure_constraints(driver)
        law_count = import_laws(laws, driver)
        case_count = import_cases(cases, driver)
        relation_count = import_relations(cases, driver)
        return {
            "law_nodes": law_count,
            "case_nodes": case_count,
            "relations": relation_count,
        }
    finally:
        driver.close()