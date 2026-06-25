import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listSessions, searchConceptsGlobal } from "../../api/client";
import type { CourseSession, GlobalConceptHit } from "../../types";
import "./CommandPalette.css";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

const NAV_ITEMS = [
  { label: "首页", path: "/", icon: "⌂" },
  { label: "新建知识库", path: "/new", icon: "+" },
];

function sessionHref(session: CourseSession): string {
  if (session.status === "graph_ready" || session.status === "notes_ready") {
    return `/session/${session.session_id}`;
  }
  return `/session/${session.session_id}/pipeline`;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [sessions, setSessions] = useState<CourseSession[]>([]);
  const [concepts, setConcepts] = useState<GlobalConceptHit[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (open) {
      setQuery("");
      setConcepts([]);
      listSessions().then(setSessions).catch(() => {});
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // global concept search (debounced) across every built graph
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) {
      setConcepts([]);
      return;
    }
    const timer = setTimeout(() => {
      searchConceptsGlobal(q, 8).then(setConcepts).catch(() => setConcepts([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [query, open]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (open) document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const lq = query.toLowerCase();
  const filteredSessions = sessions.filter(
    (s) =>
      !s.lecture_title.startsWith("[总图谱] ") &&
      (s.lecture_title.toLowerCase().includes(lq) || s.course_title.toLowerCase().includes(lq)),
  );
  const filteredNav = NAV_ITEMS.filter((n) => n.label.toLowerCase().includes(lq));

  function go(path: string) {
    navigate(path);
    onClose();
  }

  return (
    <div
      className="cmdk-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="命令面板">
        <div className="cmdk-input">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索知识库、知识点、功能…"
            aria-label="搜索"
          />
        </div>

        <div className="cmdk-list">
          {filteredNav.length > 0 && (
            <>
              <div className="cmdk-section-label">导航</div>
              {filteredNav.map((item) => (
                <div
                  key={item.path}
                  className="cmdk-item"
                  onClick={() => go(item.path)}
                  role="option"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && go(item.path)}
                >
                  <span style={{ color: "var(--ink-3)", fontSize: 14 }}>{item.icon}</span>
                  <span>{item.label}</span>
                  <span className="cmdk-item-meta">{item.path}</span>
                </div>
              ))}
            </>
          )}

          {filteredSessions.length > 0 && (
            <>
              <div className="cmdk-section-label">知识库</div>
              {filteredSessions.map((s) => (
                <div
                  key={s.session_id}
                  className="cmdk-item"
                  onClick={() => go(sessionHref(s))}
                  role="option"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && go(sessionHref(s))}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, color: "var(--ink-3)" }}>
                    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
                  </svg>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.lecture_title}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--ink-3)", fontFamily: "var(--font-mono)" }}>
                      {s.course_title}
                    </div>
                  </div>
                  <span className="cmdk-item-meta">{s.status}</span>
                </div>
              ))}
            </>
          )}

          {concepts.length > 0 && (
            <>
              <div className="cmdk-section-label">知识点</div>
              {concepts.map((c) => {
                const target = `/session/${c.session_id}?concept=${encodeURIComponent(c.concept_id)}`;
                return (
                  <div
                    key={`${c.session_id}-${c.concept_id}`}
                    className="cmdk-item"
                    onClick={() => go(target)}
                    role="option"
                    tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && go(target)}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, color: "var(--ink-3)" }}>
                      <circle cx="12" cy="12" r="3" /><circle cx="5" cy="5" r="2" /><circle cx="19" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><path d="m7 7 3 3m4 0 3-3m0 10-3-3m-4 0-3 3" />
                    </svg>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
                      <div style={{ fontSize: 11, color: "var(--ink-3)", fontFamily: "var(--font-mono)" }}>
                        {c.lecture_title} · {c.course_title}
                      </div>
                    </div>
                    <span className="cmdk-item-meta">知识点</span>
                  </div>
                );
              })}
            </>
          )}

          {filteredSessions.length === 0 && filteredNav.length === 0 && concepts.length === 0 && (
            <div className="cmdk-empty">无匹配结果</div>
          )}
        </div>
      </div>
    </div>
  );
}
