import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import clsx from "clsx";
import {
  createShare,
  deactivateProjectSession,
  getProject,
  getProjectChat,
  getProjectGraph,
  getProjectScientific,
  listOrganizations,
  listProjectActivity,
  listProjectRevisions,
  listProjectSessions,
  refreshProject,
  sendProjectChat,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/primitives/Button";
import type {
  ActivityEventView,
  ChatDocument,
  CourseSession,
  GraphArtifact,
  ProjectRevisionView,
  ProjectView,
  ScientificReport,
} from "../types";
import "./AccountPage.css";

const ConceptGraph = lazy(() =>
  import("../components/graph/ConceptGraph").then((module) => ({ default: module.ConceptGraph })),
);

type ProjectTab = "graph" | "scientific" | "opportunities" | "documents" | "activity" | "revisions" | "chat";
const ROLE_RANK: Record<string, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };

export function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id ?? "";
  const { user, activeOrganizationId } = useAuth();
  const [project, setProject] = useState<ProjectView | null>(null);
  const [sessions, setSessions] = useState<CourseSession[]>([]);
  const [revisions, setRevisions] = useState<ProjectRevisionView[]>([]);
  const [activity, setActivity] = useState<ActivityEventView[]>([]);
  const [graph, setGraph] = useState<GraphArtifact | null>(null);
  const [scientific, setScientific] = useState<ScientificReport | null>(null);
  const [chat, setChat] = useState<ChatDocument | null>(null);
  const [tab, setTab] = useState<ProjectTab>("graph");
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareDays, setShareDays] = useState(7);
  const [shareUrl, setShareUrl] = useState("");
  const [teamGraphEnabled, setTeamGraphEnabled] = useState(false);
  const membership = user?.memberships.find((item) => item.organization_id === activeOrganizationId);
  const rank = user?.is_platform_admin ? 3 : ROLE_RANK[membership?.role ?? "viewer"];
  const canWrite = rank >= 1;
  const canAdmin = rank >= 2;

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    setError("");
    Promise.all([
      getProject(projectId),
      listProjectSessions(projectId),
      listProjectRevisions(projectId),
      listProjectActivity(projectId),
      getProjectGraph(projectId).catch(() => null),
      getProjectScientific(projectId).catch(() => null),
      getProjectChat(projectId).catch(() => null),
      listOrganizations(),
    ])
      .then(([projectValue, sessionValues, revisionValues, activityValues, graphValue, reportValue, chatValue, organizations]) => {
        if (!active) return;
        setProject(projectValue);
        setSessions(sessionValues);
        setRevisions(revisionValues);
        setActivity(activityValues);
        setGraph(graphValue);
        setScientific(reportValue);
        setChat(chatValue);
        setTeamGraphEnabled(Boolean(
          organizations.find((value) => value.organization_id === activeOrganizationId)?.entitlements.team_graph,
        ));
      })
      .catch(() => {
        if (active) setError("项目不可见或加载失败。");
      });
    return () => {
      active = false;
    };
  }, [projectId, activeOrganizationId]);

  if (!id) return <Navigate to="/" replace />;

  async function runRefresh() {
    setRefreshing(true);
    setError("");
    try {
      const revision = await refreshProject(projectId);
      setRevisions((current) => [revision, ...current.filter((item) => item.revision_id !== revision.revision_id)]);
      setGraph(await getProjectGraph(projectId));
      setScientific(await getProjectScientific(projectId).catch(() => null));
      setProject((current) => current ? { ...current, latest_revision_id: revision.revision_id } : current);
    } catch (reason) {
      setError(`刷新失败：${String(reason)}`);
    } finally {
      setRefreshing(false);
    }
  }

  async function deactivate(session: CourseSession) {
    if (!window.confirm(`停用“${session.lecture_title}”并生成排除该来源的新修订版？`)) return;
    try {
      await deactivateProjectSession(projectId, session.session_id);
      setSessions((current) => current.filter((item) => item.session_id !== session.session_id));
    } catch (reason) {
      setError(`停用失败：${String(reason)}`);
    }
  }

  async function chooseRevision(revision: ProjectRevisionView) {
    try {
      setGraph(await getProjectGraph(projectId, revision.revision_id));
      setTab("graph");
    } catch {
      setError("该修订版图谱不可用。");
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!chatInput.trim()) return;
    setChatSending(true);
    try {
      const response = await sendProjectChat(projectId, chatInput.trim());
      setChat(response.chat);
      setChatInput("");
    } catch (reason) {
      setError(`项目 Chat 失败：${String(reason)}`);
    } finally {
      setChatSending(false);
    }
  }

  async function generateShare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project?.latest_revision_id) return;
    try {
      const value = await createShare({
        resource_type: "project_revision",
        resource_key: project.latest_revision_id,
        expires_in_days: shareDays,
      });
      setShareUrl(value.share_url ?? "");
    } catch (reason) {
      setError(`分享创建失败：${String(reason)}`);
    }
  }

  const tabs: Array<{ id: ProjectTab; label: string }> = [
    { id: "graph", label: "公共图谱" },
    ...(project?.kind === "scientific" ? [
      { id: "scientific" as const, label: "科研证据" },
      { id: "opportunities" as const, label: "研发机会" },
    ] : []),
    { id: "documents", label: "文献" },
    ...(teamGraphEnabled ? [
      { id: "activity" as const, label: "活动" },
      { id: "revisions" as const, label: "修订历史" },
    ] : []),
    { id: "chat", label: "个人 Chat" },
  ];

  return (
    <div className="collection-page">
      <header className="collection-head">
        <div><h1>{project?.name ?? "项目"}</h1><p className="account-muted">{project?.description || "团队共享知识项目"}</p></div>
        <div className="collection-toolbar">
          {canWrite && <Link className="btn btn-primary btn-md" to={`/new?project=${projectId}&course=${encodeURIComponent(project?.name ?? "")}`}>新增文献</Link>}
          {canWrite && teamGraphEnabled && <Button loading={refreshing} variant="ghost" onClick={runRefresh}>刷新公共版本</Button>}
          {canAdmin && project?.latest_revision_id && <Button variant="ghost" onClick={() => setShareOpen(true)}>分享快照</Button>}
        </div>
      </header>
      {error && <div className="account-error" role="alert">{error}</div>}
      <nav className="project-tabs" aria-label="项目内容">
        {tabs.map((item) => <button key={item.id} className={clsx({ active: tab === item.id })} onClick={() => setTab(item.id)} type="button">{item.label}</button>)}
      </nav>

      {tab === "graph" && (graph ? (
        <div className="project-graph"><Suspense fallback={<div className="empty-panel">加载图谱…</div>}><ConceptGraph artifact={graph} /></Suspense></div>
      ) : <div className="empty-panel">尚无公共图谱。成员上传并完成单篇抽取后，Team 项目会自动发布修订版。</div>)}

      {tab === "scientific" && (
        scientific ? <div className="card-list">
          {scientific.insights.map((insight) => <article className="content-card" key={insight.insight_id}><h3>{insight.title_zh}</h3><p>{insight.summary_zh}</p><p className="account-muted">{insight.reasoning_zh}</p></article>)}
        </div> : <div className="empty-panel">尚无项目级科研证据综合。</div>
      )}

      {tab === "opportunities" && (
        scientific ? <div className="card-list">
          {scientific.decision_cards.map((card) => <article className="content-card" key={card.decision_id}><h3>{card.title_zh}</h3><p>{card.recommendation_zh}</p><p><strong>下一步实验：</strong>{card.next_experiment_zh}</p><p className="account-muted">{card.rationale_zh}</p></article>)}
        </div> : <div className="empty-panel">尚无研发机会卡。</div>
      )}

      {tab === "documents" && (
        <section className="content-card">
          <table className="data-table"><thead><tr><th>文献</th><th>贡献者</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>{sessions.map((session) => <tr key={session.session_id}><td><Link to={`/session/${session.session_id}`}>{session.lecture_title}</Link></td><td>{session.created_by_user_id?.slice(0, 8) ?? "-"}</td><td>{session.status}</td><td>{canAdmin && <Button size="sm" variant="ghost" onClick={() => deactivate(session)}>停用</Button>}</td></tr>)}</tbody>
          </table>
        </section>
      )}

      {tab === "activity" && <div className="card-list">{activity.map((event) => <article className="content-card" key={event.event_id}><strong>{event.action}</strong><div className="content-meta"><span>{new Date(event.created_at).toLocaleString()}</span><span>{event.actor_user_id?.slice(0, 8) ?? "system"}</span></div></article>)}</div>}

      {tab === "revisions" && <div className="card-list">{revisions.map((revision) => <article className="content-card" key={revision.revision_id}><h3>修订版 {revision.revision_number} · {revision.status}</h3><div className="content-meta"><span>{revision.source_session_ids.length} 篇文献</span><span>{revision.contributor_user_ids.length} 位贡献者</span><span>{revision.completed_at ? new Date(revision.completed_at).toLocaleString() : "处理中"}</span></div>{revision.status === "ready" && <Button size="sm" variant="ghost" onClick={() => chooseRevision(revision)}>查看此版图谱</Button>}{revision.error && <div className="account-error">{revision.error}</div>}</article>)}</div>}

      {tab === "chat" && <section className="content-card"><div className="chat-log">{chat?.messages.map((message) => <div className={clsx("chat-line", message.role)} key={message.message_id}>{message.content}</div>)}{!chat?.messages.length && <div className="account-muted">对话历史仅你可见，检索范围固定为项目最新稳定修订版。</div>}</div>{canWrite && <form className="inline-form" onSubmit={sendMessage}><input value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="询问项目最新公共图谱…" /><Button type="submit" loading={chatSending}>发送</Button></form>}</section>}

      {shareOpen && <div className="modal-backdrop" role="presentation" onMouseDown={() => setShareOpen(false)}><section className="modal-card" role="dialog" aria-modal="true" aria-labelledby="share-title" onMouseDown={(event) => event.stopPropagation()}><h2 id="share-title">创建固定快照链接</h2><p className="account-muted">外链固定到当前修订版，不会随项目更新；不包含原始文件、成员、Chat 和内部路径。</p><form className="account-form" onSubmit={generateShare}><label>有效天数<input type="number" min={1} max={90} value={shareDays} onChange={(event) => setShareDays(Number(event.target.value))} /></label><Button type="submit">生成链接</Button></form>{shareUrl && <div className="copy-value"><code>{shareUrl}</code><Button size="sm" onClick={() => navigator.clipboard.writeText(shareUrl)}>复制</Button></div>}<Button variant="ghost" onClick={() => setShareOpen(false)}>关闭</Button></section></div>}
    </div>
  );
}
