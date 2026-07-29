import { useEffect, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import type {
  ScientificEvidence,
  ScientificInsightType,
  ScientificReport,
} from "../../types";

const INSIGHT_LABELS: Record<ScientificInsightType, string> = {
  agreement: "一致证据",
  contradiction: "证据矛盾",
  research_gap: "研究空白",
  transfer_opportunity: "迁移机会",
  technical_lineage: "技术演进",
};

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

export function ScientificReportView({
  report,
  focus = "decision",
}: {
  report: ScientificReport;
  focus?: "decision" | "evidence";
}) {
  const evidenceRef = useRef<HTMLElement | null>(null);
  const decisionRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const target = focus === "evidence" ? evidenceRef.current : decisionRef.current;
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focus, report.report_id]);

  const evidenceSection = (
    <section className="science-section" ref={evidenceRef} id="science-evidence">
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
  );

  const insightsSection = (
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
  );

  const decisionSection = (
    <section className="science-section" ref={decisionRef} id="science-decision">
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
  );

  const body =
    focus === "evidence"
      ? [evidenceSection, insightsSection, decisionSection]
      : [decisionSection, evidenceSection, insightsSection];

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
      {body}
    </div>
  );
}
