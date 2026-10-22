"""国家法律法规数据库（flk.npc.gov.cn）采集客户端。

该站是 Vue 单页应用，接口在改版后换过一代：

- 旧版：``GET /api/?type=flfg&...``（网上博客多为此版，现已下线，
  该路径会回落到 SPA 首页并返回 HTML，容易误判成"反爬"）
- 新版：``POST /law-search/search/list`` 检索、
  ``GET /law-search/download/pc`` 换取 OSS 直链

因此本模块不使用旧接口。全文通过官方 docx 获取，用标准库
``zipfile`` + ``ElementTree`` 解析，不额外引入 python-docx。

只用标准库实现，便于在其他机器上直接跑。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

BASE_URL = "https://flk.npc.gov.cn"
SEARCH_PATH = "/law-search/search/list"
DETAIL_PATH = "/law-search/search/flfgDetails"
DOWNLOAD_PATH = "/law-search/download/pc"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# sxx 字段含义：官方前端用它标记时效性
STATUS_MAP = {
    1: "已废止",
    2: "已被修改",
    3: "现行有效",
}

# 法规性质（flxz）中不属于条文正文、抓来也没有检索价值的类别
SKIP_CATEGORIES = {"修改、废止的决定", "修正案", "有关法律问题和重大问题的决定（部分）"}

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HIGHLIGHT_RE = re.compile(r"<[^>]+>")


class FlkError(RuntimeError):
    """采集过程中的可预期错误（网络、接口结构变化等）"""


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": f"{BASE_URL}/search",
        "Origin": BASE_URL,
    }


def _request(url: str, payload: dict | None = None, timeout: int = 30) -> bytes:
    """发一次请求，带一次退避重试

    Args:
        url: 完整地址
        payload: 非 None 时以 POST JSON 发送
        timeout: 单次超时秒数
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers=_headers(),
                method="POST" if data else "GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.5)
    raise FlkError(f"请求失败 {url}：{last_error}")


def _request_json(url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    raw = _request(url, payload, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        head = raw[:120].decode("utf-8", "ignore")
        raise FlkError(
            f"接口返回的不是 JSON（可能接口已变更）：{url} -> {head!r}"
        ) from exc


def clean_title(raw: str) -> str:
    """去掉检索结果里的 <em class='highlight'> 高亮标签"""
    return _HIGHLIGHT_RE.sub("", raw or "").strip()


def search_laws(
    keyword: str,
    *,
    exact: bool = True,
    page: int = 1,
    page_size: int = 10,
    category_ids: list[int] | None = None,
    timeout: int = 30,
) -> tuple[int, list[dict]]:
    """检索法规

    Args:
        keyword: 检索词，默认按标题匹配
        exact: True=标题精确匹配，False=模糊匹配
        category_ids: flfgCodeId 过滤，例如 [3]=法律、[8]=社会法、[14]=行政法规
        timeout: 超时秒数

    Returns:
        (命中总数, 结果行列表)；行内关键字段为 bbbs/title/sxx/flxz/gbrq/sxrq
    """
    payload = {
        "searchRange": 1,
        "searchType": 1 if exact else 2,
        "searchContent": keyword,
        "pageNum": page,
        "pageSize": page_size,
        "orderByParam": {"order": "-1", "sort": ""},
        "flfgCodeId": category_ids or [],
        "zdjgCodeId": [],
        "sxx": [],
        "gbrq": [],
        "sxrq": [],
        "gbrqYear": [],
        "xgzlSearch": False,
    }
    data = _request_json(f"{BASE_URL}{SEARCH_PATH}", payload, timeout=timeout)
    if data.get("code") not in (None, 200):
        raise FlkError(f"检索接口返回异常：{data.get('msg')}")
    rows = [dict(row, title=clean_title(row.get("title", ""))) for row in data.get("rows") or []]
    return int(data.get("total") or 0), rows


def resolve_law(title: str, *, current_only: bool = True) -> dict | None:
    """按标题定位唯一一部法规

    优先取标题完全一致且现行有效的版本。同名法规常有多个历史版本，
    用 sxx==3 过滤掉已被修改/废止的版本，否则语料里会混进旧条文。

    Args:
        title: 法规全称
        current_only: 只要现行有效版本

    Returns:
        结果行字典；找不到时返回 None
    """
    _, rows = search_laws(title, exact=True, page_size=10)

    def rank(row: dict) -> tuple[int, int]:
        exact = 1 if row.get("title") == title else 0
        current = 1 if row.get("sxx") == 3 else 0
        return (exact, current)

    candidates = [r for r in rows if r.get("flxz") not in SKIP_CATEGORIES]
    if current_only:
        candidates = [r for r in candidates if r.get("sxx") == 3] or candidates
    if not candidates:
        return None
    candidates.sort(key=rank, reverse=True)
    best = candidates[0]
    if best.get("title") != title and best.get("sxx") != 3:
        return None
    return best


def get_detail(bbbs: str) -> dict:
    """获取法规详情（含 ossFile 与章节树）"""
    url = f"{BASE_URL}{DETAIL_PATH}?{urllib.parse.urlencode({'bbbs': bbbs})}"
    data = _request_json(url)
    if data.get("code") not in (None, 200):
        raise FlkError(f"详情接口返回异常：{data.get('msg')}")
    return data.get("data") or {}


def get_download_url(bbbs: str, fmt: str = "docx") -> str:
    """换取带签名的 OSS 直链

    Args:
        bbbs: 法规标识
        fmt: docx / pdf / ofd
    """
    query = urllib.parse.urlencode({"bbbs": bbbs, "format": fmt})
    data = _request_json(f"{BASE_URL}{DOWNLOAD_PATH}?{query}")
    url = (data.get("data") or {}).get("url")
    if not url:
        raise FlkError(f"未取到下载直链：{bbbs}")
    return url


def download_docx(bbbs: str, timeout: int = 90) -> bytes:
    """下载法规 docx 原始字节"""
    url = get_download_url(bbbs, "docx")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read()
    if not content.startswith(b"PK"):
        raise FlkError(f"下载内容不是 docx（bbbs={bbbs}）")
    return content


def parse_docx(data: bytes) -> list[str]:
    """从 docx 字节中提取非空段落文本

    docx 就是 zip 包，正文在 word/document.xml。法规文件只有段落，
    因此不需要 python-docx 的完整能力。

    Args:
        data: docx 原始字节

    Returns:
        按文档顺序排列的段落文本（已去除首尾空白、过滤空段）
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise FlkError("docx 解析失败：文件结构异常") from exc

    root = ET.fromstring(xml)
    paragraphs: list[str] = []
    for para in root.iter(f"{_W_NS}p"):
        text = "".join(node.text or "" for node in para.iter(f"{_W_NS}t"))
        text = text.strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def fetch_law(title: str, *, current_only: bool = True) -> tuple[dict, list[str]]:
    """按标题抓取一部法规的元数据与段落

    Returns:
        (元数据字典, 段落列表)

    Raises:
        FlkError: 未检索到法规或下载解析失败
    """
    row = resolve_law(title, current_only=current_only)
    if not row:
        raise FlkError(f"未检索到法规：{title}")

    bbbs = row["bbbs"]
    detail = get_detail(bbbs)
    paragraphs = parse_docx(download_docx(bbbs))

    metadata = {
        "bbbs": bbbs,
        "law_name": row.get("title") or detail.get("title") or title,
        "category": row.get("flxz", ""),
        "authority": row.get("zdjgName", ""),
        "publish_date": row.get("gbrq", ""),
        "effective_date": row.get("sxrq", ""),
        "status": STATUS_MAP.get(row.get("sxx"), ""),
    }
    return metadata, paragraphs
