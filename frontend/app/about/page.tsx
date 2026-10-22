import { AppShell } from "@/components/shell/AppShell";

const STACK = [
  "LangGraph",
  "FastAPI · SSE",
  "Neo4j",
  "FAISS",
  "BM25",
  "DeepSeek",
  "text-embedding-v3",
  "Next.js",
];

export default function AboutPage() {
  return (
    <AppShell active="about">
      <main className="about-main">
        <header className="about-hero">
          <div className="eyebrow">关于</div>
          <h1>LilMark</h1>
          <p>中文法律咨询助手 · 多智能体编排 · 可追溯的法条依据</p>
          <div className="about-stack">
            {STACK.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </header>

        <section className="about-section">
          <h2>项目简介</h2>
          <p>
            LilMark 是一个基于多智能体编排与 GraphRAG 的中文法律咨询助手，覆盖民法、刑法、劳动法、行政法等领域。系统会先识别问题所属法律领域，再通过向量、BM25 与知识图谱三路检索召回法条，最后由审查代理逐条核验引用，降低模型编造法条的风险。
          </p>
        </section>

        <section className="about-section">
          <h2>技术架构</h2>
          <ul>
            <li>编排层：LangGraph StateGraph，领域路由 + 审查回边</li>
            <li>检索层：BM25 + FAISS 向量检索 + Neo4j 图谱，RRF 融合</li>
            <li>生成层：DeepSeek 对话模型，SSE 流式返回推理步骤</li>
            <li>数据层：国家法律法规数据库语料，24 部法规、3942 条条文</li>
            <li>服务层：FastAPI 后端 + Next.js App Router 前端</li>
          </ul>
        </section>

        <section className="about-section">
          <h2>核心特性</h2>
          <ul>
            <li>多智能体协作：协调代理、领域代理、审查代理分工完成回答</li>
            <li>GraphRAG：向量召回与图谱关系互补，提升跨法条问题的召回率</li>
            <li>引用审查：逐条比对全量语料条号，区分幻觉与漏召回</li>
            <li>可解释性：答案附带法条原文、来源与领域标签</li>
          </ul>
        </section>
      </main>
    </AppShell>
  );
}
