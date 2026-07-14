import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { resolveShare } from "../api/client";
import type { DiscoveryReport, GraphArtifact, ScientificReport, ShareSnapshot } from "../types";
import "./AccountPage.css";

const ConceptGraph = lazy(() =>
  import("../components/graph/ConceptGraph").then((module) => ({ default: module.ConceptGraph })),
);

function graphFrom(snapshot: ShareSnapshot): GraphArtifact | null {
  const value = snapshot.payload.graph;
  if (!value || typeof value !== "object" || !("concepts" in value)) return null;
  return value as GraphArtifact;
}

function scientificFrom(snapshot: ShareSnapshot): ScientificReport | null {
  if (!("decision_cards" in snapshot.payload) || !("insights" in snapshot.payload)) return null;
  return snapshot.payload as unknown as ScientificReport;
}

function discoveryFrom(snapshot: ShareSnapshot): DiscoveryReport | null {
  if (!("proposals" in snapshot.payload) || !("findings" in snapshot.payload)) return null;
  return snapshot.payload as unknown as DiscoveryReport;
}

export function SharePage() {
  const token = useMemo(() => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "", []);
  const [snapshot, setSnapshot] = useState<ShareSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) {
      setError("分享链接缺少 token。");
      return;
    }
    let active = true;
    resolveShare(token)
      .then((value) => {
        if (active) setSnapshot(value);
      })
      .catch(() => {
        if (active) setError("分享链接不存在、已撤销、已过期或目标已归档。");
      });
    window.history.replaceState(null, "", "/share");
    return () => {
      active = false;
    };
  }, [token]);

  const graph = snapshot ? graphFrom(snapshot) : null;
  const scientific = snapshot ? scientificFrom(snapshot) : null;
  const discovery = snapshot ? discoveryFrom(snapshot) : null;

  return (
    <main className="account-page">
      <div className="share-shell">
        <div className="account-brand"><span className="brand-mark" /> corpus2node · 只读快照</div>
        {error && <div className="account-error" role="alert">{error}</div>}
        {!snapshot && !error && <div className="empty-panel">正在验证分享链接…</div>}
        {snapshot && (
          <>
            <header className="collection-head"><div><h1>{snapshot.title}</h1><p className="account-muted">该页面是固定版本，不会随团队后续修改自动变化。</p></div></header>
            <div className="share-expiry">有效至 {new Date(snapshot.expires_at).toLocaleString()}</div>
            {graph && <div className="project-graph"><Suspense fallback={<div className="empty-panel">加载图谱…</div>}><ConceptGraph artifact={graph} /></Suspense></div>}
            {scientific && <div className="card-list">
              {scientific.insights.map((insight) => <article className="content-card" key={insight.insight_id}><h3>{insight.title_zh}</h3><p>{insight.summary_zh}</p></article>)}
              {scientific.decision_cards.map((card) => <article className="content-card" key={card.decision_id}><h3>{card.title_zh}</h3><p>{card.recommendation_zh}</p><p><strong>下一步实验：</strong>{card.next_experiment_zh}</p></article>)}
            </div>}
            {discovery && <div className="card-list">
              {discovery.findings.map((finding) => <article className="content-card" key={finding.finding_id}><h3>{finding.title}</h3><p>{finding.summary}</p></article>)}
              {discovery.proposals.map((proposal) => <article className="content-card" key={proposal.proposal_id}><h3>{proposal.title}</h3><p>{proposal.pitch}</p><p><strong>第一步：</strong>{proposal.first_step}</p></article>)}
            </div>}
          </>
        )}
      </div>
    </main>
  );
}
