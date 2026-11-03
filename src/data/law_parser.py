"""法规正文结构化：把 docx 段落切成「编-章-节-条」

国家法律法规数据库下载的 docx 是纯段落流，且开头带目录
（目录里的章标题与正文重复），直接按行扫描会把目录误当成章节。
因此先定位正文首个条号「第一条」，再向前回溯最近的编/章/节作为上下文。

输出的每一条与 ``src/data/collector.py`` 中的 laws 结构兼容，
额外增加 part/chapter_path/article_index 等字段供图谱与前端使用。
"""

from __future__ import annotations

import re

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_NUM = "一二三四五六七八九十百千零〇"

PART_RE = re.compile(rf"^第[{_CN_NUM}]+编[\s　]*(.*)$")
CHAPTER_RE = re.compile(rf"^第[{_CN_NUM}]+章[\s　]*(.*)$")
SECTION_RE = re.compile(rf"^第[{_CN_NUM}]+节[\s　]*(.*)$")
ARTICLE_RE = re.compile(rf"^第([{_CN_NUM}]{{1,12}})条(之[{_CN_NUM}]{{1,3}})?[\s　]*(.*)$")
TOC_RE = re.compile(r"^目[\s　]*录$")


def cn_to_int(text: str) -> int:
    """中文数字转整数，支持到千位（法条编号够用）

    >>> cn_to_int("一千二百六十")
    1260
    >>> cn_to_int("十一")
    11
    """
    total = 0
    current = 0
    for ch in text:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (current or 1) * unit
            current = 0
    return total + current


def _norm(text: str) -> str:
    """压缩空白，保留可读性（全角空格统一成普通空格）"""
    return re.sub(r"[\s　]+", " ", text).strip()


def _find_first_article(paragraphs: list[str]) -> int:
    for i, para in enumerate(paragraphs):
        if ARTICLE_RE.match(_norm(para)):
            return i
    return -1


def _seed_context(paragraphs: list[str], first_article: int) -> tuple[int, str, str, str]:
    """从首个条号回溯最近的编/章/节

    Returns:
        (起始下标, 编标题, 章标题, 节标题)
    """
    part = chapter = section = ""
    start = first_article
    for i in range(first_article - 1, -1, -1):
        text = _norm(paragraphs[i])
        if TOC_RE.match(text):
            break
        if not chapter and CHAPTER_RE.match(text):
            chapter = text
            start = i
            continue
        if chapter and not section and SECTION_RE.match(text):
            section = text
            continue
        if not part and PART_RE.match(text):
            part = text
            start = i
            break
    return start, part, chapter, section


def parse_law(
    paragraphs: list[str],
    law_name: str,
    meta: dict | None = None,
) -> list[dict]:
    """把法规段落解析为条文列表

    Args:
        paragraphs: docx 段落文本
        law_name: 法规全称
        meta: 采集元数据（bbbs/公布日期/时效性等），会并入每条记录

    Returns:
        条文列表，每条含 law_name/part/chapter/section/chapter_path/
        article_number/article_index/content 等字段

    Raises:
        ValueError: 段落中找不到任何条号
    """
    first = _find_first_article(paragraphs)
    if first < 0:
        raise ValueError(f"{law_name}：未定位到条号，可能不是法规正文")

    start, part, chapter, section = _seed_context(paragraphs, first)
    base = dict(meta or {})
    base.pop("bbbs", None)  # bbbs 只用于溯源，不重复写进每条

    articles: list[dict] = []
    current: dict | None = None

    def chapter_path() -> str:
        return " > ".join(x for x in (part, chapter, section) if x)

    for para in paragraphs[start:]:
        text = _norm(para)
        if not text:
            continue

        match = ARTICLE_RE.match(text)
        if match:
            number = f"第{match.group(1)}条{match.group(2) or ''}"
            body = match.group(3).strip()
            current = {
                "law_name": law_name,
                "part": part,
                "chapter": chapter,
                "section": section,
                "chapter_path": chapter_path(),
                "article_number": number,
                "article_index": cn_to_int(match.group(1)),
                "content": body,
                **base,
            }
            articles.append(current)
            continue

        if PART_RE.match(text):
            part, chapter, section = text, "", ""
            current = None
            continue
        if CHAPTER_RE.match(text):
            chapter, section = text, ""
            current = None
            continue
        if SECTION_RE.match(text):
            section = text
            current = None
            continue

        # 其余段落视为当前条的续文（款/项），换行保留结构
        if current is not None:
            if current["content"]:
                current["content"] += "\n" + text
            else:
                current["content"] = text

    # 丢掉正文为空的条目（极少数只有条号的占位）
    return [a for a in articles if a["content"]]
