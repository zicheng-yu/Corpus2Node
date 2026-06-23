import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";
import { bindPurpose, deleteCredential, deleteSession, getLlmSettings, listSessions, upsertCredential } from "../api/client";
import type { CourseSession, LLMSettingsView, LlmPurpose, ProviderKind, SessionStatus } from "../types";
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

const PURPOSES: LlmPurpose[] = ["graph", "chat", "critic", "exam"];

function DeploymentSettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<LLMSettingsView | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  // new-credential form
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<ProviderKind>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [defaultModel, setDefaultModel] = useState("");

  // binding form
  const [bindCred, setBindCred] = useState("");
  const [bindModel, setBindModel] = useState("");

  const load = useCallback(async () => {
    try {
      const s = await getLlmSettings();
      setSettings(s);
      setBindCred((cur) => cur || s.credentials[0]?.credential_id || "");
    } catch {
      toast("加载模型设置失败", "error");
    }
  }, [toast]);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  async function addCredential() {
    if (!label.trim() || !apiKey.trim()) {
      toast("标签和 API Key 必填", "error");
      return;
    }
    try {
      const s = await upsertCredential({
        label: label.trim(),
        kind,
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        default_model: defaultModel.trim(),
      });
      setSettings(s);
      setApiKey("");
      setLabel("");
      setBindCred((cur) => cur || s.credentials[s.credentials.length - 1]?.credential_id || "");
      toast("凭据已保存", "success");
    } catch (e) {
      toast(`保存失败：${String(e)}`, "error");
    }
  }

  async function removeCredential(id: string) {
    try {
      setSettings(await deleteCredential(id));
    } catch (e) {
      toast(`删除失败：${String(e)}`, "error");
    }
  }

  async function bind(purpose: LlmPurpose) {
    if (!bindCred) {
      toast("请先选择凭据", "error");
      return;
    }
    try {
      setSettings(await bindPurpose(purpose, { credential_id: bindCred, model: bindModel.trim() }));
      toast(`已绑定 ${purpose}`, "success");
    } catch (e) {
      toast(`绑定失败：${String(e)}`, "error");
    }
  }

  async function quickBindGraphChat() {
    if (!bindCred) {
      toast("请先选择凭据", "error");
      return;
    }
    try {
      let latest: LLMSettingsView | null = null;
      for (const p of ["graph", "chat"] as LlmPurpose[]) {
        latest = await bindPurpose(p, { credential_id: bindCred, model: bindModel.trim() });
      }
      if (latest) setSettings(latest);
      toast("已把 graph + chat 绑定到所选凭据", "success");
    } catch (e) {
      toast(`绑定失败：${String(e)}`, "error");
    }
  }

  const bindingByPurpose = new Map((settings?.bindings ?? []).map((b) => [b.purpose, b]));

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="settings-head">
          <div>
            <p className="settings-kicker">MODELS</p>
            <h2>模型配置</h2>
            <p>暂存多个 API 凭据（OpenAI 兼容 / Anthropic），再把 graph / chat / critic / exam 绑定到某个凭据+模型。密钥仅以掩码回显。</p>
          </div>
          <button className="settings-close" type="button" onClick={onClose} aria-label="关闭设置">×</button>
        </div>

        {loading ? (
          <div className="settings-loading">加载设置中…</div>
        ) : (
          <>
            <div className="settings-warning">
              图片/PDF 解析（Kimi）、Embedding、语音转写仍由后端 <code>.env</code> 配置；此面板只管 graph/chat/critic/exam 这类对话模型。
            </div>

            {/* Credentials */}
            <div className="settings-list">
              <section className="settings-group is-open">
                <div className="settings-group-toggle" style={{ cursor: "default" }}>
                  <span className="settings-group-copy">
                    <span className="settings-group-title">已有凭据</span>
                    <span className="settings-group-description">已保存的 API Key（掩码显示），可删除。</span>
                  </span>
                  <span className="settings-group-count">{settings?.credentials.length ?? 0} 个</span>
                </div>
                <div className="settings-row-list">
                  {(settings?.credentials ?? []).length === 0 && (
                    <div className="settings-row" style={{ color: "var(--ink-3)" }}>暂无凭据，请在下方新增。</div>
                  )}
                  {(settings?.credentials ?? []).map((c) => (
                    <div className="settings-row" key={c.credential_id} style={{ alignItems: "center" }}>
                      <span className="settings-row-copy">
                        <span className="settings-row-title">
                          {c.label} <em>{c.kind}</em>
                        </span>
                        <span className="settings-row-key">
                          {c.credential_id} · {c.default_model || "(无默认模型)"} · key {c.api_key_preview || "—"}
                        </span>
                      </span>
                      <button className="btn btn-outline btn-sm" type="button" onClick={() => removeCredential(c.credential_id)}>删除</button>
                    </div>
                  ))}
                </div>
              </section>

              {/* Bindings */}
              <section className="settings-group is-open">
                <div className="settings-group-toggle" style={{ cursor: "default" }}>
                  <span className="settings-group-copy">
                    <span className="settings-group-title">用途绑定</span>
                    <span className="settings-group-description">graph 用于建图抽取，chat 用于问答；二者至少各绑一个。</span>
                  </span>
                </div>
                <div className="settings-row-list">
                  {PURPOSES.map((p) => {
                    const b = bindingByPurpose.get(p);
                    return (
                      <div className="settings-row" key={p}>
                        <span className="settings-row-copy">
                          <span className="settings-row-title">{p}</span>
                          <span className="settings-row-key">
                            {b ? `${b.credential_id} · ${b.model || "(默认)"} ${b.resolved ? "✓" : "✗ 凭据缺失"}` : "未绑定"}
                          </span>
                        </span>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>

            {/* Add credential */}
            <div className="settings-list">
              <section className="settings-group is-open">
                <div className="settings-group-toggle" style={{ cursor: "default" }}>
                  <span className="settings-group-copy">
                    <span className="settings-group-title">新增凭据</span>
                  </span>
                </div>
                <div className="settings-row-list">
                  <label className="settings-row">
                    <span className="settings-row-copy"><span className="settings-row-title">标签</span></span>
                    <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="如 deepseek" autoComplete="off" />
                  </label>
                  <label className="settings-row">
                    <span className="settings-row-copy"><span className="settings-row-title">类型</span></span>
                    <select value={kind} onChange={(e) => setKind(e.target.value as ProviderKind)}>
                      <option value="openai">openai 兼容</option>
                      <option value="anthropic">anthropic</option>
                    </select>
                  </label>
                  <label className="settings-row">
                    <span className="settings-row-copy"><span className="settings-row-title">base_url</span></span>
                    <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com" autoComplete="off" />
                  </label>
                  <label className="settings-row">
                    <span className="settings-row-copy"><span className="settings-row-title">api_key</span></span>
                    <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." autoComplete="off" />
                  </label>
                  <label className="settings-row">
                    <span className="settings-row-copy"><span className="settings-row-title">默认模型</span></span>
                    <input value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)} placeholder="如 deepseek-v4-flash" autoComplete="off" />
                  </label>
                  <div className="settings-row">
                    <span className="settings-row-copy" />
                    <button className="btn btn-accent btn-sm" type="button" onClick={addCredential}>保存凭据</button>
                  </div>
                </div>
              </section>

              {/* Bind a purpose */}
              <section className="settings-group is-open">
                <div className="settings-group-toggle" style={{ cursor: "default" }}>
                  <span className="settings-group-copy">
                    <span className="settings-group-title">绑定用途</span>
                  </span>
                </div>
                <div className="settings-row-list">
                  <label className="settings-row">
                    <span className="settings-row-copy"><span className="settings-row-title">凭据</span></span>
                    <select value={bindCred} onChange={(e) => setBindCred(e.target.value)}>
                      {(settings?.credentials ?? []).map((c) => (
                        <option key={c.credential_id} value={c.credential_id}>{c.label} ({c.credential_id})</option>
                      ))}
                    </select>
                  </label>
                  <label className="settings-row">
                    <span className="settings-row-copy"><span className="settings-row-title">模型（留空=用默认）</span></span>
                    <input value={bindModel} onChange={(e) => setBindModel(e.target.value)} placeholder="如 deepseek-v4-flash" autoComplete="off" />
                  </label>
                  <div className="settings-row" style={{ gap: 8, flexWrap: "wrap" }}>
                    <span className="settings-row-copy" />
                    {PURPOSES.map((p) => (
                      <button key={p} className="btn btn-outline btn-sm" type="button" onClick={() => bind(p)}>绑定 {p}</button>
                    ))}
                    <button className="btn btn-accent btn-sm" type="button" onClick={quickBindGraphChat}>一键 graph + chat</button>
                  </div>
                </div>
              </section>
            </div>

            <div className="settings-actions">
              <button className="btn btn-accent btn-sm" type="button" onClick={onClose}>完成</button>
            </div>
          </>
        )}
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();

  useEffect(() => {
    listSessions()
      .then((data) => setSessions(data.sort((a, b) => b.updated_at.localeCompare(a.updated_at))))
      .catch(() => toast("加载会话列表失败", "error"))
      .finally(() => setLoading(false));
  }, [toast]);

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
            className="btn btn-outline"
            onClick={() => setSettingsOpen(true)}
            type="button"
          >
            模型配置
          </button>
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
              <div className="session-group-header">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--ink-3)", flexShrink: 0 }}>
                  <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
                </svg>
                <span className="session-group-name">{course}</span>
                <span className="session-group-count">{rows.length} 个资料集</span>
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
              {rows.map((s) => (
                <SessionRow
                  key={s.session_id}
                  session={s}
                  onClick={() => navigate(sessionHref(s))}
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

      {settingsOpen && <DeploymentSettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

function SessionRow({ session: s, onClick, onDelete }: { session: CourseSession; onClick: () => void; onDelete: () => void }) {
  const date = new Date(s.updated_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
  const hasPdf = s.source_files.some((f) => f.kind === "pdf");
  const hasAudio = s.source_files.some((f) => f.kind === "audio");
  const hasDoc = s.source_files.some((f) => f.kind === "document");
  const hasImage = s.source_files.some((f) => f.kind === "image");

  return (
    <div className="session-row" onClick={onClick} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onClick()}>
      <CoverMark seed={s.session_id} size={56} />

      <div style={{ minWidth: 0 }}>
        <div className="session-lecture">{s.lecture_title}</div>
        <div className="session-meta">
          <span>{date}</span>
          {hasPdf && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>
              PDF
            </span>
          )}
          {hasAudio && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
              音频
            </span>
          )}
          {hasDoc && (
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
              文档
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
