import { useMemo } from "react";
import type { CSSProperties } from "react";
import ReactFlow, {
  Background,
  Controls,
  Position,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";

import type { DiscoveryBridgeGraph } from "../../types";
import "./BridgeGraphView.css";

// Two layouts share one component, keyed by which node types the graph carries:
// - proposal-centric (v2): session(部门) → concept(桥接概念) → proposal(创新提案)
// - legacy finding-centric (old saved reports): finding → concept → session
const COL_X_PROPOSAL: Record<string, number> = { session: 0, concept: 300, proposal: 620 };
const COL_X_LEGACY: Record<string, number> = { finding: 0, concept: 300, session: 600 };
const ROW_GAP = 80;
const NODE_W = 176;
const PROPOSAL_W = 230;

const NODE_STYLE: Record<string, CSSProperties> = {
  finding: { background: "var(--accent-soft)", border: "1px solid var(--accent)", color: "var(--ink)", fontWeight: 600 },
  proposal: { background: "var(--accent-soft)", border: "1px solid var(--accent)", color: "var(--ink)", fontWeight: 600, cursor: "pointer" },
  concept: { background: "var(--panel)", border: "1px solid var(--rule)", color: "var(--ink-2)", cursor: "pointer" },
  session: { background: "var(--panel-2)", border: "1px dashed var(--rule)", color: "var(--ink-3)" },
};

interface NodeData {
  label: string;
  nodeType: string;
  sessionId?: string;
  conceptId?: string;
  proposalId?: string;
}

function clip(text: string, max = 22): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function buildFlow(graph: DiscoveryBridgeGraph): { nodes: Node<NodeData>[]; edges: Edge[]; hasProposal: boolean } {
  const hasProposal = graph.nodes.some((node) => node.node_type === "proposal");
  const colX = hasProposal ? COL_X_PROPOSAL : COL_X_LEGACY;
  const columns = hasProposal ? (["session", "concept", "proposal"] as const) : (["finding", "concept", "session"] as const);

  const byType: Record<string, typeof graph.nodes> = {};
  for (const node of graph.nodes) (byType[node.node_type] ??= []).push(node);

  const nodes: Node<NodeData>[] = [];
  for (const type of columns) {
    const list = byType[type] ?? [];
    const gap = type === "proposal" ? ROW_GAP + 24 : ROW_GAP;
    const offset = ((list.length - 1) * gap) / 2;
    list.forEach((node, index) => {
      const meta = (node.metadata ?? {}) as Record<string, unknown>;
      const discarded = meta.status === "discarded";
      const kept = meta.status === "kept";
      nodes.push({
        id: node.id,
        position: { x: colX[type] ?? 300, y: index * gap - offset },
        data: {
          label: clip(node.label, type === "proposal" ? 26 : 22),
          nodeType: node.node_type,
          sessionId: node.session_id ?? undefined,
          conceptId: typeof meta.concept_id === "string" ? meta.concept_id : undefined,
          proposalId: typeof meta.proposal_id === "string" ? meta.proposal_id : undefined,
        },
        style: {
          ...NODE_STYLE[node.node_type],
          width: type === "proposal" ? PROPOSAL_W : NODE_W,
          padding: type === "proposal" ? "8px 12px" : "6px 10px",
          borderRadius: node.node_type === "concept" ? 999 : 10,
          fontSize: 12,
          fontFamily: "var(--font-ui)",
          ...(discarded ? { opacity: 0.45 } : {}),
          ...(kept ? { boxShadow: "0 0 0 2px var(--accent)" } : {}),
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        connectable: false,
        draggable: false,
      });
    });
  }

  const edges: Edge[] = graph.edges.map((edge, index) => {
    const structural = edge.edge_type === "from_session" || edge.edge_type === "provides";
    return {
      id: `bridge-edge-${index}`,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      animated: !structural,
      style: {
        stroke: structural ? "rgba(136,124,105,0.32)" : "rgba(184,93,48,0.6)",
        strokeWidth: structural ? 1 : 1.6,
      },
    };
  });

  return { nodes, edges, hasProposal };
}

export function BridgeGraphView({
  graph,
  onConceptClick,
  onProposalClick,
}: {
  graph: DiscoveryBridgeGraph;
  onConceptClick: (sessionId: string, conceptId: string) => void;
  onProposalClick?: (proposalId: string) => void;
}) {
  const { nodes, edges, hasProposal } = useMemo(() => buildFlow(graph), [graph]);
  if (graph.nodes.length === 0) return null;

  return (
    <div className="bridge-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          const data = node.data as NodeData;
          if (data.nodeType === "concept" && data.sessionId && data.conceptId) {
            onConceptClick(data.sessionId, data.conceptId);
          } else if (data.nodeType === "proposal" && data.proposalId && onProposalClick) {
            onProposalClick(data.proposalId);
          }
        }}
      >
        <Background color="var(--border-color)" gap={18} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <div className="bridge-graph-legend">
        {hasProposal ? (
          <>
            <span><i className="bridge-dot bridge-dot-session" />部门 / 资料集</span>
            <span><i className="bridge-dot bridge-dot-concept" />桥接概念（可点击溯源）</span>
            <span><i className="bridge-dot bridge-dot-finding" />创新提案（点击定位卡片）</span>
          </>
        ) : (
          <>
            <span><i className="bridge-dot bridge-dot-finding" />发现</span>
            <span><i className="bridge-dot bridge-dot-concept" />知识点（可点击溯源）</span>
            <span><i className="bridge-dot bridge-dot-session" />资料集</span>
          </>
        )}
      </div>
    </div>
  );
}
