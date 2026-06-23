import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getGraph } from "../../api/client";
import type { ConceptNode, GraphArtifact } from "../../types";
import "./ConceptDrawer.css";

const CLUSTER_COLORS = [
  "var(--accent)",
  "var(--info)",
  "var(--warn)",
  "var(--ok)",
  "var(--err)",
];

interface ConceptDrawerProps {
  sessionId: string;
  onClose?: () => void;
}

function SkeletonCard() {
  return (
    <div className="cd-card">
      <div className="cd-skeleton-line" style={{ width: "60%", height: 20, marginBottom: 12 }} />
      <div className="cd-skeleton-line" style={{ width: "100%" }} />
      <div className="cd-skeleton-line" style={{ width: "80%" }} />
      <div className="cd-skeleton-line" style={{ width: "90%" }} />
    </div>
  );
}

export function ConceptDrawer({ sessionId, onClose }: ConceptDrawerProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const conceptId = searchParams.get("concept");
  const [concept, setConcept] = useState<ConceptNode | null>(null);
  const [artifact, setArtifact] = useState<GraphArtifact | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!conceptId) {
      setConcept(null);
      setArtifact(null);
      return;
    }
    setLoading(true);
    getGraph(sessionId)
      .then((art) => {
        setArtifact(art);
        const c = art.concepts.find((c) => c.concept_id === conceptId);
        setConcept(c ?? null);
      })
      .catch(() => { setConcept(null); setArtifact(null); })
      .finally(() => setLoading(false));
  }, [sessionId, conceptId]);

  function close() {
    if (onClose) {
      onClose();
    } else {
      setSearchParams({});
    }
  }

  if (!conceptId) return null;

  // Find cluster for this concept
  const clusterIndex = artifact?.topic_clusters.findIndex((cl) =>
    cl.concept_ids.includes(conceptId ?? ""),
  ) ?? -1;
  const heroColor = clusterIndex >= 0 ? CLUSTER_COLORS[clusterIndex % CLUSTER_COLORS.length] : "var(--accent)";

  // Find neighbors from edges
  const outNeighbors: Array<{ id: string; name: string; type: string; relationType?: string }> = [];
  const inNeighbors: Array<{ id: string; name: string; type: string; relationType?: string }> = [];
  if (artifact && concept) {
    for (const edge of artifact.edges) {
      const relationType =
        typeof edge.properties?.relation_type === "string" ? edge.properties.relation_type : undefined;
      if (edge.source === conceptId) {
        const target = artifact.concepts.find((c) => c.concept_id === edge.target);
        if (target) outNeighbors.push({ id: target.concept_id, name: target.name, type: edge.edge_type, relationType });
      } else if (edge.target === conceptId) {
        const source = artifact.concepts.find((c) => c.concept_id === edge.source);
        if (source) inNeighbors.push({ id: source.concept_id, name: source.name, type: edge.edge_type, relationType });
      }
    }
  }

  return (
    <div className="concept-drawer">
      <button className="cd-close" onClick={close} type="button" aria-label="关闭">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>

      <div className="cd-scroll">
        {loading && <SkeletonCard />}

        {!loading && concept && (
          <>
            {/* Hero card */}
            <div
              className="cd-card cd-hero"
              style={{
                "--hero-color": heroColor,
                borderColor: `color-mix(in oklab, ${heroColor} 25%, var(--rule))`,
                background: `linear-gradient(135deg, color-mix(in oklab, ${heroColor} 22%, var(--panel)) 0%, color-mix(in oklab, ${heroColor} 10%, var(--panel)) 60%, var(--panel) 100%)`,
              } as React.CSSProperties}
            >
              <div className="cd-hero-meta">
                {clusterIndex >= 0 && (
                  <span className="cd-hero-tag">
                    <span className="cd-hero-tag-dot" style={{ background: heroColor }} />
                    {artifact?.topic_clusters[clusterIndex]?.title}
                  </span>
                )}
                <span className="cd-hero-imp">
                  重要性 {(concept.importance_score * 100).toFixed(0)}%
                </span>
              </div>
              <div className="cd-hero-title">{concept.name}</div>
              {concept.aliases.length > 0 && (
                <div className="cd-hero-aliases">
                  {concept.aliases.slice(0, 5).map((a) => (
                    <span key={a} className="cd-hero-alias">{a}</span>
                  ))}
                </div>
              )}
            </div>

            {/* Stats card */}
            <div className="cd-card cd-stats-card">
              <div className="cd-stat">
                <div className="cd-stat-num">{outNeighbors.length + inNeighbors.length}</div>
                <div className="cd-stat-label">关系</div>
              </div>
              <div className="cd-stat-div" />
              <div className="cd-stat">
                <div className="cd-stat-num">{concept.key_points.length}</div>
                <div className="cd-stat-label">要点</div>
              </div>
              <div className="cd-stat-div" />
              <div className="cd-stat">
                <div className="cd-stat-num">{concept.tags.length}</div>
                <div className="cd-stat-label">标签</div>
              </div>
            </div>

            {/* Definition */}
            {concept.definition && (
              <div className="cd-card">
                <div className="cd-card-label">
                  <span className="cd-label-bar" />
                  定义
                </div>
                <p className="cd-defn-text">{concept.definition}</p>
              </div>
            )}

            {concept.summary && (
              <div className="cd-card">
                <div className="cd-card-label">
                  <span className="cd-label-bar" />
                  概念摘要
                </div>
                <p className="cd-defn-text">{concept.summary}</p>
              </div>
            )}

            {concept.key_points.length > 0 && (
              <div className="cd-card">
                <div className="cd-card-label">
                  <span className="cd-label-bar" />
                  关键要点
                </div>
                <ul className="cd-bullet-list">
                  {concept.key_points.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            {concept.tags.length > 0 && (
              <div className="cd-card">
                <div className="cd-card-label">
                  <span className="cd-label-bar" />
                  标签
                </div>
                <div className="cd-hero-aliases">
                  {concept.tags.map((tag) => (
                    <span key={tag} className="cd-hero-alias">{tag}</span>
                  ))}
                </div>
              </div>
            )}

            {(concept.prerequisites.length > 0 || concept.applications.length > 0) && (
              <div className="cd-card">
                {concept.prerequisites.length > 0 && (
                  <div className="cd-mini-section">
                    <div className="cd-card-label">
                      <span className="cd-label-bar" />
                      前置概念
                    </div>
                    <ul className="cd-bullet-list">
                      {concept.prerequisites.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {concept.applications.length > 0 && (
                  <div className="cd-mini-section">
                    <div className="cd-card-label">
                      <span className="cd-label-bar" />
                      应用场景
                    </div>
                    <ul className="cd-bullet-list">
                      {concept.applications.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Neighbors */}
            {(outNeighbors.length > 0 || inNeighbors.length > 0) && (
              <div className="cd-card">
                <div className="cd-card-label">
                  <span className="cd-label-bar" />
                  关联概念
                  <span className="cd-label-count">{outNeighbors.length + inNeighbors.length}</span>
                </div>

                {outNeighbors.length > 0 && (
                  <div className="cd-neighbor-group">
                    <div className="cd-neighbor-group-label">指向</div>
                    {outNeighbors.slice(0, 6).map((n) => (
                        <NeighborRow
                          key={n.id}
                          name={n.name}
                          type={n.type}
                          relationType={n.relationType}
                          onClick={() => setSearchParams({ concept: n.id })}
                        />
                    ))}
                  </div>
                )}

                {inNeighbors.length > 0 && (
                  <div className="cd-neighbor-group">
                    <div className="cd-neighbor-group-label">被指向</div>
                    {inNeighbors.slice(0, 6).map((n) => (
                        <NeighborRow
                          key={n.id}
                          name={n.name}
                          type={n.type}
                          relationType={n.relationType}
                          onClick={() => setSearchParams({ concept: n.id })}
                        />
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {!loading && !concept && conceptId && (
          <div className="cd-card" style={{ color: "var(--ink-3)", fontFamily: "var(--font-ui)", fontSize: 14 }}>
            未找到概念数据
          </div>
        )}
      </div>
    </div>
  );
}

function NeighborRow({
  name,
  type,
  relationType,
  onClick,
}: {
  name: string;
  type: string;
  relationType?: string;
  onClick: () => void;
}) {
  const typeLabel: Record<string, string> = {
    RELATES_TO: "相关",
    CO_OCCURS_WITH: "共现",
    CONTAINS: "包含",
    MENTIONS: "提及",
  };
  const relationTypeLabel: Record<string, string> = {
    is_a: "属于",
    part_of: "部分-整体",
    prerequisite_of: "前置关系",
    causes: "导致",
    used_for: "用于",
    similar_to: "相似",
  };
  const label = type === "RELATES_TO"
    ? relationTypeLabel[relationType ?? ""] ?? typeLabel[type] ?? type
    : typeLabel[type] ?? type;
  return (
    <div className="cd-neighbor-row" onClick={onClick} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onClick()}>
      <span className="cd-neighbor-name">{name}</span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--ink-4)" }}>
        {label}
      </span>
    </div>
  );
}
