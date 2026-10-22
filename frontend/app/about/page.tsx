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
          <p>中文法律咨询助手 · 多角色 Agent 编排 · 可追溯的法条依据</p>
          <div className="about-stack">
            {STACK.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </header>

        <section className="about-section">
          <h2>项目简介</h2>
          <p>
            LilMark 是一个基于多角色 Agent 编排与知识图谱增强检索的中文法律咨询助手，覆盖民法、刑法、劳动法、行政法等领域。系统会先识别问题所属法律领域，再通过向量、BM25 与知识图谱三路检索召回法条，最后由审查角色逐条核验引用，区分「编造条号」与「真实但未召回」，降低模型编造法条的风险。
          </p>
        </section>

        <section className="about-section">
          <h2>技术架构</h2>
          <ul>
            <li>编排层：LangGraph StateGraph，领域路由 + 审查回边（带环反思回路）</li>
            <li>检索层：BM25 + FAISS 向量检索 + Neo4j 图谱二跳扩展，加权 RRF 融合</li>
            <li>生成层：DeepSeek 对话模型，SSE 流式返回每一步</li>
            <li>数据层：国家法律法规数据库语料，24 部法规、3942 条条文、1.7 万刑事案例</li>
            <li>服务层：FastAPI 后端 + Next.js App Router 前端</li>
          </ul>
        </section>

        <section className="about-section">
          <h2>核心特性</h2>
          <ul>
            <li>多角色编排：协调角色识别领域，领域角色生成回答，审查角色核验引用</li>
            <li>图谱增强检索：向量召回与图谱二跳关系互补，沿 APPLIES 关系召回类案与相邻法条</li>
            <li>引用审查：逐条比对全量语料条号，区分「编造」与「真实但未召回」</li>
            <li>可解释性：答案附带法条原文、来源、检索通道与领域标签</li>
          </ul>
        </section>
      </main>
    </AppShell>
  );
}
