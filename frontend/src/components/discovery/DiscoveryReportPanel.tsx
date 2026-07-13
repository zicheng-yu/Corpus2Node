import { Suspense, lazy } from "react";
import clsx from "clsx";
import type {
  DiscoveryFinding,
  DiscoveryReport,
  InnovationProposal,
  ProposalStatus,
} from "../../types";

const BridgeGraphView = lazy(() =>
  import("./BridgeGraphView").then((module) => ({ default: module.BridgeGraphView })),
);

function TrashIcon() {
  return <span className="trash-icon" aria-hidden="true" />;
}

export function DiscoveryHistoryBar({
  history,
  activeId,
  onPick,
  onDelete,
}: {
  history: DiscoveryReport[];
  activeId?: string;
  onPick: (id: string) => void;
  onDelete: (report: DiscoveryReport) => void;
}) {
  return (
    <div className="discovery-history">
      <span className="discovery-history-label">历史发现 · {history.length}</span>
      <div className="discovery-history-list">
        {history.slice(0, 12).map((report) => (
          <div className="discovery-history-entry" key={report.discovery_id}>
            <button
              className={clsx("discovery-history-item", { active: report.discovery_id === activeId })}
              type="button"
              onClick={() => onPick(report.discovery_id)}
              title={`${report.title || report.discovery_id.slice(0, 8)} · ${new Date(report.generated_at).toLocaleString()}`}
            >
              <b>{report.title || report.discovery_id.slice(0, 8)}</b>
              <span>
                {report.mode === "random" ? "随机" : `${report.session_ids.length} 资料集`} ·{" "}
                {(report.proposals?.length ?? 0) > 0 ? `${report.proposals.length} 提案` : `${report.findings.length} 发现`}
              </span>
            </button>
            <button
              className="discovery-history-delete"
              type="button"
              onClick={() => onDelete(report)}
              aria-label={`删除历史发现 ${report.title || report.discovery_id.slice(0, 8)}`}
              title="删除历史发现"
            >
              <TrashIcon />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DiscoveryReportPanel({
  report,
  showBridgeGraph,
  onToggleBridge,
  onOpenConcept,
  onProposalStatus,
  onDeepen,
  deepeningId,
  onProposalLocate,
  onClose,
}: {
  report: DiscoveryReport;
  showBridgeGraph: boolean;
  onToggleBridge: () => void;
  onOpenConcept: (sessionId: string, conceptId: string) => void;
  onProposalStatus: (proposalId: string, status: ProposalStatus) => void;
  onDeepen: (proposalId: string) => void;
  deepeningId: string | null;
  onProposalLocate: (proposalId: string) => void;
  onClose: () => void;
}) {
  const hasBridge = report.bridge_graph.nodes.length > 0;
  const proposals = report.proposals ?? [];
  return (
    <section className="discovery-panel">
      <div className="discovery-panel-head">
        <div>
          <div className="discovery-report-title">{report.title || "知识发现"}</div>
          <div className="discovery-id">
            {proposals.length > 0 && `${proposals.length} 条提案 · `}
            {report.findings.length} 处交叉 · {report.discovery_id.slice(0, 8)}
          </div>
          {report.intent && <div className="discovery-intent-line">意图：{report.intent}</div>}
        </div>
        <div className="discovery-head-actions">
          <span className="discovery-graph-stat">
            {report.bridge_graph.nodes.length} 节点 / {report.bridge_graph.edges.length} 连接
          </span>
          {hasBridge && (
            <button className="discovery-mini-btn" type="button" onClick={onToggleBridge}>
              {showBridgeGraph ? "隐藏图" : "显示图"}
            </button>
          )}
          <button className="discovery-mini-btn" type="button" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
      {showBridgeGraph && hasBridge && (
        <div className="discovery-bridge-wrap">
          <Suspense fallback={<div className="bridge-graph" />}>
            <BridgeGraphView
              graph={report.bridge_graph}
              onConceptClick={onOpenConcept}
              onProposalClick={onProposalLocate}
            />
          </Suspense>
        </div>
      )}
      {proposals.length > 0 && (
        <>
          <div className="discovery-section-title">创新提案</div>
          <div className="discovery-list">
            {proposals.map((proposal) => (
              <ProposalCard
                key={proposal.proposal_id}
                proposal={proposal}
                deepening={deepeningId === proposal.proposal_id}
                onOpenConcept={onOpenConcept}
                onStatus={onProposalStatus}
                onDeepen={onDeepen}
              />
            ))}
          </div>
        </>
      )}
      {report.findings.length === 0 ? (
        <div className="discovery-empty">没有发现足够证据支撑的交叉点。</div>
      ) : (
        <>
          {proposals.length > 0 && <div className="discovery-section-title">支撑桥接点</div>}
          <div className="discovery-list">
            {report.findings.map((finding) => (
              <DiscoveryFindingCard key={finding.finding_id} finding={finding} onOpenConcept={onOpenConcept} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

const PROPOSAL_STATUS_LABEL: Record<ProposalStatus, string> = {
  new: "待定",
  kept: "已采纳",
  discarded: "已搁置",
};

// Overlapping chunks (sentence carry-over) can yield near-identical quotes; keep one.
function dedupEvidence<T extends { snippet: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = item.snippet.slice(0, 80);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// deep_dive lines look like "**目标**：…" — render the label bold instead of raw asterisks.
function DeepDiveLine({ line }: { line: string }) {
  const match = /^\*\*(.+?)\*\*\s*[:：]?\s*(.*)$/.exec(line);
  if (!match) return <div>{line}</div>;
  return (
    <div>
      <b>{match[1]}</b>：{match[2]}
    </div>
  );
}

function ProposalCard({
  proposal,
  deepening,
  onOpenConcept,
  onStatus,
  onDeepen,
}: {
  proposal: InnovationProposal;
  deepening: boolean;
  onOpenConcept: (sessionId: string, conceptId: string) => void;
  onStatus: (proposalId: string, status: ProposalStatus) => void;
  onDeepen: (proposalId: string) => void;
}) {
  const kept = proposal.status === "kept";
  const discarded = proposal.status === "discarded";
  return (
    <article
      id={`proposal-${proposal.proposal_id}`}
      className={clsx("discovery-card proposal-card", { "proposal-kept": kept, "proposal-discarded": discarded })}
    >
      <div className="discovery-card-top">
        <h2>{proposal.title}</h2>
        <span className={clsx("proposal-status", `proposal-status-${proposal.status}`)}>
          {PROPOSAL_STATUS_LABEL[proposal.status]}
        </span>
      </div>
      {proposal.pitch && <p className="discovery-summary proposal-pitch">{proposal.pitch}</p>}
      {proposal.combination && (
        <p className="proposal-row"><b>组合</b>{proposal.combination}</p>
      )}
      {proposal.first_step && (
        <p className="proposal-row"><b>第一步</b>{proposal.first_step}</p>
      )}
      {proposal.risks && (
        <p className="proposal-row proposal-risks"><b>风险</b>{proposal.risks}</p>
      )}
      <div className="discovery-participants">
        {proposal.sources.map((source) => (
          <button
            key={`${source.session_id}-${source.concept_id}`}
            className="discovery-chip-link"
            type="button"
            title="打开该资料集图谱并聚焦此知识点"
            onClick={() => onOpenConcept(source.session_id, source.concept_id)}
          >
            {source.lecture_title} · {source.concept_name}
          </button>
        ))}
      </div>
      {proposal.evidence.length > 0 && (
        <div className="discovery-evidence">
          {dedupEvidence(proposal.evidence).slice(0, 4).map((evidence, index) => {
            const clickable = Boolean(evidence.concept_id);
            return (
              <blockquote
                key={`${evidence.session_id}-${evidence.concept_id}-${evidence.chunk_id || index}`}
                className={clickable ? "discovery-evidence-link" : undefined}
                onClick={clickable ? () => onOpenConcept(evidence.session_id, evidence.concept_id) : undefined}
              >
                <b>{evidence.lecture_title} / {evidence.concept_name}</b>
                <span>{evidence.locator}</span>
                {evidence.snippet}
              </blockquote>
            );
          })}
        </div>
      )}
      {proposal.deep_dive && (
        <div className="proposal-deep-dive">
          {proposal.deep_dive.split("\n").map((line, index) => (
            <DeepDiveLine key={index} line={line} />
          ))}
        </div>
      )}
      <div className="proposal-actions">
        <button
          className={clsx("discovery-mini-btn", { "proposal-btn-active": kept })}
          type="button"
          onClick={() => onStatus(proposal.proposal_id, kept ? "new" : "kept")}
        >
          {kept ? "取消采纳" : "采纳"}
        </button>
        <button
          className={clsx("discovery-mini-btn", { "proposal-btn-active": discarded })}
          type="button"
          onClick={() => onStatus(proposal.proposal_id, discarded ? "new" : "discarded")}
        >
          {discarded ? "恢复" : "搁置"}
        </button>
        <button
          className="discovery-mini-btn"
          type="button"
          disabled={deepening}
          onClick={() => onDeepen(proposal.proposal_id)}
        >
          {deepening ? "深挖中…" : proposal.deep_dive ? "重新深挖" : "深挖"}
        </button>
        <span className="proposal-confidence">{Math.round(proposal.confidence * 100)}%</span>
      </div>
    </article>
  );
}

function DiscoveryFindingCard({
  finding,
  onOpenConcept,
}: {
  finding: DiscoveryFinding;
  onOpenConcept: (sessionId: string, conceptId: string) => void;
}) {
  return (
    <article className="discovery-card">
      <div className="discovery-card-top">
        <h2>{finding.title}</h2>
        <span>{Math.round(finding.confidence * 100)}%</span>
      </div>
      <div className="discovery-meta-row">
        <span>{relationLabel(finding.relation_type)}</span>
        <span>新颖度 {Math.round(finding.novelty * 100)}%</span>
      </div>
      <p className="discovery-summary">{finding.summary}</p>
      {finding.reasoning && <p className="discovery-reasoning">{finding.reasoning}</p>}
      <div className="discovery-participants">
        {finding.participants.map((participant) => (
          <button
            key={`${participant.session_id}-${participant.concept_id}`}
            className="discovery-chip-link"
            type="button"
            title="打开该资料集图谱并聚焦此知识点"
            onClick={() => onOpenConcept(participant.session_id, participant.concept_id)}
          >
            {participant.lecture_title} · {participant.concept_name}
          </button>
        ))}
      </div>
      <div className="discovery-evidence">
        {finding.evidence.slice(0, 4).map((evidence, index) => {
          const clickable = Boolean(evidence.concept_id);
          return (
            <blockquote
              key={`${evidence.session_id}-${evidence.concept_id}-${evidence.chunk_id || index}`}
              className={clickable ? "discovery-evidence-link" : undefined}
              onClick={clickable ? () => onOpenConcept(evidence.session_id, evidence.concept_id) : undefined}
              title={clickable ? "打开来源图谱并聚焦此知识点" : undefined}
            >
              <b>{evidence.lecture_title} / {evidence.concept_name}</b>
              <span>{evidence.locator}</span>
              {evidence.snippet}
            </blockquote>
          );
        })}
      </div>
    </article>
  );
}

function relationLabel(value: string): string {
  const labels: Record<string, string> = {
    same_under_different_terms: "异名同义",
    prerequisite: "前置依赖",
    complement: "互补",
    analogy: "类比",
    method_to_application: "方法迁移",
    contradiction: "矛盾张力",
    shared_context: "共同场景",
    open_question: "待探索问题",
  };
  return labels[value] ?? value;
}
