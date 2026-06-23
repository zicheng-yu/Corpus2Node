import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listSessions } from "../../api/client";
import type { CourseSession } from "../../types";
import "./CommandPalette.css";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

const NAV_ITEMS = [
  { label: "首页", path: "/", icon: "⌂" },
  { label: "新建课程", path: "/new", icon: "+" },
];

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [sessions, setSessions] = useState<CourseSession[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (open) {
      setQuery("");
      listSessions().then(setSessions).catch(() => {});
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

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
      s.lecture_title.toLowerCase().includes(lq) ||
      s.course_title.toLowerCase().includes(lq),
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
            placeholder="搜索课程、功能…"
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
              <div className="cmdk-section-label">课程</div>
              {filteredSessions.map((s) => (
                <div
                  key={s.session_id}
                  className="cmdk-item"
                  onClick={() => go(`/session/${s.session_id}`)}
                  role="option"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && go(`/session/${s.session_id}`)}
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

          {filteredSessions.length === 0 && filteredNav.length === 0 && (
            <div className="cmdk-empty">无匹配结果</div>
          )}
        </div>
      </div>
    </div>
  );
}
