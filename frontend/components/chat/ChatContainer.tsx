"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { ChatMessage, SSEEvent, sendChat, parseSSEStream, SourceDetail } from "@/lib/api";
import { MessageList } from "./MessageList";
import { AssistantMessage } from "./AssistantMessage";
import { InputArea } from "./InputArea";
import { AgentTimeline, type AgentTrace } from "./AgentTimeline";
import { AppShell } from "@/components/shell/AppShell";

const SUGGESTIONS = [
  "试用期解除需要满足哪些条件？",
  "劳动合同法第 39 条如何适用？",
  "公司拖欠工资可以主张哪些赔偿？",
];

/** 把消息列表折叠成后端需要的成对 {question, answer} 历史 */
function buildHistory(
  messages: ChatMessage[]
): { question: string; answer: string }[] {
  const history: { question: string; answer: string }[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      history.push({ question: m.content, answer: "" });
    } else if (m.role === "assistant" && history.length > 0) {
      history[history.length - 1].answer = m.content;
    }
  }
  return history.filter((h) => h.question.trim() !== "");
}

export function ChatContainer() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [pendingDomain, setPendingDomain] = useState("");
  const [pendingDomainZh, setPendingDomainZh] = useState("");
  const [pendingSources, setPendingSources] = useState<string[]>([]);
  const [pendingSourcesDetail, setPendingSourcesDetail] = useState<SourceDetail[]>([]);
  const [reviewState, setReviewState] = useState<{
    passed: boolean;
    score: number;
    issues: string[];
  } | null>(null);
  const [trace, setTrace] = useState<AgentTrace>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const conversationIdRef = useRef<string | undefined>(undefined);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingAnswer]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const handleSend = useCallback(async (question: string) => {
    const history = buildHistory(messagesRef.current);
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setIsLoading(true);
    setCurrentStep("intent");
    setStreamingAnswer("");
    setPendingSources([]);
    setPendingSourcesDetail([]);
    setReviewState(null);
    setTrace({ currentStep: "intent" });

    let lastAnswer = "";
    let domain = "";
    let domainZh = "";
    let collectedSources: string[] = [];
    let collectedSourcesDetail: SourceDetail[] = [];
    let lastElapsedMs = 0;

    try {
      const response = await sendChat(question, history, conversationIdRef.current);
      const eventStream = parseSSEStream(response);

      for await (const event of eventStream) {
        if (event.type === "step") {
          const step = event.data;
          const interval =
            step.elapsed_ms != null ? step.elapsed_ms - lastElapsedMs : null;
          if (step.elapsed_ms != null) lastElapsedMs = step.elapsed_ms;
          setCurrentStep(step.step);
          setTrace((prev) => {
            const next: AgentTrace = { ...prev, currentStep: step.step };
            if (interval != null) {
              next.timings = { ...(prev.timings ?? {}), [step.step]: interval };
            }
            if (step.step === "intent") {
              next.domain = step.domain ?? "general";
              next.domainZh = step.domain_zh ?? "通用";
              next.intent = step.intent ?? "";
              next.keywords = step.keywords ?? [];
            }
            if (step.step === "retrieve") {
              next.sourcesCount = step.sources_count ?? 0;
              next.retrievedBy = step.retrieved_by ?? [];
            }
            if (step.step === "generate") {
              next.attempt = step.attempt ?? 1;
            }
            if (step.step === "review") {
              next.review = {
                passed: Boolean(step.passed),
                score: step.score ?? 0,
                mode: step.mode ?? "rule",
                issues: step.issues ?? [],
              };
              next.unretrieved = step.unretrieved ?? [];
            }
            return next;
          });

          if (step.step === "intent") {
            domain = step.domain ?? "general";
            domainZh = step.domain_zh ?? "通用";
            setPendingDomain(domain);
            setPendingDomainZh(domainZh);
          }

          if (step.step === "generate" && step.answer) {
            lastAnswer = step.answer;
            setStreamingAnswer(step.answer);
          }

          if (step.step === "review") {
            setReviewState({
              passed: Boolean(step.passed),
              score: step.score ?? 0,
              issues: step.issues ?? [],
            });
          }
        } else if (event.type === "done") {
          collectedSources = event.data.sources;
          collectedSourcesDetail = event.data.sources_detail ?? [];
          if (event.data.conversation_id) {
            conversationIdRef.current = event.data.conversation_id;
          }
          setPendingSources(collectedSources);
          setPendingSourcesDetail(collectedSourcesDetail);
        } else if (event.type === "error") {
          lastAnswer = `错误: ${event.data.message}`;
          setStreamingAnswer(lastAnswer);
        }
      }

      if (lastAnswer) {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: lastAnswer,
            domain,
            domain_zh: domainZh,
            sources: collectedSources,
            sources_detail: collectedSourcesDetail,
          },
        ]);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "请求失败，请检查后端服务是否运行。" },
      ]);
    } finally {
      setIsLoading(false);
      setCurrentStep(null);
      setStreamingAnswer("");
      setTrace((prev) => ({ ...prev, currentStep: null }));
    }
  }, []);

  return (
    <AppShell active="chat" fill>
      <div className="chat-panel">
        <div className="chat-scroll">
          <div className="chat-inner">
            <AgentTimeline trace={trace} />

            {reviewState && !reviewState.passed && reviewState.issues.length > 0 && (
              <div className="review-alert">
                <strong>审查未通过 · 置信度 {reviewState.score.toFixed(2)}</strong>
                {reviewState.issues.map((issue) => (
                  <div key={issue}>· {issue}</div>
                ))}
              </div>
            )}

            {messages.length === 0 && !isLoading && (
              <section className="chat-hero">
                <div className="chat-seal">律</div>
                <h1>让每一个结论，都有法条可依。</h1>
                <span className="hero-rule" />
                <p>
                  LilMark 法律咨询助手 · 多角色 Agent 编排 · 知识图谱增强检索
                  <br />
                  覆盖民法、刑法、劳动法、行政法四大领域
                </p>
                <div className="chat-suggestions">
                  {SUGGESTIONS.map((question) => (
                    <button
                      className="chat-suggestion"
                      key={question}
                      onClick={() => handleSend(question)}
                      type="button"
                    >
                      {question}
                    </button>
                  ))}
                </div>
              </section>
            )}

            <MessageList messages={messages} />

            {streamingAnswer && (
              <AssistantMessage
                content={streamingAnswer}
                domain={pendingDomain}
                domain_zh={pendingDomainZh}
              sources={pendingSources}
              sourcesDetail={pendingSourcesDetail}
              streaming
              />
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        <footer className="chat-footer">
          <div className="chat-footer-inner">
            <InputArea onSend={handleSend} disabled={isLoading} />
            <div className="chat-hint">
              回答基于国家法律法规数据库语料 · 仅供研究参考，不构成正式法律意见
            </div>
          </div>
        </footer>
      </div>
    </AppShell>
  );
}
