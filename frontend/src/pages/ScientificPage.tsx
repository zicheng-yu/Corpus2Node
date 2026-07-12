import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  listScientificReports,
  listSessions,
  runScientificAnalysis,
} from "../api/client";
import type {
  CourseSession,
  ScientificEvidence,
  ScientificInsightType,
  ScientificReport,
} from "../types";
import { useToast } from "../components/primitives/Toast";
import "./ScientificPage.css";

const INSIGHT_LABELS: Record<ScientificInsightType, string> = {
  agreement: "一致证据",
  contradiction: "证据矛盾",
  research_gap: "研究空白",
  transfer_opportunity: "迁移机会",
  technical_lineage: "技术演进",
};

function isReady(session: CourseSession): boolean {
  return !session.lecture_title.startsWith("[总图谱] ") &&
    (session.status === "graph_ready" || session.status === "notes_ready");
}

function EvidenceLinks({ ids, report }: { ids: string[]; report: ScientificReport }) {
  const byId = useMemo(() => new Map(report.evidence.map((item) => [item.evidence_id, item])), [report]);
  const items = ids.map((id) => byId.get(id)).filter((item): item is ScientificEvidence => Boolean(item));
  if (!items.length) return null;
  return (
    <div className="science-evidence-list">
      {items.slice(0, 5).map((item) => (
        <details key={item.evidence_id} className="science-evidence">
          <summary>{item.locator}</summary>
          <p>{item.snippet}</p>
          <Link to={`/session/${item.session_id}`}>打开对应资料集</Link>
        </details>
      ))}
    </div>
  );
}

function ReportView({ report }: { report: ScientificReport }) {
  return (
    <div className="science-report">
      <header className="science-report-head">
        <div>
          <span className="science-eyebrow">R&amp;D EVIDENCE REPORT</span>
          <h2>{report.title_zh}</h2>
          <p>{report.objective_zh || "比较技术路线、实验结论与适用边界"}</p>
        </div>
        <div className="science-report-stats">
          <span><strong>{report.papers.length}</strong> 篇论文</span>
          <span><strong>{report.claims.length}</strong> 条主张</span>
          <span><strong>{report.evidence.length}</strong> 条证据</span>
          <span><strong>{report.insights.length}</strong> 个跨文献洞察</span>
        </div>
      </header>

      <section className="science-section">
        <h3>论文证据矩阵</h3>
        <div className="science-table-wrap">
          <table className="science-matrix">
            <thead><tr><th>论文</th><th>研究问题</th><th>核心方法</th><th>实验对象 / 指标</th><th>主要结果与边界</th></tr></thead>
            <tbody>
              {report.evidence_matrix.map((row) => (
                <tr key={row.session_id}>
                  <td><Link to={`/session/${row.session_id}`}>{row.paper_title}</Link></td>
                  <td>{row.research_problem_zh}</td>
                  <td>{row.core_methods.join("、") || "—"}</td>
                  <td>{[...row.datasets_or_environments, ...row.metrics].join("、") || "—"}</td>
                  <td>
                    <p>{row.main_result_zh}</p>
                    {row.limitations_zh.length > 0 && <p className="science-muted">边界：{row.limitations_zh.join("；")}</p>}
                    <EvidenceLinks ids={row.evidence_ids.slice(0, 2)} report={report} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="science-section">
        <h3>跨论文发现</h3>
        <div className="science-card-grid">
          {report.insights.map((insight) => (
            <article className="science-card" key={insight.insight_id}>
              <div className="science-card-meta">
                <span>{INSIGHT_LABELS[insight.insight_type]}</span>
                <span>置信度 {Math.round(insight.confidence * 100)}%</span>
              </div>
              <h4>{insight.title_zh}</h4>
              <p>{insight.summary_zh}</p>
              {insight.reasoning_zh && <p className="science-muted">判断依据：{insight.reasoning_zh}</p>}
              <EvidenceLinks ids={insight.evidence_ids} report={report} />
            </article>
          ))}
          {!report.insights.length && <p className="science-empty">本轮没有形成通过证据校验的跨论文洞察。</p>}
        </div>
      </section>

      <section className="science-section">
        <h3>研发决策卡</h3>
        <div className="science-decision-list">
          {report.decision_cards.map((card, index) => (
            <article className="science-decision" key={card.decision_id}>
              <span className="science-decision-num">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <h4>{card.title_zh}</h4>
                <p><strong>建议：</strong>{card.recommendation_zh}</p>
                <p><strong>理由：</strong>{card.rationale_zh}</p>
                <p className="science-next"><strong>最小验证实验：</strong>{card.next_experiment_zh}</p>
                {card.risks_zh.length > 0 && <p className="science-muted">风险：{card.risks_zh.join("；")}</p>}
                <EvidenceLinks ids={card.evidence_ids} report={report} />
              </div>
            </article>
          ))}
          {!report.decision_cards.length && <p className="science-empty">本轮没有形成通过证据校验的研发决策卡。</p>}
        </div>
      </section>
    </div>
  );
}

export function ScientificPage() {
  const [sessions, setSessions] = useState<CourseSession[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [objective, setObjective] = useState("比较多智能体强化学习中的价值分解路线、实验结论与适用边界");
  const [report, setReport] = useState<ScientificReport | null>(null);
  const [history, setHistory] = useState<ScientificReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const toast = useToast();

  useEffect(() => {
    Promise.all([listSessions(), listScientificReports()])
      .then(([sessionData, reportData]) => {
        const ready = sessionData.filter(isReady);
        setSessions(ready);
        const paperIds = ready.filter((item) => item.course_title === "demo: papers").map((item) => item.session_id);
        setSelected(new Set(paperIds.length >= 2 ? paperIds : ready.slice(0, 2).map((item) => item.session_id)));
        setHistory(reportData);
        if (reportData.length) setReport(reportData[0]);
      })
      .catch(() => toast("加载科研文献与历史报告失败", "error"))
      .finally(() => setLoading(false));
  }, [toast]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function run() {
    if (!selected.size) {
      toast("请至少选择一篇已建图的科技文献", "error");
      return;
    }
    setRunning(true);
    try {
      const next = await runScientificAnalysis({
        session_ids: [...selected],
        objective_zh: objective.trim(),
        language_mode: "zh_bilingual",
      });
      setReport(next);
      setHistory((current) => [next, ...current.filter((item) => item.report_id !== next.report_id)]);
      toast("科研证据分析完成", "success");
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "科研证据分析失败，请检查模型配置";
      toast(message, "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="scientific-page">
      <aside className="science-sidebar">
        <span className="science-eyebrow">SCIENTIFIC R&amp;D</span>
        <h1>科研证据图谱</h1>
        <p>从原始科技文献提取方法、实验、指标、结果与限制，跨论文发现证据关系和研发机会。</p>

        <label className="science-label" htmlFor="science-objective">研发分析目标</label>
        <textarea id="science-objective" rows={4} value={objective} onChange={(event) => setObjective(event.target.value)} maxLength={800} />

        <div className="science-label science-label-row"><span>选择文献</span><span>{selected.size} 篇</span></div>
        <div className="science-session-list">
          {loading && <p className="science-muted">正在加载…</p>}
          {sessions.map((session) => (
            <label className="science-session" key={session.session_id}>
              <input type="checkbox" checked={selected.has(session.session_id)} onChange={() => toggle(session.session_id)} />
              <span><strong>{session.lecture_title}</strong><small>{session.course_title} · {session.stats.chunk_count} 个原文块</small></span>
            </label>
          ))}
        </div>
        <button className="btn btn-accent science-run" type="button" onClick={run} disabled={running || loading}>
          {running ? "正在抽取与综合证据…" : "开始科研证据分析"}
        </button>
        <p className="science-run-note">中文叙述，英文正式名称独立保留；所有结论必须有原文定位。</p>

        {history.length > 0 && (
          <div className="science-history">
            <span className="science-label">历史报告</span>
            {history.slice(0, 8).map((item) => (
              <button type="button" key={item.report_id} className={report?.report_id === item.report_id ? "active" : ""} onClick={() => setReport(item)}>
                <strong>{item.title_zh}</strong>
                <small>{new Date(item.generated_at).toLocaleString("zh-CN")}</small>
              </button>
            ))}
          </div>
        )}
      </aside>

      <main className="science-main">
        {report ? <ReportView report={report} /> : (
          <div className="science-blank">
            <span>01</span><h2>选择科技文献并开始分析</h2>
            <p>系统将构建论文级证据结构，再做跨论文比较，不会把无出处的模型推断当成科研事实。</p>
          </div>
        )}
      </main>
    </div>
  );
}
