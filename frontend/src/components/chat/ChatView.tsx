import { useEffect, useMemo, useState } from "react";
import { clearChat, getChat, getSession, streamChat } from "../../api/client";
import type { ChatCitation, ChatContextItem, ChatDocument, ConceptNode, SubgraphResponse } from "../../types";
import { Markdown } from "../notes/Markdown";
import { Button } from "../primitives/Button";
import { useToast } from "../primitives/Toast";
import "./ChatView.css";

interface ChatViewProps {
  sessionId: string;
  selectedConcept?: ConceptNode | null;
  pendingContext?: ChatContextItem | null;
  onContextConsumed?: () => void;
}

interface LiveAnswer {
  text: string;
  citations: ChatCitation[];
  subgraph: SubgraphResponse | null;
  trace: { type: string; tool?: string; summary: string }[];
}

const PROMPTS = ["用复习的角度解释它", "列出容易混淆的概念", "它和哪些概念相关？"];
const EMPTY_LIVE: LiveAnswer = { text: "", citations: [], subgraph: null, trace: [] };

export function ChatView({ sessionId, selectedConcept, pendingContext, onContextConsumed }: ChatViewProps) {
  const [chat, setChat] = useState<ChatDocument | null>(null);
  const [input, setInput] = useState("");
  const [contexts, setContexts] = useState<ChatContextItem[]>([]);
  const [sending, setSending] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [live, setLive] = useState<LiveAnswer | null>(null);
  const [sourceNames, setSourceNames] = useState<Record<string, string>>({});
  const toast = useToast();

  useEffect(() => {
    getChat(sessionId)
      .then(setChat)
      .catch(() => setChat({ chat_id: "", session_id: sessionId, messages: [], updated_at: "" }));
  }, [sessionId]);

  // map source_id -> filename so citations can show WHERE (file · page), not content
  useEffect(() => {
    getSession(sessionId)
      .then((s) => setSourceNames(Object.fromEntries(s.source_files.map((f) => [f.source_id, f.filename]))))
      .catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    if (!pendingContext) return;
    addContext(pendingContext);
    if (!input.trim()) setInput(defaultPromptForContext(pendingContext));
    onContextConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingContext]);

  const conceptContext = useMemo(
    () => (selectedConcept ? contextFromConcept(selectedConcept) : null),
    [selectedConcept],
  );

  function addContext(context: ChatContextItem) {
    setContexts((current) => {
      const key = contextKey(context);
      if (current.some((item) => contextKey(item) === key)) return current;
      return [...current, context];
    });
  }

  function removeContext(index: number) {
    setContexts((current) => current.filter((_, i) => i !== index));
  }

  async function handleSend() {
    const message = input.trim() || (contexts.length ? "请解释当前上下文。" : "");
    if (!message || sending) return;
    setSending(true);

    const sentContexts = contexts;
    const userMessage = {
      message_id: `tmp-${Date.now()}`,
      role: "user",
      content: message,
      context_items: sentContexts,
      created_at: new Date().toISOString(),
    };
    setChat((c) => ({
      chat_id: c?.chat_id ?? "",
      session_id: sessionId,
      messages: [...(c?.messages ?? []), userMessage],
      updated_at: "",
    }));
    setInput("");
    setContexts([]);
    setLive({ ...EMPTY_LIVE });

    try {
      await streamChat(
        { session_id: sessionId, message, context_items: sentContexts },
        (event) => {
          const data = event.data as Record<string, unknown>;
          if (event.type === "token") {
            setLive((l) => ({ ...(l ?? EMPTY_LIVE), text: (l?.text ?? "") + String(data.text ?? "") }));
          } else if (event.type === "citation") {
            setLive((l) => ({ ...(l ?? EMPTY_LIVE), citations: [...(l?.citations ?? []), data as unknown as ChatCitation] }));
          } else if (event.type === "subgraph") {
            setLive((l) => ({ ...(l ?? EMPTY_LIVE), subgraph: data as unknown as SubgraphResponse }));
          } else if (event.type === "tool_call" || event.type === "retrieval") {
            setLive((l) => ({
              ...(l ?? EMPTY_LIVE),
              trace: [...(l?.trace ?? []), { type: event.type, tool: String(data.tool ?? ""), summary: JSON.stringify(data) }],
            }));
          } else if (event.type === "error") {
            toast(`对话失败：${String(data.message ?? "")}`, "error");
          }
        },
      );
      const fresh = await getChat(sessionId);
      setChat(fresh);
      setLive(null);
    } catch (error) {
      toast(error instanceof Error ? `对话失败：${error.message}` : "对话失败", "error");
      setLive(null);
    } finally {
      setSending(false);
    }
  }

  async function handleClear() {
    setClearing(true);
    try {
      const fresh = await clearChat(sessionId);
      setChat(fresh);
      setContexts([]);
      setInput("");
    } catch {
      toast("清空失败", "error");
    } finally {
      setClearing(false);
    }
  }

  function applyPrompt(prompt: string) {
    setInput(prompt);
    if (conceptContext) addContext(conceptContext);
  }

  const messages = chat?.messages ?? [];

  return (
    <div className="chat-view">
      <div className="chat-header">
        <p className="chat-subtitle">基于图谱检索作答 · 回答可溯源</p>
        <div className="chat-actions">
          <Button variant="ghost" size="sm" onClick={handleClear} loading={clearing}>
            清空
          </Button>
        </div>
      </div>

      {conceptContext && (
        <div className="chat-context-card">
          <div>
            <div className="chat-context-label">当前图谱选中</div>
            <div className="chat-context-title">{selectedConcept?.name}</div>
          </div>
          <button
            className="chat-context-btn"
            type="button"
            onClick={() => {
              addContext(conceptContext);
              if (!input.trim()) setInput("请解释这个知识点，并指出它和相邻概念的关系。");
            }}
          >
            询问这个知识点
          </button>
        </div>
      )}

      {messages.length === 0 && !live ? (
        <div className="chat-empty">
          <p className="chat-empty-title">开始一个和资料图谱有关的问题</p>
          <div className="chat-prompt-list">
            {PROMPTS.map((prompt) => (
              <button key={prompt} type="button" onClick={() => applyPrompt(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="chat-message-list">
          {messages.map((message) => (
            <div key={message.message_id} className={`chat-message chat-message-${message.role}`}>
              <div className="chat-message-role">{message.role === "user" ? "你" : "助手"}</div>
              <div className="chat-message-body">
                {message.role === "assistant" ? <Markdown>{message.content}</Markdown> : message.content}
              </div>
              {message.role === "assistant" && message.citations && message.citations.length > 0 && (
                <CitationList citations={message.citations} sourceNames={sourceNames} />
              )}
              {message.context_items.length > 0 && (
                <div className="chat-message-contexts">
                  {message.context_items.map((item, index) => (
                    <span key={`${item.label}-${index}`}>{item.label || contextTypeLabel(item.context_type)}</span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {live && (
            <div className="chat-message chat-message-assistant">
              <div className="chat-message-role">助手{sending ? " · 生成中…" : ""}</div>
              <div className="chat-message-body">
                {live.text ? <Markdown>{live.text}</Markdown> : <span className="chat-typing">检索中…</span>}
              </div>
              {live.citations.length > 0 && <CitationList citations={live.citations} sourceNames={sourceNames} />}
              {live.subgraph && live.subgraph.nodes.length > 0 && <SubgraphSummary subgraph={live.subgraph} />}
            </div>
          )}
        </div>
      )}

      {contexts.length > 0 && (
        <div className="chat-context-tray">
          {contexts.map((context, index) => (
            <button
              key={`${contextKey(context)}-${index}`}
              type="button"
              className="chat-context-chip"
              onClick={() => removeContext(index)}
              title="点击移除此上下文"
            >
              {context.label || contextTypeLabel(context.context_type)}
              <span>×</span>
            </button>
          ))}
        </div>
      )}

      <div className="chat-composer">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="询问当前资料、选中知识点…（⌘/Ctrl + Enter 发送）"
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              void handleSend();
            }
          }}
        />
        <Button onClick={handleSend} loading={sending}>
          发送
        </Button>
      </div>
    </div>
  );
}

function CitationList({ citations, sourceNames }: { citations: ChatCitation[]; sourceNames: Record<string, string> }) {
  // Show WHERE a citation comes from (file · page, or concept), not its content.
  function label(c: ChatCitation): { where: string; tag: string } {
    if (c.kind === "concept") return { where: c.title || c.ref_id, tag: "概念" };
    const file = (c.source_id && sourceNames[c.source_id]) || "原文";
    return { where: file, tag: c.locator || "" };
  }
  return (
    <div className="chat-citations">
      <div className="chat-citations-title">引用 · {citations.length}</div>
      {citations.map((c) => {
        const { where, tag } = label(c);
        return (
          <div className="chat-citation" key={`${c.kind}-${c.ref_id}-${c.index}`} title={c.snippet || where}>
            <span className="chat-citation-index">[{c.index}]</span>
            <span className="chat-citation-title-line">{where}</span>
            {tag && <span className="chat-citation-loc">{tag}</span>}
          </div>
        );
      })}
    </div>
  );
}

function SubgraphSummary({ subgraph }: { subgraph: SubgraphResponse }) {
  return (
    <div className="chat-subgraph">
      <div className="chat-citations-title">
        命中子图 · {subgraph.nodes.length} 概念 / {subgraph.edges.length} 关系
      </div>
      <div className="chat-subgraph-nodes">
        {subgraph.nodes.slice(0, 12).map((n) => (
          <span className="chat-subgraph-node" key={n.id}>{n.label}</span>
        ))}
      </div>
    </div>
  );
}

function contextFromConcept(concept: ConceptNode): ChatContextItem {
  const parts = [
    concept.definition && `定义：${concept.definition}`,
    concept.summary && `摘要：${concept.summary}`,
    concept.key_points.length > 0 && `要点：${concept.key_points.join("；")}`,
    concept.prerequisites.length > 0 && `前置：${concept.prerequisites.join("；")}`,
    concept.applications.length > 0 && `应用：${concept.applications.join("；")}`,
    `重要性：${Math.round(concept.importance_score * 100)}%`,
  ].filter(Boolean);
  return {
    context_type: "concept",
    label: `知识点：${concept.name}`,
    concept_id: concept.concept_id,
    content: parts.join("\n"),
  };
}

function defaultPromptForContext(context: ChatContextItem): string {
  if (context.context_type === "note_selection") return "请解释这段笔记，并补充我应该如何复习。";
  if (context.context_type === "exam_selection") return "请讲解这道题的考点和解题思路。";
  if (context.context_type === "concept") return "请解释这个知识点。";
  return "请解释这段内容。";
}

function contextKey(context: ChatContextItem): string {
  return `${context.context_type}:${context.concept_id ?? ""}:${context.label}:${context.content.slice(0, 80)}`;
}

function contextTypeLabel(type: string): string {
  return (
    {
      concept: "知识点",
      note_selection: "笔记选区",
      exam_selection: "试卷选区",
      selection: "选区",
    }[type] ?? type
  );
}
