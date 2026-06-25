import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";
import { ApiError, deleteSession, listSessions, renameCourse, renameSession, searchConceptsGlobal } from "../api/client";
import type { CourseSession, GlobalConceptHit, SessionStatus } from "../types";
import { useToast } from "../components/primitives/Toast";
import "./HomePage.css";

// ── CoverMark ─────────────────────────────────────────────────────────────────
function CoverMark({ seed, size = 56 }: { seed: string; size?: number }) {
  let h = 0;
  for (let i = 0; i < (seed || "").length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const rot = h % 360;
  const n = 3 + (h % 4);
  const dots = Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2 + (rot * Math.PI) / 180;
    const r = 14 + ((h >> i) & 7);
    return { x: 50 + Math.cos(a) * r, y: 50 + Math.sin(a) * r, r: 3 + ((h >> (i * 2)) & 3) };
  });
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" style={{ display: "block" }}>
      <rect x="1" y="1" width="98" height="98" rx="8" fill="var(--panel-2)" stroke="var(--rule)" />
      {dots.map((d, i) =>
        dots.slice(i + 1).map((d2, j) => (
          <line
            key={`${i}-${j}`}
            x1={d.x} y1={d.y} x2={d2.x} y2={d2.y}
            stroke="var(--rule-strong)" strokeWidth="0.8"
          />
        )),
      )}
      {dots.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={d.r} fill="var(--accent)" opacity="0.7" />
      ))}
    </svg>
  );
}

function TrashIcon() {
  return <span className="trash-icon" aria-hidden="true" />;
}

function PencilIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

// ── StatusChip ────────────────────────────────────────────────────────────────
const STATUS_MAP: Record<SessionStatus, { cls: string; label: string }> = {
  draft:       { cls: "chip",       label: "草稿" },
  uploaded:    { cls: "chip chip-info",  label: "已上传" },
  ingesting:   { cls: "chip chip-live",  label: "解析中" },
  building_graph: { cls: "chip chip-live", label: "构建图谱中" },
  merging_graph:  { cls: "chip chip-live", label: "合并图谱中" },
  graph_ready: { cls: "chip chip-warn",  label: "图谱就绪" },
  notes_ready: { cls: "chip chip-ok",    label: "已就绪" },
  failed:      { cls: "chip chip-err",   label: "失败" },
};

function StatusChip({ status }: { status: SessionStatus }) {
  const { cls, label } = STATUS_MAP[status] ?? { cls: "chip", label: status };
  return (
    <span className={cls}>
      <span className="chip-dot" />
      {label}
    </span>
  );
}

// ── Status filter groups ──────────────────────────────────────────────────────
type FilterGroup = "all" | "ready" | "processing" | "failed";

function matchFilter(status: SessionStatus, filter: FilterGroup): boolean {
  if (filter === "all") return true;
  if (filter === "ready") return status === "notes_ready" || status === "graph_ready";
  if (filter === "processing") return status === "ingesting" || status === "building_graph" || status === "merging_graph" || status === "uploaded" || status === "draft";
  if (filter === "failed") return status === "failed";
  return true;
}

function sessionHref(session: CourseSession): string {
  if (session.status === "graph_ready" || session.status === "notes_ready") {
    return `/session/${session.session_id}`;
  }
  return `/session/${session.session_id}/pipeline`;
}

function sortSessions(data: CourseSession[]): CourseSession[] {
  return [...data].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

type RenameTarget =
  | { type: "session"; session: CourseSession }
  | { type: "course"; courseTitle: string };

// ── ConfirmModal ──────────────────────────────────────────────────────────────
function ConfirmModal({
  message,
  onConfirm,
  onCancel,
  loading,
}: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading: boolean;
}) {
  return (
    <div className="confirm-overlay" onClick={() => !loading && onCancel()}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
        <p className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button className="btn btn-outline btn-sm" onClick={onCancel} disabled={loading} type="button">
            取消
          </button>
          <button className="btn btn-danger btn-sm" onClick={onConfirm} disabled={loading} type="button">
            {loading ? "删除中…" : "确认删除"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RenameModal({
  title,
  label,
  initialValue,
  loading,
  onConfirm,
  onCancel,
}: {
  title: string;
  label: string;
  initialValue: string;
  loading: boolean;
  onConfirm: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  const trimmed = value.trim();
  const disabled = loading || !trimmed || trimmed === initialValue.trim();

  function submit() {
    if (!disabled) onConfirm(trimmed);
  }

  return (
    <div className="confirm-overlay" onClick={() => !loading && onCancel()}>
      <div className="confirm-dialog rename-dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="rename-title">{title}</h2>
        <label className="rename-label" htmlFor="rename-input">{label}</label>
        <input
          id="rename-input"
          className="rename-input"
          value={value}
          autoFocus
          maxLength={120}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
            if (e.key === "Escape" && !loading) onCancel();
          }}
        />
        <div className="confirm-actions">
          <button className="btn btn-outline btn-sm" onClick={onCancel} disabled={loading} type="button">
            取消
          </button>
          <button className="btn btn-accent btn-sm" onClick={submit} disabled={disabled} type="button">
            {loading ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── HomePage ──────────────────────────────────────────────────────────────────
export function HomePage() {
  const [sessions, setSessions] = useState<CourseSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterGroup>("all");
  const [courseFilter, setCourseFilter] = useState<string>("all");
  const [pending, setPending] = useState<{ label: string; onConfirm: () => Promise<void> } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [conceptHits, setConceptHits] = useState<GlobalConceptHit[]>([]);
  const [collapsedCourses, setCollapsedCourses] = useState<Set<string>>(
    () => new Set<string>(JSON.parse(localStorage.getItem("c2n:collapsedCourses") || "[]")),
  );
  const toast = useToast();
  const navigate = useNavigate();

  useEffect(() => {
    listSessions()
      .then((data) => setSessions(sortSessions(data)))
      .catch(() => toast("加载会话列表失败", "error"))
      .finally(() => setLoading(false));
  }, [toast]);

  // global concept search (debounced) across every built graph
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setConceptHits([]);
      return;
    }
    const timer = setTimeout(() => {
      searchConceptsGlobal(q, 12).then(setConceptHits).catch(() => setConceptHits([]));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  function toggleCourse(course: string) {
    setCollapsedCourses((prev) => {
      const next = new Set(prev);
      if (next.has(course)) next.delete(course);
      else next.add(course);
      localStorage.setItem("c2n:collapsedCourses", JSON.stringify([...next]));
      return next;
    });
  }

  const handleDeleteSession = (session: CourseSession) => {
    setPending({
      label: `确认删除「${session.lecture_title}」？此操作不可撤销。`,
      onConfirm: async () => {
        await deleteSession(session.session_id);
        setSessions((prev) => prev.filter((s) => s.session_id !== session.session_id));
        toast("已删除", "success");
      },
    });
  };

  const handleDeleteCourse = (courseTitle: string) => {
    const count = sessions.filter((s) => s.course_title === courseTitle).length;
    setPending({
      label: `确认删除知识库「${courseTitle}」中的全部 ${count} 个资料集？此操作不可撤销。`,
      onConfirm: async () => {
        const toDelete = sessions.filter((s) => s.course_title === courseTitle);
        await Promise.all(toDelete.map((s) => deleteSession(s.session_id)));
        setSessions((prev) => prev.filter((s) => s.course_title !== courseTitle));
        toast("知识库已删除", "success");
      },
    });
  };

  const confirmRename = async (value: string) => {
    if (!renameTarget) return;
    setRenaming(true);
    try {
      if (renameTarget.type === "session") {
        const updated = await renameSession(renameTarget.session.session_id, { lecture_title: value });
        setSessions((prev) => sortSessions(prev.map((s) => (s.session_id === updated.session_id ? updated : s))));
        toast("资料集已改名", "success");
      } else {
        const oldTitle = renameTarget.courseTitle;
        const updated = await renameCourse({ old_course_title: oldTitle, new_course_title: value });
        const updatedById = new Map(updated.map((s) => [s.session_id, s]));
        setSessions((prev) => sortSessions(prev.map((s) => updatedById.get(s.session_id) ?? s)));
        setCourseFilter((current) => (current === oldTitle ? value : current));
        setCollapsedCourses((prev) => {
          const next = new Set(prev);
          const wasCollapsed = next.delete(oldTitle);
          if (wasCollapsed) next.add(value);
          localStorage.setItem("c2n:collapsedCourses", JSON.stringify([...next]));
          return next;
        });
        toast("知识库已改名", "success");
      }
      setRenameTarget(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        toast("已有同名知识库", "error");
      } else {
        toast("改名失败，请重试", "error");
      }
    } finally {
      setRenaming(false);
    }
  };

  const confirmDelete = async () => {
    if (!pending) return;
    setDeleting(true);
    try {
      await pending.onConfirm();
      setPending(null);
    } catch {
      toast("删除失败，请重试", "error");
    } finally {
      setDeleting(false);
    }
  };

  const courses = useMemo(() => {
    const seen = new Set<string>();
    return sessions.filter((s) => {
      if (seen.has(s.course_title)) return false;
      seen.add(s.course_title);
      return true;
    }).map((s) => s.course_title);
  }, [sessions]);

  const filtered = useMemo(() => {
    const lq = query.toLowerCase();
    return sessions.filter((s) => {
      // Hide virtual course-graph sessions from the normal list
      if (s.lecture_title.startsWith("[总图谱] ")) return false;
      if (!matchFilter(s.status, statusFilter)) return false;
      if (courseFilter !== "all" && s.course_title !== courseFilter) return false;
      if (lq && !s.lecture_title.toLowerCase().includes(lq) && !s.course_title.toLowerCase().includes(lq)) return false;
      return true;
    });
  }, [sessions, statusFilter, courseFilter, query]);

  // Group by course_title
  const groups = useMemo(() => {
    const map = new Map<string, CourseSession[]>();
    for (const s of filtered) {
      const arr = map.get(s.course_title) ?? [];
      arr.push(s);
      map.set(s.course_title, arr);
    }
    return map;
  }, [filtered]);

  const totalConcepts = sessions.reduce((a, s) => a + (s.stats?.concept_count ?? 0), 0);
  const totalRelations = sessions.reduce((a, s) => a + (s.stats?.relation_count ?? 0), 0);

  return (
    <div className="page">
      {/* Header */}
      <div className="home-head">
        <div className="home-head-left">
          <div className="home-head-label">知识库 · LIBRARY</div>
          <h1 className="home-title">
            我的知识库 / <em>graph</em>
          </h1>
          <p className="home-sub">
            {sessions.length} 个资料集 · 累计 <b>{totalConcepts.toLocaleString()}</b> 个知识点，<b>{totalRelations.toLocaleString()}</b> 条关系
          </p>
        </div>
        <div className="home-head-actions">
          <button
            className="btn btn-accent"
            onClick={() => navigate("/new")}
            type="button"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            新建知识库
          </button>
        </div>
      </div>

      {/* Toolbar */}
      <div className="home-toolbar">
        <div className="home-search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索知识库或资料集…"
          />
        </div>

        <div className="filter-group">
          <span className="filter-label">状态</span>
          {(["all", "ready", "processing", "failed"] as FilterGroup[]).map((f) => (
            <button
              key={f}
              className={clsx("filter-pill", { active: statusFilter === f })}
              onClick={() => setStatusFilter(f)}
              type="button"
            >
              {{ all: "全部", ready: "已就绪", processing: "处理中", failed: "失败" }[f]}
            </button>
          ))}
        </div>

        <div className="filter-group">
          <span className="filter-label">知识库</span>
          <select
            className="filter-select"
            value={courseFilter}
            onChange={(e) => setCourseFilter(e.target.value)}
          >
            <option value="all">全部</option>
            {courses.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Global concept search results */}
      {query.trim() && conceptHits.length > 0 && (
        <div className="home-concepts">
          <div className="home-concepts-label">相关知识点 · {conceptHits.length}</div>
          <div className="home-concepts-list">
            {conceptHits.map((c) => (
              <button
                key={`${c.session_id}-${c.concept_id}`}
                className="home-concept-row"
                type="button"
                onClick={() => navigate(`/session/${c.session_id}?concept=${encodeURIComponent(c.concept_id)}`)}
              >
                <span className="home-concept-name">{c.name}</span>
                <span className="home-concept-meta">{c.lecture_title} · {c.course_title}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="session-list">
          {[1, 2, 3].map((i) => <div key={i} className="home-skeleton" />)}
        </div>
      ) : groups.size === 0 ? (
        <div className="home-empty">
          <div className="home-empty-title">暂无知识库</div>
          {sessions.length === 0
            ? "上传你的第一份资料，开始构建知识图谱。"
            : "没有符合筛选条件的知识库。"}
        </div>
      ) : (
        <div className="session-list">
          {Array.from(groups.entries()).map(([course, rows]) => (
            <div key={course}>
              <div
                className="session-group-header"
                onClick={() => toggleCourse(course)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && toggleCourse(course)}
              >
                <svg
                  width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                  style={{ color: "var(--ink-3)", flexShrink: 0, transform: collapsedCourses.has(course) ? "rotate(-90deg)" : "none", transition: "transform 150ms var(--ease)" }}
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--ink-3)", flexShrink: 0 }}>
                  <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                </svg>
                <span className="session-group-name">{course}</span>
                <span className="session-group-count">{rows.length} 个资料集</span>
                <button
                  className="btn btn-icon group-edit-btn"
                  onClick={(e) => { e.stopPropagation(); setRenameTarget({ type: "course", courseTitle: course }); }}
                  aria-label={`重命名知识库 ${course}`}
                  title="重命名知识库"
                  type="button"
                >
                  <PencilIcon />
                </button>
                <button
                  className="btn btn-icon group-add-btn"
                  onClick={(e) => { e.stopPropagation(); navigate(`/new?course=${encodeURIComponent(course)}`); }}
                  aria-label={`向知识库 ${course} 新增资料集`}
                  title="新增资料集"
                  type="button"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                </button>
                <button
                  className="btn btn-icon group-delete-btn"
                  onClick={(e) => { e.stopPropagation(); handleDeleteCourse(course); }}
                  aria-label={`删除知识库 ${course}`}
                  title="删除整个知识库"
                  type="button"
                >
                  <TrashIcon />
                </button>
              </div>
              {!collapsedCourses.has(course) &&
                rows.map((s) => (
                  <SessionRow
                    key={s.session_id}
                    session={s}
                    onClick={() => navigate(sessionHref(s))}
                    onRename={() => setRenameTarget({ type: "session", session: s })}
                    onDelete={() => handleDeleteSession(s)}
                  />
                ))}
            </div>
          ))}
        </div>
      )}

      {pending && (
        <ConfirmModal
          message={pending.label}
          onConfirm={confirmDelete}
          onCancel={() => !deleting && setPending(null)}
          loading={deleting}
        />
      )}

      {renameTarget && (
        <RenameModal
          title={renameTarget.type === "course" ? "重命名知识库" : "重命名资料集"}
          label={renameTarget.type === "course" ? "知识库名称" : "资料集名称"}
          initialValue={renameTarget.type === "course" ? renameTarget.courseTitle : renameTarget.session.lecture_title}
          loading={renaming}
          onConfirm={confirmRename}
          onCancel={() => !renaming && setRenameTarget(null)}
        />
      )}

    </div>
  );
}

function SessionRow({
  session: s,
  onClick,
  onRename,
  onDelete,
}: {
  session: CourseSession;
  onClick: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const date = new Date(s.updated_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
  const hasDoc = s.source_files.some((f) => f.kind === "document" || f.kind === "pdf");  // PDF 归入文档
  const hasVideo = s.source_files.some((f) => f.kind === "video");
  const hasAudio = s.source_files.some((f) => f.kind === "audio");
  const hasImage = s.source_files.some((f) => f.kind === "image");

  return (
    <div className="session-row" onClick={onClick} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onClick()}>
      <CoverMark seed={s.session_id} size={56} />

      <div style={{ minWidth: 0 }}>
        <div className="session-lecture">{s.lecture_title}</div>
        <div className="session-meta">
          <span>{date}</span>
          {hasDoc && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
              文档
            </span>
          )}
          {hasVideo && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><polygon points="10 8 15 10.5 10 13 10 8" fill="currentColor"/></svg>
              视频
            </span>
          )}
          {hasAudio && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
              音频
            </span>
          )}
          {hasImage && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.5-3.5L9 20"/></svg>
              图片
            </span>
          )}
        </div>
      </div>

      <div className="session-stats">
        <span><b>{s.stats?.concept_count ?? "—"}</b> 概念</span>
        <span><b>{s.stats?.relation_count ?? "—"}</b> 关系</span>
      </div>

      <StatusChip status={s.status} />

      <button
        className="btn btn-icon row-edit-btn"
        onClick={(e) => { e.stopPropagation(); onRename(); }}
        aria-label="重命名此资料集"
        title="重命名此资料集"
        type="button"
      >
        <PencilIcon />
      </button>

      <button
        className="btn btn-icon row-delete-btn"
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        aria-label="删除此资料集"
        title="删除此资料集"
        type="button"
      >
        <TrashIcon />
      </button>

      <svg className="session-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m9 18 6-6-6-6" />
      </svg>
    </div>
  );
}
