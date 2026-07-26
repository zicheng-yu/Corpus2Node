import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import clsx from "clsx";
import {
  ApiError,
  deepenProposal,
  deleteDiscovery,
  deleteScientificReport,
  getDiscovery,
  getScientificReport,
  listDiscoveryHistory,
  listSessions,
  streamDiscovery,
  streamScientificAnalysis,
  updateProposalStatus,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { DiscoveryReportPanel } from "../components/discovery/DiscoveryReportPanel";
import { ScientificReportView } from "../components/scientific/ScientificReportView";
import { useToast } from "../components/primitives/Toast";
import type {
  CourseSession,
  DiscoveryHistoryItem,
  DiscoveryHistoryType,
  DiscoveryReport,
  ProposalStatus,
  ScientificReport,
} from "../types";
import "./DiscoverPage.css";
import "./HomePage.css";
import "./ScientificPage.css";

type DiscoverMode = "cross" | "scientific";
type HistoryFilter = "all" | DiscoveryHistoryType;
type ActiveReport =
  | { type: "cross_corpus"; report: DiscoveryReport }
  | { type: "scientific_evidence"; report: ScientificReport };

const MANAGE_ROLES = new Set(["owner", "admin"]);

function isRealSession(session: CourseSession): boolean {
  return !session.lecture_title.startsWith("[总图谱] ") && session.source_files.length > 0;
}

function isCrossReady(session: CourseSession): boolean {
  return session.status === "graph_ready" || session.status === "notes_ready";
}

function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : "运行失败，请稍后重试。";
  try {
    const payload = JSON.parse(error.message) as { detail?: string | { code?: string; metric?: string; used?: number; limit?: number } };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.code === "quota_exceeded") {
      return `当前额度不足：${payload.detail.metric ?? "任务"} ${payload.detail.used ?? 0}/${payload.detail.limit ?? 0}`;
    }
  } catch {
    // Preserve the server message below when it is not JSON.
  }
  return error.message;
}

function historyMeta(item: DiscoveryHistoryItem): string {
  if (item.report_type === "cross_corpus") {
    return `${item.session_count} 份资料 · ${item.proposal_count} 个提案 · ${item.finding_count} 处交叉`;
  }
  return `${item.session_count} 篇文献 · ${item.claim_count} 条主张 · ${item.insight_count} 个洞察`;
}

export function DiscoverPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { mode: authMode, user, activeOrganizationId } = useAuth();
  const toast = useToast();
  const mode: DiscoverMode = searchParams.get("mode") === "scientific" ? "scientific" : "cross";
  const [sessions, setSessions] = useState<CourseSession[]>([]);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(searchParams.getAll("session")),
  );
  const [history, setHistory] = useState<DiscoveryHistoryItem[]>([]);
  const [historyFilter, setHistoryFilter] = useState<HistoryFilter>("all");
  const [activeReport, setActiveReport] = useState<ActiveReport | null>(null);
  const [intent, setIntent] = useState("");
  const [objective, setObjective] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);
  const [running, setRunning] = useState(false);
  const [showBridgeGraph, setShowBridgeGraph] = useState(true);
  const [deepeningId, setDeepeningId] = useState<string | null>(null);

  const membership = user?.memberships.find((item) => item.organization_id === activeOrganizationId);
  const canRun = authMode !== "accounts"
    || Boolean(user?.is_platform_admin || (membership && membership.role !== "viewer"));
  const canDelete = authMode !== "accounts"
    || Boolean(user?.is_platform_admin || (membership && MANAGE_ROLES.has(membership.role)));

  useEffect(() => {
    let active = true;
    Promise.all([listSessions(), listDiscoveryHistory()])
      .then(([sessionValues, historyValues]) => {
        if (!active) return;
        const available = sessionValues.filter(isRealSession);
        const availableIds = new Set(available.map((item) => item.session_id));
        setSessions(available);
        setSelected((current) => new Set([...current].filter((id) => availableIds.has(id))));
        setHistory(historyValues);
      })
      .catch((error) => {
        if (active) toast(errorMessage(error), "error");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [toast]);

  const selectedSessions = useMemo(
    () => sessions.filter((session) => selected.has(session.session_id)),
    [selected, sessions],
  );
  const incompatible = mode === "cross" ? selectedSessions.filter((session) => !isCrossReady(session)) : [];
  const filteredSessions = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return sessions;
    return sessions.filter((session) =>
      session.lecture_title.toLowerCase().includes(normalized)
      || session.course_title.toLowerCase().includes(normalized),
    );
  }, [query, sessions]);
  const filteredHistory = useMemo(
    () => history.filter((item) => historyFilter === "all" || item.report_type === historyFilter),
    [history, historyFilter],
  );
  const hasCrossReady = sessions.some(isCrossReady);
  const runDisabled = loading || running || !canRun
    || (mode === "scientific" && selected.size === 0)
    || (mode === "cross" && (incompatible.length > 0 || (selected.size === 0 && !hasCrossReady)));

  function updateLocation(nextMode: DiscoverMode, nextSelected: Set<string>) {
    const params = new URLSearchParams();
    params.set("mode", nextMode);
    for (const sessionId of nextSelected) params.append("session", sessionId);
    setSearchParams(params, { replace: true });
  }

  function changeMode(nextMode: DiscoverMode) {
    if (running) return;
    updateLocation(nextMode, selected);
  }

  function toggleSession(sessionId: string) {
    if (running) return;
    const next = new Set(selected);
    if (next.has(sessionId)) next.delete(sessionId); else next.add(sessionId);
    setSelected(next);
    updateLocation(mode, next);
  }

  async function refreshHistory() {
    setHistory(await listDiscoveryHistory());
  }

  async function runAnalysis() {
    if (runDisabled) return;
    setRunning(true);
    try {
      if (mode === "cross") {
        const result: { report?: DiscoveryReport } = {};
        await streamDiscovery(
          {
            mode: selected.size ? "selected" : "random",
            session_ids: selected.size ? [...selected] : undefined,
            intent: intent.trim(),
            limit: 8,
            seed: selected.size ? undefined : Date.now(),
          },
          (event) => {
            if (event.type === "error") throw new Error(event.data.message || "跨资料发现失败");
            if (event.type === "done" && event.data.report) result.report = event.data.report;
          },
        );
        if (!result.report) throw new Error("跨资料发现未返回报告");
        setActiveReport({ type: "cross_corpus", report: result.report });
        setShowBridgeGraph(true);
      } else {
        const result: { report?: ScientificReport } = {};
        await streamScientificAnalysis(
          {
            session_ids: [...selected],
            objective_zh: objective.trim(),
            language_mode: "zh_bilingual",
          },
          (event) => {
            if (event.type === "error") throw new Error(event.data.message || "科研证据分析失败");
            if (event.type === "done" && event.data.report) result.report = event.data.report;
          },
        );
        if (!result.report) throw new Error("科研证据分析未返回报告");
        setActiveReport({ type: "scientific_evidence", report: result.report });
      }
      await refreshHistory();
      toast(mode === "cross" ? "跨资料发现完成" : "科研证据分析完成", "success");
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      setRunning(false);
    }
  }

  async function openHistory(item: DiscoveryHistoryItem) {
    setLoadingReport(true);
    try {
      if (item.report_type === "cross_corpus") {
        setActiveReport({ type: "cross_corpus", report: await getDiscovery(item.report_id) });
        updateLocation("cross", selected);
        setShowBridgeGraph(true);
      } else {
        setActiveReport({ type: "scientific_evidence", report: await getScientificReport(item.report_id) });
        updateLocation("scientific", selected);
      }
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      setLoadingReport(false);
    }
  }

  async function removeHistory(item: DiscoveryHistoryItem) {
    if (!window.confirm(`确认删除“${item.title}”？此操作不可撤销。`)) return;
    try {
      if (item.report_type === "cross_corpus") await deleteDiscovery(item.report_id);
      else await deleteScientificReport(item.report_id);
      setHistory((current) => current.filter((value) => value.report_id !== item.report_id));
      setActiveReport((current) => {
        if (!current) return current;
        const currentId = current.type === "cross_corpus" ? current.report.discovery_id : current.report.report_id;
        return currentId === item.report_id ? null : current;
      });
      toast("历史报告已删除", "success");
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  }

  async function updateStatus(proposalId: string, status: ProposalStatus) {
    if (activeReport?.type !== "cross_corpus") return;
    try {
      const report = await updateProposalStatus(activeReport.report.discovery_id, proposalId, status);
      setActiveReport({ type: "cross_corpus", report });
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  }

  async function deepen(proposalId: string) {
    if (activeReport?.type !== "cross_corpus" || deepeningId) return;
    setDeepeningId(proposalId);
    try {
      const report = await deepenProposal(activeReport.report.discovery_id, proposalId);
      setActiveReport({ type: "cross_corpus", report });
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      setDeepeningId(null);
    }
  }

  const activeReportId = activeReport?.type === "cross_corpus"
    ? activeReport.report.discovery_id
    : activeReport?.report.report_id;

  return (
    <main className="discover-page">
      <aside className="discover-sidebar">
        <div className="discover-sidebar-head">
          <button type="button" className="discover-back" onClick={() => navigate("/")}>← 返回项目</button>
          <span className="science-eyebrow">KNOWLEDGE DISCOVERY</span>
          <h1>知识发现</h1>
          <p>在同一个入口中选择跨资料创新发现，或面向科技文献建立可核查证据。</p>
        </div>

        <div className="discover-mode-tabs" role="tablist" aria-label="发现模式">
          <button type="button" role="tab" aria-selected={mode === "cross"} className={clsx({ active: mode === "cross" })} onClick={() => changeMode("cross")} disabled={running}>
            <strong>跨资料发现</strong><span>桥接概念与创新提案</span>
          </button>
          <button type="button" role="tab" aria-selected={mode === "scientific"} className={clsx({ active: mode === "scientific" })} onClick={() => changeMode("scientific")} disabled={running}>
            <strong>科研证据分析</strong><span>证据矩阵与研发机会</span>
          </button>
        </div>

        <label className="discover-field">
          <span>{mode === "cross" ? "发现意图（可选）" : "研发分析目标（可选）"}</span>
          <textarea
            rows={3}
            maxLength={mode === "cross" ? 600 : 800}
            value={mode === "cross" ? intent : objective}
            onChange={(event) => mode === "cross" ? setIntent(event.target.value) : setObjective(event.target.value)}
            placeholder={mode === "cross" ? "例：寻找跨部门协作与新产品机会" : "例：比较技术路线、实验结果与适用边界"}
            disabled={running}
          />
        </label>

        <div className="discover-picker-head">
          <span>选择资料</span><b>{selected.size} 份</b>
        </div>
        <input className="discover-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索知识库或资料集…" />
        <div className="discover-session-list">
          {loading && <p className="discover-muted">正在加载资料…</p>}
          {filteredSessions.map((session) => {
            const crossReady = isCrossReady(session);
            return (
              <label className={clsx("discover-session", { selected: selected.has(session.session_id) })} key={session.session_id}>
                <input type="checkbox" checked={selected.has(session.session_id)} onChange={() => toggleSession(session.session_id)} disabled={running} />
                <span><strong>{session.lecture_title}</strong><small>{session.course_title}</small></span>
                <em className={crossReady ? "ready" : "source-only"}>{crossReady ? "图谱就绪" : "仅科研"}</em>
              </label>
            );
          })}
          {!loading && !filteredSessions.length && <p className="discover-muted">没有可选择的资料。</p>}
        </div>
        {incompatible.length > 0 && <p className="discover-warning">有 {incompatible.length} 份资料尚未完成图谱构建；请切换到科研证据分析，或先完成建图。</p>}
        {!canRun && <p className="discover-warning">当前角色为只读成员，不能启动模型任务。</p>}
        <button className="btn btn-accent discover-run" type="button" disabled={runDisabled} onClick={() => void runAnalysis()}>
          {running ? "分析运行中…" : mode === "scientific" ? "开始科研证据分析" : selected.size ? "开始跨资料发现" : "随机发现"}
        </button>

        <section className="discover-history">
          <div className="discover-history-head"><span>历史报告</span><b>{history.length}</b></div>
          <div className="discover-history-filters" aria-label="历史类型筛选">
            {(["all", "cross_corpus", "scientific_evidence"] as HistoryFilter[]).map((filter) => (
              <button type="button" className={clsx({ active: historyFilter === filter })} key={filter} onClick={() => setHistoryFilter(filter)}>
                {{ all: "全部", cross_corpus: "跨资料", scientific_evidence: "科研证据" }[filter]}
              </button>
            ))}
          </div>
          <div className="discover-history-list">
            {filteredHistory.map((item) => (
              <div className={clsx("discover-history-item", { active: activeReportId === item.report_id })} key={`${item.report_type}-${item.report_id}`}>
                <button type="button" onClick={() => void openHistory(item)} disabled={loadingReport}>
                  <span className={clsx("discover-kind", item.report_type)}>{item.report_type === "cross_corpus" ? "跨资料" : "科研证据"}</span>
                  <strong>{item.title}</strong>
                  <small>{historyMeta(item)}</small>
                  <time>{new Date(item.generated_at).toLocaleString("zh-CN")}</time>
                </button>
                {canDelete && <button type="button" className="discover-history-delete" aria-label={`删除历史报告 ${item.title}`} onClick={() => void removeHistory(item)}>×</button>}
              </div>
            ))}
            {!filteredHistory.length && <p className="discover-muted">暂无此类历史报告。</p>}
          </div>
        </section>
      </aside>

      <section className="discover-main">
        {loadingReport ? (
          <div className="discover-blank"><span>···</span><h2>正在加载报告</h2></div>
        ) : activeReport?.type === "cross_corpus" ? (
          <DiscoveryReportPanel
            report={activeReport.report}
            editable={canRun}
            showBridgeGraph={showBridgeGraph}
            onToggleBridge={() => setShowBridgeGraph((value) => !value)}
            onOpenConcept={(sessionId, conceptId) => navigate(`/session/${sessionId}?concept=${encodeURIComponent(conceptId)}`)}
            onProposalStatus={(proposalId, status) => void updateStatus(proposalId, status)}
            onDeepen={(proposalId) => void deepen(proposalId)}
            deepeningId={deepeningId}
            onProposalLocate={(proposalId) => document.getElementById(`proposal-${proposalId}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}
            onClose={() => setActiveReport(null)}
          />
        ) : activeReport?.type === "scientific_evidence" ? (
          <ScientificReportView report={activeReport.report} />
        ) : (
          <div className="discover-blank">
            <span>01</span>
            <h2>{mode === "cross" ? "发现资料之间的新连接" : "从论文中建立可核查证据"}</h2>
            <p>{mode === "cross" ? "选择资料后寻找桥接概念、创新提案与最小行动方案；未选择时可以随机探索。" : "选择科技文献后抽取主张、实验、指标与限制，并形成证据矩阵和研发决策卡。"}</p>
          </div>
        )}
      </section>
    </main>
  );
}
