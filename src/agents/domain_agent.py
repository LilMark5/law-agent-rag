"""专业 Agent 基类：可复用的领域问答 Agent"""

from __future__ import annotations

import yaml
from openai import OpenAI

from src.config import get_project_root, load_config
from src.retrieval.fusion import hybrid_search


CASE_SECTION_HEADER = (
    "【类案参考】以下为真实裁判文书中的个案，仅用于判断同类案件的裁判倾向，"
    "不得把个案判决当作量刑标准或普遍结论："
)


def build_context_blocks(
    context_docs: list, case_limit: int = 2, fact_chars: int = 400
) -> str:
    """把检索结果排成「法律条文 / 类案参考」两段，编号连续

    为什么必须分区：法条是裁判依据，案例只是倾向参考。混在一段里时，
    模型很容易把个案刑期说成普遍标准（"故意伤害致轻伤判 6 个月"），
    而这种表述在法律咨询里是硬伤。

    为什么必须截断：CAIL 的事实最长近 4 万字，两条原文就能吃掉半个上下文窗口。
    """
    laws = [doc for doc in context_docs if (doc.metadata or {}).get("source_type") != "case"]
    cases = [doc for doc in context_docs if (doc.metadata or {}).get("source_type") == "case"]

    lines: list[str] = []
    index = 0

    if laws:
        lines.append("【法律条文】")
        for doc in laws:
            index += 1
            lines.append(f"[{index}] {doc.page_content}")

    if cases:
        if lines:
            lines.append("")
        lines.append(CASE_SECTION_HEADER)
        for doc in cases[:case_limit]:
            meta = doc.metadata or {}
            index += 1
            fact = (meta.get("fact") or doc.page_content or "").strip()
            if len(fact) > fact_chars:
                fact = fact[:fact_chars] + "…"
            lines.append(
                f"[{index}] 案例 {meta.get('case_id', '')}"
                f"（{meta.get('crime') or '罪名未标注'}）：{fact} "
                f"判决：{meta.get('judgment') or '刑期未标注'}"
            )

    return "\n".join(lines) if lines else "（本轮未检索到相关资料）"


def build_sources(context_docs: list) -> list[str]:
    """从检索文档提取可展示的引用来源（去重保序）"""
    sources: list[str] = []
    for doc in context_docs:
        meta = doc.metadata or {}
        if meta.get("source_type") == "law":
            label = f"{meta.get('law_name', '')} {meta.get('article_number', '')}".strip()
        elif meta.get("source_type") == "case":
            label = f"案例 {meta.get('case_id', '')} ({meta.get('crime', '')})"
        else:
            continue
        if label:
            sources.append(label)
    return list(dict.fromkeys(sources))


def build_sources_detail(context_docs: list, fact_chars: int = 300) -> list[dict]:
    """从检索文档提取结构化溯源信息，供前端渲染可展开的来源卡片

    与 build_sources 的区别：build_sources 把 metadata 压成一行字符串，
    这里保留法条（法名/条号/章节）与类案（案号/罪名/事实/判决）的完整结构，
    并带出每条命中的检索通道（retrieved_by），让溯源从"一行字"变成"可点开的证据"。
    """
    detail: list[dict] = []
    for doc in context_docs:
        meta = doc.metadata or {}
        source_type = meta.get("source_type")
        if source_type == "law":
            detail.append(
                {
                    "type": "law",
                    "law_name": meta.get("law_name", ""),
                    "article_number": meta.get("article_number", ""),
                    "chapter_path": meta.get("chapter_path", "")
                    or meta.get("chapter", ""),
                    "retrieved_by": meta.get("retrieved_by", "vector"),
                }
            )
        elif source_type == "case":
            fact = (meta.get("fact") or "").strip()
            judgment = (meta.get("judgment") or "").strip()
            if len(fact) > fact_chars:
                fact = fact[:fact_chars] + "…"
            detail.append(
                {
                    "type": "case",
                    "case_id": meta.get("case_id", ""),
                    "crime": meta.get("crime", ""),
                    "fact": fact,
                    "judgment": judgment,
                    "retrieved_by": meta.get("retrieved_by", "graph"),
                }
            )
    return detail


class DomainAgent:
    """领域专业 Agent

    根据领域配置加载 system prompt，结合检索结果生成回答。
    检索结果可由调用方传入（避免重复检索），也可由本类自行检索。
    """

    def __init__(self, domain: str):
        self.domain = domain
        self.config_data = self._load_domain_config(domain)
        self.system_prompt = self.config_data["system_prompt"]

    def _load_domain_config(self, domain: str) -> dict:
        config_path = get_project_root() / "src" / "agents" / "config" / f"{domain}.yaml"
        if not config_path.exists():
            config_path = get_project_root() / "src" / "agents" / "config" / "general.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def answer(
        self,
        question: str,
        intent: str = "",
        keywords: list[str] | None = None,
        context_docs: list | None = None,
        review_feedback: str | None = None,
        history: list[dict] | None = None,
    ) -> dict:
        """生成领域专业回答

        Args:
            question: 用户问题
            intent: 意图标签
            keywords: 关键词列表
            context_docs: 已检索到的文档；为 None 时本方法自行检索
            review_feedback: 审查未通过时的问题清单，用于二次生成
            history: 多轮对话历史，每项含 question / answer

        Returns:
            包含 answer / sources / domain / context_docs 的字典
        """
        config = load_config()

        # 1. 检索（调用方已检索则直接复用，避免同一问题跑两遍）
        if context_docs is None:
            context_docs = hybrid_search(question)

        prompt_cfg = config.get("prompt") or {}
        context_text = build_context_blocks(
            context_docs,
            case_limit=int(prompt_cfg.get("case_context_limit", 2)),
            fact_chars=int(prompt_cfg.get("case_fact_chars", 400)),
        )
        has_cases = any(
            (doc.metadata or {}).get("source_type") == "case" for doc in context_docs
        )

        # 2. 组装 user message
        sections = []
        if history:
            recent = "\n".join(
                f"问：{item.get('question', '')}\n答：{item.get('answer', '')}"
                for item in history[-3:]
            )
            sections.append(f"此前的对话（供理解指代）：\n{recent}")
        sections.extend(
            [
                f"参考资料：\n{context_text}",
                f"用户问题：{question}",
                f"问题意图：{intent}",
                f"关键词：{', '.join(keywords or [])}",
            ]
        )
        if review_feedback:
            sections.append(
                "上一版回答存在以下问题，请针对性修正后重新作答：\n" + review_feedback
            )
        sections.append("请严格依据参考资料并运用专业判断给出回答。")
        if has_cases:
            sections.append(
                "引用类案时须写明案号，并说明它作为类案参考的意义；"
                "不得把个案判决表述为量刑标准或必然结果。"
            )
        user_message = "\n\n".join(sections)

        # 3. 调用 LLM
        api_key = (config.get("llm") or {}).get("api_key")
        if not api_key:
            raise RuntimeError(
                "未配置 DEEPSEEK_API_KEY，无法生成回答。"
                "请在项目根目录 .env 中填入该变量后重启后端"
                "（运行 python scripts/doctor.py --check-api 可先验证 Key 是否有效）。"
            )

        client = OpenAI(
            api_key=api_key,
            base_url=config["llm"]["base_url"],
        )

        response = client.chat.completions.create(
            model=config["llm"]["model"],
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=config["llm"]["temperature"],
            max_tokens=config["llm"]["max_tokens"],
        )

        answer = response.choices[0].message.content or ""

        # 推理模型（如 deepseek-v4-pro）会先消耗思考 token，预算不足时 content 为空，
        # 表现为"生成成功但答案是空字符串"，审查随即判不通过，很难从现象定位。
        if not answer.strip():
            finish_reason = response.choices[0].finish_reason
            if finish_reason == "length":
                raise RuntimeError(
                    f"模型 {config['llm']['model']} 输出被 max_tokens="
                    f"{config['llm']['max_tokens']} 截断，正文为空。"
                    "推理模型会先消耗思考 token，请调大 config/settings.yaml 的 "
                    "llm.max_tokens（建议 >= 4096），或改用非推理模型 deepseek-chat。"
                )
            raise RuntimeError(
                f"模型返回空内容（finish_reason={finish_reason}），请检查模型名称是否可用"
            )

        return {
            "answer": answer,
            "sources": build_sources(context_docs),
            "domain": self.domain,
            "context_docs": context_docs,
        }
