/** API 客户端及 SSE 解析 */

export interface SourceDetail {
  type: "law" | "case";
  law_name?: string;
  article_number?: string;
  chapter_path?: string;
  case_id?: string;
  crime?: string;
  fact?: string;
  judgment?: string;
  retrieved_by?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  domain?: string;
  domain_zh?: string;
  sources?: string[];
  sources_detail?: SourceDetail[];
}

export interface StepEvent {
  step: "intent" | "retrieve" | "generate" | "review";
  status: "completed" | "pending" | "passed" | "failed";
  domain?: string;
  domain_zh?: string;
  intent?: string;
  keywords?: string[];
  sources_count?: number;
  retrieved_by?: string[];
  answer?: string;
  attempt?: number;
  passed?: boolean;
  score?: number;
  issues?: string[];
  unretrieved?: string[];
  mode?: string;
  elapsed_ms?: number;
}

export interface DoneEvent {
  sources: string[];
  sources_detail?: SourceDetail[];
  review?: {
    passed?: boolean;
    score?: number;
    mode?: string;
  };
  conversation_id?: string;
}

export interface ErrorEvent {
  message: string;
}

export type SSEEvent =
  | { type: "step"; data: StepEvent }
  | { type: "done"; data: DoneEvent }
  | { type: "error"; data: ErrorEvent };

export async function* parseSSEStream(
  response: Response
): AsyncGenerator<SSEEvent, void, unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";
  let currentEventType = "step";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEventType = line.slice(6).trim();
        continue;
      }
      if (line.startsWith("data:")) {
        const dataStr = line.slice(5).trim();
        try {
          const data = JSON.parse(dataStr);
          yield { type: currentEventType, data } as SSEEvent;
        } catch {
          // ignore parse errors
        }
      }
    }
  }
}

export async function sendChat(
  question: string,
  history: { question: string; answer: string }[],
  conversationId?: string
): Promise<Response> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history, conversation_id: conversationId }),
  });
  return response;
}

// ---------------------------------------------------------------------------
// 知识图谱接口
// ---------------------------------------------------------------------------

export interface GraphStats {
  laws: number;
  cases: number;
  relations: number;
  available: boolean;
}

export interface SubgraphNode {
  id: string;
  type: "law" | "case";
  label: string;
  law_name?: string;
  chapter?: string;
  content?: string;
  crime?: string;
  judgment?: string;
  fact?: string;
}

export interface SubgraphEdge {
  from: string;
  to: string;
  label: string;
}

export interface Subgraph {
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  available: boolean;
  article: string;
}

export async function fetchGraphStats(): Promise<GraphStats> {
  const res = await fetch("/api/graph/stats");
  if (!res.ok) throw new Error(`graph stats ${res.status}`);
  return res.json();
}

export async function fetchSubgraph(article: string, law?: string): Promise<Subgraph> {
  const params = new URLSearchParams({ article });
  if (law) params.set("law", law);
  const res = await fetch(`/api/graph/subgraph?${params.toString()}`);
  if (!res.ok) throw new Error(`graph subgraph ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// 运维面板
// ---------------------------------------------------------------------------

export interface SystemStats {
  graph: {
    laws: number;
    cases: number;
    relations: number;
    lawBooks: number;
    available: boolean;
  };
  topLawBooks: { name: string; articles: number }[];
  vectorIndex: { exists: boolean; sizeMb: number };
  llm: { configured: boolean; model: string };
  embedding: { configured: boolean; model: string; dimension: number };
  review: { enabled: boolean; mode: string; max_retry: number };
  retrieval: { fusion: string; finalTopK: number; graphHop: number };
}

export async function fetchSystemStats(): Promise<SystemStats> {
  const res = await fetch("/api/system/stats");
  if (!res.ok) throw new Error(`system stats ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// 历史会话
// ---------------------------------------------------------------------------

export interface HistorySummary {
  id: string;
  title: string;
  turns: number;
  updated_at: number;
}

export interface HistoryTurn {
  question: string;
  answer: string;
  domain: string;
  domain_zh: string;
}

export interface HistorySession {
  id: string;
  title: string;
  turns: HistoryTurn[];
  updated_at: number;
}

export async function fetchHistoryList(): Promise<HistorySummary[]> {
  const res = await fetch("/api/history");
  if (!res.ok) throw new Error(`history ${res.status}`);
  return res.json();
}

export async function fetchHistoryDetail(id: string): Promise<HistorySession> {
  const res = await fetch(`/api/history/${id}`);
  if (!res.ok) throw new Error(`history detail ${res.status}`);
  return res.json();
}
