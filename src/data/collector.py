"""数据采集模块：加载法条与案例语料

真实法条语料来自国家法律法规数据库，由 ``scripts/fetch_laws.py`` 抓取，
落盘到 ``data/processed/laws.json``。本模块的职责是**读取**语料，
并保留内置示例数据作为兜底——这样在没联网、没跑过抓取的机器上，
检索链路依然能跑通（只是效果会差很多）。

注意：原 ``download_cail_dataset`` 指向的 CAIL2018 下载地址已失效，
保留这个死链接只会让人以为数据层是通的，故已移除，改为指向抓取脚本。
"""

import json
import urllib.request
from pathlib import Path

from src.config import get_project_root

RAW_DATA_DIR = get_project_root() / "data" / "raw"
PROCESSED_DIR = get_project_root() / "data" / "processed"


def _read_json(path: Path):
    """读 JSON，损坏或为空时返回 None，交给调用方回退"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_laws(domain: str | None = None) -> list[dict]:
    """加载法条语料

    Args:
        domain: 只取某个领域的条文（labor_law / civil_law / criminal_law /
            admin_law / general），None 表示全部

    Returns:
        条文列表；真实语料不存在时回退到内置示例
    """
    data = _read_json(PROCESSED_DIR / "laws.json")
    if data:
        if domain:
            subset = [item for item in data if item.get("domain") == domain]
            if subset:
                return subset
        else:
            return data
    return load_sample_laws()


def load_cases() -> list[dict]:
    """加载案例语料

    只返回 ``data/processed/cases.json`` 中的真实案例。内置的 3 条示例案例
    （CASE001 等）是编造的，一旦进入检索语料就会在结果里冒充真实判例，
    因此**默认不参与检索**——需要演示图谱关系时请显式调用
    ``load_sample_cases()``。
    """
    return _read_json(PROCESSED_DIR / "cases.json") or []


def corpus_stats() -> dict:
    """统计当前语料规模，用于启动日志与评测报告

    Returns:
        含 laws / articles / laws_loaded / source 的字典
    """
    data = _read_json(PROCESSED_DIR / "laws.json")
    if not data:
        sample = load_sample_laws()
        return {
            "source": "sample",
            "laws": len({item["law_name"] for item in sample}),
            "articles": len(sample),
            "chars": sum(len(item["content"]) for item in sample),
        }
    return {
        "source": "flk.npc.gov.cn",
        "laws": len({item["law_name"] for item in data}),
        "articles": len(data),
        "chars": sum(len(item.get("content", "")) for item in data),
    }


def download_cail_dataset(save_path: Path | None = None) -> Path:
    """已废弃：CAIL2018 下载地址失效

    法条语料请用 ``python scripts/fetch_laws.py --all``。
    案例语料暂无稳定的公开批量来源，见 docs/onboarding 中的数据源说明。
    """
    raise NotImplementedError(
        "CAIL 数据集下载地址已失效。法条语料请运行 scripts/fetch_laws.py；"
        "案例来源说明见 docs/onboarding/数据源与扩充方案.md"
    )


def load_sample_laws() -> list[dict]:
    """加载内置的示例法律条文数据

    在没有完整数据集时，使用内置示例数据进行开发测试。
    """
    sample_data = [
        {
            "law_name": "中华人民共和国刑法",
            "chapter": "第二编 分则",
            "article_number": "第二百三十二条",
            "content": "故意杀人的，处死刑、无期徒刑或者十年以上有期徒刑；情节较轻的，处三年以上十年以下有期徒刑。",
        },
        {
            "law_name": "中华人民共和国刑法",
            "chapter": "第二编 分则",
            "article_number": "第二百六十四条",
            "content": "盗窃公私财物，数额较大的，或者多次盗窃、入户盗窃、携带凶器盗窃、扒窃的，处三年以下有期徒刑、拘役或者管制，并处或者单处罚金；数额巨大或者有其他严重情节的，处三年以上十年以下有期徒刑，并处罚金；数额特别巨大或者有其他特别严重情节的，处十年以上有期徒刑或者无期徒刑，并处罚金或者没收财产。",
        },
        {
            "law_name": "中华人民共和国劳动合同法",
            "chapter": "第一章 总则",
            "article_number": "第十条",
            "content": "建立劳动关系，应当订立书面劳动合同。已建立劳动关系，未同时订立书面劳动合同的，应当自用工之日起一个月内订立书面劳动合同。",
        },
        {
            "law_name": "中华人民共和国劳动合同法",
            "chapter": "第七章 法律责任",
            "article_number": "第八十二条",
            "content": "用人单位自用工之日起超过一个月不满一年未与劳动者订立书面劳动合同的，应当向劳动者每月支付二倍的工资。",
        },
        {
            "law_name": "中华人民共和国民法典",
            "chapter": "第一编 总则",
            "article_number": "第一百一十条",
            "content": "自然人享有生命权、身体权、健康权、姓名权、肖像权、名誉权、荣誉权、隐私权、婚姻自主权等权利。法人、非法人组织享有名称权、名誉权和荣誉权。",
        },
    ]
    return sample_data


def load_sample_cases() -> list[dict]:
    """加载内置的示例案例数据"""
    sample_data = [
        {
            "case_id": "CASE001",
            "case_type": "刑事",
            "crime": "故意杀人",
            "fact": "被告人李某因家庭纠纷持刀将被害人王某刺死",
            "judgment": "判处无期徒刑",
            "applicable_law": "刑法第二百三十二条",
        },
        {
            "case_id": "CASE002",
            "case_type": "刑事",
            "crime": "盗窃",
            "fact": "被告人张某多次入户盗窃，盗窃金额累计5万元",
            "judgment": "判处有期徒刑三年，并处罚金",
            "applicable_law": "刑法第二百六十四条",
        },
        {
            "case_id": "CASE003",
            "case_type": "劳动争议",
            "crime": "",
            "fact": "原告入职被告公司6个月，被告未签订书面劳动合同",
            "judgment": "被告支付双倍工资差额",
            "applicable_law": "劳动合同法第八十二条",
        },
    ]
    return sample_data


def save_data(data: list[dict], filename: str) -> Path:
    """保存数据到processed目录"""
    processed_dir = get_project_root() / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    save_path = processed_dir / filename
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return save_path