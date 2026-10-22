"""CAIL2018 案例语料加载

把赛事数据集转成项目 ``Case`` 节点需要的结构，供 ``scripts/import_cail.py``
和向量/BM25 语料复用。

原始数据有三处不一致，都在本模块里一次性抹平：

1. **条号类型**：``exercise_contest`` 里是整数 ``[264]``，
   ``first_stage`` 里是字符串 ``["234"]``。不归一化就会静默漏建关系边。
2. **条号写法**：数据里是阿拉伯数字，语料里存的是「第二百六十四条」，
   必须经 ``int_to_cn`` 转换才能和 ``Law`` 节点对上。
3. **刑期三态**：``term_of_imprisonment`` 的三个字段可能全为 false，
   这既可能是免予刑事处罚，也可能是管制或拘役——CAIL 没区分。
   此时**留空**比硬编「有期徒刑0月」诚实。

格式为 JSONL（一行一条），也兼容标准 JSON 数组。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Iterator

from src.config import get_project_root
from src.retrieval.graph_search import int_to_cn

logger = logging.getLogger(__name__)

DEFAULT_CASE_FILE = get_project_root() / "data" / "raw" / "cail" / "data_valid.json"


# --------------------------------------------------------------------------
# 字段归一化
# --------------------------------------------------------------------------
def to_article_int(value) -> int | None:
    """把条号统一成 int，无法解析时返回 None

    容忍 ``264`` / ``"264"`` / ``"第264条"`` 三种写法，其余一律视为脏数据。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None

    text = str(value).strip().strip("第条")
    return int(text) if text.isdigit() and int(text) > 0 else None


def normalize_articles(values: Iterable) -> list[int]:
    """条号列表归一化：转 int、去重、保持原顺序"""
    result: list[int] = []
    for value in values or []:
        number = to_article_int(value)
        if number is not None and number not in result:
            result.append(number)
    return result


def render_judgment(term: dict | None) -> str:
    """把 ``term_of_imprisonment`` 渲染成人类可读的判决结果

    ``imprisonment <= 0`` 且非死非无期时返回空串：CAIL 没有区分
    免予刑事处罚 / 管制 / 拘役，编一个具体刑期会污染类案参考。
    """
    if not isinstance(term, dict):
        return ""

    if term.get("death_penalty"):
        return "死刑"
    if term.get("life_imprisonment"):
        return "无期徒刑"

    try:
        months = int(term.get("imprisonment") or 0)
    except (TypeError, ValueError):
        return ""
    if months <= 0:
        return ""

    years, rest = divmod(months, 12)
    if years and rest:
        return f"有期徒刑{years}年{rest}个月"
    if years:
        return f"有期徒刑{years}年"
    return f"有期徒刑{rest}个月"


def render_applicable_law(articles: list[int]) -> str:
    """条号列表 → 「刑法第二百六十四条、第三百一十二条」

    必须带法名前缀：``import_relations`` 靠它把跨法重名的条号收窄，
    而 CAIL 全是刑事案件，法名恒为刑法。
    """
    return "、".join(f"刑法第{int_to_cn(number)}条" for number in articles)


# --------------------------------------------------------------------------
# 单条转换
# --------------------------------------------------------------------------
def convert_record(record: dict, index: int, prefix: str = "CAIL") -> dict | None:
    """CAIL 单条记录 → 项目 Case 字典

    Returns:
        case 字典；缺少事实或法条时返回 None（这类记录建不出 ``APPLIES`` 边，
        留在图谱里只是个孤立节点，不如不导）
    """
    fact = (record.get("fact") or "").strip()
    meta = record.get("meta") or {}
    articles = normalize_articles(meta.get("relevant_articles") or [])
    if not fact or not articles:
        return None

    accusations = [str(a).strip() for a in (meta.get("accusation") or []) if str(a).strip()]

    return {
        "case_id": f"{prefix}-{index:06d}",
        "case_type": "刑事",
        "crime": "、".join(accusations),
        "fact": fact,
        "judgment": render_judgment(meta.get("term_of_imprisonment")),
        "applicable_law": render_applicable_law(articles),
        # 结构化条号留给导入器直接建边，不必再从字符串里反解
        "article_numbers": articles,
    }


# --------------------------------------------------------------------------
# 文件读取
# --------------------------------------------------------------------------
def iter_records(path: Path | str) -> Iterator[dict]:
    """逐条读取 CAIL 数据，兼容 JSONL 与 JSON 数组两种格式"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到 CAIL 数据文件：{path}")

    with path.open("r", encoding="utf-8") as handle:
        first = handle.read(1)
        handle.seek(0)
        if first.strip() == "[":
            for record in json.load(handle):
                if isinstance(record, dict):
                    yield record
            return

        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("跳过第 %s 行：不是合法 JSON", line_no)
                continue
            if isinstance(record, dict):
                yield record


def load_cases(
    path: Path | str | None = None,
    limit: int | None = None,
    prefix: str = "CAIL",
) -> list[dict]:
    """读取并转换 CAIL 案例

    Args:
        path: 数据文件路径，默认 ``data/raw/cail/data_valid.json``
        limit: 最多转换多少条**有效**记录（None 为全部）
        prefix: case_id 前缀，同一图谱里导入多个 split 时应区分

    Returns:
        项目 Case 字典列表
    """
    path = Path(path) if path else DEFAULT_CASE_FILE

    cases: list[dict] = []
    skipped = 0
    seen = 0
    for record in iter_records(path):
        seen += 1
        case = convert_record(record, len(cases) + 1, prefix=prefix)
        if case is None:
            skipped += 1
            continue
        cases.append(case)
        if limit is not None and len(cases) >= limit:
            break

    logger.info(
        "CAIL 读取完成：扫描 %s 条，有效 %s 条，跳过 %s 条", seen, len(cases), skipped
    )
    return cases
