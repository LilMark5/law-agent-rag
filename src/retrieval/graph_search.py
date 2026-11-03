"""图检索模块：Neo4j Cypher 查询与实体抽取

设计要点：
1. **所有实体值走 $param 参数绑定**，不拼进 Cypher 字符串（防注入、可复用执行计划）。
2. **分路查询**：法条按条号/正文命中、案例按罪名/事实命中，各自独立可解释。
3. **二跳扩展**：命中法条 → 关联案例 → 这些案例涉及的其他法条（GraphRAG 的价值所在）。
4. **连接失败自动降级**：Neo4j 未启动时返回空列表，不阻断整条问答链路。
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from openai import OpenAI

from src.config import load_config

logger = logging.getLogger(__name__)

# 直接命中：只按**条号精确匹配**（可选再用法名收窄）
#
# 刻意不做 ``l.content CONTAINS 术语``：实测这样召回的是"提到该词的任意法条"，
# 既没有排序也没有区分度，等于把 BM25 的活重做一遍还更差。这种"噪声提名"
# 进入融合后会挤掉向量检索的正确答案（实测 MRR 0.741 → 0.644）。
# 图检索的价值在于**精确结构命中**：给定条号/罪名，沿关系找得到、而向量找不到。
DIRECT_QUERY = """
MATCH (l:Law)
WHERE $articles <> [] AND l.article_number IN $articles
  AND ($law_names = [] OR any(n IN $law_names WHERE l.law_name CONTAINS n))
RETURN l
LIMIT $limit
"""

# 案例命中：问题里只提到罪名/事实时，直接捞案例
CASE_QUERY = """
MATCH (c:Case)
WHERE any(t IN $terms WHERE c.crime CONTAINS t OR c.fact CONTAINS t)
RETURN DISTINCT c
LIMIT $limit
"""

# 给定条号捞适用该条的案例（条号方向的类案检索）
CASE_BY_ARTICLE_QUERY = """
MATCH (c:Case)-[:APPLIES]->(l:Law)
WHERE l.article_number IN $articles
  AND ($law_names = [] OR any(n IN $law_names WHERE l.law_name CONTAINS n))
RETURN DISTINCT c
LIMIT $limit
"""

# 二跳扩展：从命中法条出发，经案例找到其他法条
EXPAND_QUERY = """
MATCH (l:Law)
WHERE l.article_number IN $articles
OPTIONAL MATCH (c:Case)-[:APPLIES]->(l)
OPTIONAL MATCH (c)-[:APPLIES]->(l2:Law)
WHERE l2.article_number <> l.article_number
RETURN l2
LIMIT $limit
"""


# --------------------------------------------------------------------------
# 实体抽取
# --------------------------------------------------------------------------
_ARTICLE_RE = re.compile(
    r"第([0-9]+|[一二三四五六七八九十百千零〇]+)条"
    r"(?:之([0-9]+|[一二三四五六七八九十]+))?"
)
_CRIME_HINTS = (
    "盗窃", "诈骗", "抢劫", "故意伤害", "故意杀人", "贪污", "受贿", "行贿",
    "危险驾驶", "交通肇事", "非法拘禁", "寻衅滋事", "强奸", "绑架", "贩毒",
)

_CN_DIGITS = "零一二三四五六七八九"
_CN_UNITS = ["", "十", "百", "千"]


def int_to_cn(num: int) -> str:
    """整数转中文数字（法条编号够用，上限 9999）

    语料里的条号存的是"第二百三十二条"，但用户常写"第232条"。
    不统一就永远检索不到，所以这里做一次归一化。
    """
    if num <= 0:
        return ""
    if num < 10:
        return _CN_DIGITS[num]

    digits = str(num)
    length = len(digits)
    parts: list[str] = []
    zero_pending = False

    for index, char in enumerate(digits):
        digit = int(char)
        unit = _CN_UNITS[length - index - 1]
        if digit == 0:
            zero_pending = True
            continue
        if zero_pending and parts:
            parts.append("零")
        zero_pending = False
        parts.append(_CN_DIGITS[digit] + unit)

    result = "".join(parts)
    # 10~19 习惯写"十一"而不是"一十一"
    if result.startswith("一十"):
        result = result[1:]
    return result


def extract_article_numbers(text: str) -> list[str]:
    """抽出问题里的条号并统一成中文数字写法（支持 第232条 / 第232条之一）"""
    found: list[str] = []
    for match in _ARTICLE_RE.finditer(text):
        number, suffix = match.group(1), match.group(2)
        if number.isdigit():
            number = int_to_cn(int(number))
        if suffix:
            if suffix.isdigit():
                suffix = int_to_cn(int(suffix))
            found.append(f"第{number}条之{suffix}")
        else:
            found.append(f"第{number}条")
    return list(dict.fromkeys(found))


@lru_cache(maxsize=1)
def law_name_index() -> tuple[tuple[str, str], ...]:
    """(匹配用简称, 完整法名) 列表，按简称长度降序

    为什么要用真实语料里的法名做词典，而不是正则 ``xx法``：
    正则会把"方法""办法""做法"都当成法名，反而污染查询条件。
    词典还解决了"第232条"跨法重名的问题——问题里出现"刑法"就只查刑法。
    """
    try:
        from src.data.collector import load_laws

        names = {law["law_name"] for law in load_laws()}
    except Exception:  # 语料缺失时退化为空词典，不影响其他检索路径
        return ()

    pairs: list[tuple[str, str]] = []
    for full in names:
        short = full.replace("中华人民共和国", "")
        if short:
            pairs.append((short, full))
        pairs.append((full, full))

    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(pairs)


def match_law_names(text: str, limit: int = 2) -> list[str]:
    """找出问题里提到的法名，返回完整法名（去重、最多 limit 个）"""
    hits: list[str] = []
    for short, full in law_name_index():
        if short in text and full not in hits:
            hits.append(full)
            if len(hits) >= limit:
                break
    return hits


@lru_cache(maxsize=512)
def extract_entities(question: str) -> dict:
    """从用户问题中提取法律实体（条款号 / 罪名 / 法律术语）

    策略：**规则优先、LLM 兜底**。
    - 条号 ``第X条``、罪名关键词都能用正则/词典直接拿到，这类请求不必问模型
    - 只有规则一无所获时，才花一次 LLM 调用；且带超时与缓存

    这样把"每条查询固定多等 3~8 秒"降成"多数查询 0 次模型调用"。
    抽取失败时返回空结构，由调用方决定是否跳过图检索。
    """
    entities = {"article_numbers": [], "crimes": [], "legal_terms": []}

    # 1. 条号：正则直接命中（阿拉伯数字自动转中文，否则对不上语料）
    entities["article_numbers"] = extract_article_numbers(question)

    # 2. 罪名：语料里罪名有限，用词典扫一遍比模型可靠
    entities["crimes"] = [c for c in _CRIME_HINTS if c in question]

    # 3. 法名：用真实语料里的法名词典匹配，避免"方法/办法"这类误命中
    entities["legal_terms"] = match_law_names(question)

    # 规则已经拿到可用实体 → 直接返回，省掉一次 LLM 往返
    if entities["article_numbers"] or entities["crimes"]:
        return entities

    config = load_config()
    if not (config.get("retrieval") or {}).get("graph_use_llm_entities", False):
        # 检索链路上默认不调 LLM：每条查询固定多等 3~8 秒，换来的精度提升接近 0
        # （实测 33 条 gold：开 LLM 抽取 Recall 不变，单查询延迟 442ms → 5226ms）
        return entities

    if not (config.get("llm") or {}).get("api_key"):
        # 没 Key 就别发请求，否则每次检索都要白等一次网络超时
        return entities

    client = OpenAI(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"]["base_url"],
        timeout=15,
        max_retries=0,
    )

    prompt = f"""从以下法律问题中提取关键实体，返回 JSON 格式：
{{
  "article_numbers": ["提取到的条款号，统一写成中文数字形式，如第二百三十二条"],
  "crimes": ["提取到的罪名，如盗窃"],
  "legal_terms": ["提取到的法律术语，如正当防卫"]
}}

问题：{question}

只返回 JSON，不要其他内容。"""

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
        merged = {
            "article_numbers": data.get("article_numbers") or [],
            "crimes": data.get("crimes") or [],
            "legal_terms": data.get("legal_terms") or entities["legal_terms"],
        }
        # 规则抽出的法名不能丢
        if entities["legal_terms"] and not merged["legal_terms"]:
            merged["legal_terms"] = entities["legal_terms"]
        return merged
    except Exception as exc:
        logger.warning("实体抽取失败，跳过图检索：%s", exc)
        return entities


# --------------------------------------------------------------------------
# Cypher 构建（全部参数化）
# --------------------------------------------------------------------------
def build_graph_query(entities: dict, hop: int = 2) -> tuple[str, dict]:
    """构建直接命中的 Cypher 与参数字典

    只在**问题里出现明确条号**时才走图检索。术语/法名不构成高精度条件，
    走它只会引入噪声（见 DIRECT_QUERY 注释）。

    Returns:
        (cypher, params)。无可用条号时返回 ("", {})，调用方应直接跳过。
    """
    articles = [a for a in (entities.get("article_numbers") or []) if a]
    if not articles:
        return "", {}

    # 法名用来把"第八十二条"这种跨法重名的条号收窄
    law_names = [t for t in (entities.get("legal_terms") or []) if t]

    params = {
        "articles": articles,
        "law_names": law_names,
        "limit": 8 if hop >= 2 else 5,
    }
    return DIRECT_QUERY, params


def build_expand_query(articles: list[str], limit: int = 5) -> tuple[str, dict]:
    """二跳扩展查询：给定命中条号，找经由案例关联的其他法条"""
    return EXPAND_QUERY, {"articles": articles, "limit": limit}


def build_case_query(terms: list[str], limit: int = 5) -> tuple[str, dict]:
    return CASE_QUERY, {"terms": terms, "limit": limit}


def build_case_by_article_query(
    articles: list[str], law_names: list[str] | None = None, limit: int = 2
) -> tuple[str, dict]:
    """给定条号，捞适用该条的案例"""
    return CASE_BY_ARTICLE_QUERY, {
        "articles": articles,
        "law_names": law_names or [],
        "limit": limit,
    }


# --------------------------------------------------------------------------
# 查询执行
# --------------------------------------------------------------------------
def _iter_nodes(value):
    """记录值可能是 Node、list[Node]、None，统一展开"""
    if value is None:
        return
    if hasattr(value, "labels"):
        yield value
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_nodes(item)


def _dedup_key(node) -> tuple:
    labels = tuple(sorted(node.labels))
    props = dict(node)
    identity = (
        props.get("law_name", ""),
        props.get("article_number", ""),
        props.get("case_id", ""),
    )
    return labels, identity


def _run_query(session, cypher: str, params: dict) -> list[dict]:
    results: list[dict] = []
    for record in session.run(cypher, params):
        for value in record.values():
            for node in _iter_nodes(value):
                labels = list(node.labels)
                results.append(
                    {
                        "type": labels[0] if labels else "Unknown",
                        "properties": dict(node),
                    }
                )
    return results


def graph_search(question: str, top_k: int = 5) -> list[dict]:
    """执行图检索：直接命中 → 二跳扩展 → 案例补充

    案例放在最后是有意的：热门法条挂着上千条案例，先捞案例会把
    二跳扩展挤出收集上限，而二跳才是图检索区别于向量检索的地方。

    Returns:
        节点字典列表，元素形如 {"type": "Law", "properties": {...}}
    """
    config = load_config()
    retrieval_cfg = config.get("retrieval", {})
    hop = int(retrieval_cfg.get("graph_hop", 2))
    case_limit = int(retrieval_cfg.get("graph_case_limit", 2))

    entities = extract_entities(question)

    cypher, params = build_graph_query(entities, hop=hop)

    # 案例兜底用的检索词：罪名 + 法名。问题里没有条号、或条号在语料里查不到时，
    # 就靠这些词走 CASE_QUERY（对 c.crime / c.fact 做 CONTAINS）捞案例。
    terms = list(
        dict.fromkeys(
            [t for t in (entities.get("crimes") or []) if t]
            + [t for t in (entities.get("legal_terms") or []) if t]
        )
    )

    # 两条路都空才提前返回：只看条号会漏掉"只提罪名"的问句，
    # 那样下面的案例检索就成了永远走不到的死代码。
    if not cypher and not terms:
        return []

    try:
        from src.data.kg_builder import get_neo4j_driver

        driver = get_neo4j_driver()
    except Exception as exc:
        logger.warning("Neo4j 驱动创建失败，跳过图检索：%s", exc)
        return []

    collected: dict[tuple, dict] = {}
    hit_articles: set[str] = set()

    def absorb(nodes: list[dict]) -> None:
        for node in nodes:
            props = node["properties"]
            key = (
                node["type"],
                props.get("law_name", ""),
                props.get("article_number", ""),
                props.get("case_id", ""),
            )
            if key in collected:
                continue
            if len(collected) >= top_k * 2:
                return
            collected[key] = node
            if node["type"] == "Law" and props.get("article_number"):
                hit_articles.add(props["article_number"])

    try:
        with driver.session() as session:
            if cypher:
                absorb(_run_query(session, cypher, params))

            # 二跳必须排在案例之前。热门法条（刑法第264条挂着上千条案例）
            # 一旦先被案例塞满 absorb 的上限，二跳就永远走不到——
            # 而「法条 → 类案 → 相邻法条」正是图谱这一路的价值所在。
            if hop >= 2 and hit_articles:
                expand_cypher, expand_params = build_expand_query(
                    sorted(hit_articles), limit=top_k
                )
                absorb(_run_query(session, expand_cypher, expand_params))

            # 案例补充：有条号按条号捞类案，只有罪名/法名时按罪名捞
            if hit_articles:
                case_cypher, case_params = build_case_by_article_query(
                    sorted(hit_articles),
                    entities.get("legal_terms") or [],
                    limit=case_limit,
                )
                absorb(_run_query(session, case_cypher, case_params))
            elif terms:
                case_cypher, case_params = build_case_query(terms, limit=case_limit)
                absorb(_run_query(session, case_cypher, case_params))
    except Exception as exc:
        logger.warning("Neo4j 查询失败，返回已获取结果：%s", exc)
    finally:
        try:
            driver.close()
        except Exception:
            pass

    laws = [node for node in collected.values() if node["type"] == "Law"]
    cases = [node for node in collected.values() if node["type"] != "Law"]

    # 给案例留固定名额：法条通常能占满 top_k，按"法条优先"整体截断的话
    # 案例一条也进不来，类案检索等于没做。
    reserved = min(len(cases), case_limit, max(0, top_k // 2))
    selected = laws[: top_k - reserved]
    selected += cases[: top_k - len(selected)]
    return selected
