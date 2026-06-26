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

// Tripartite left→right layout following edge direction: finding → concept → session.
const COL_X: Record<string, number> = { finding: 0, concept: 300, session: 600 };
const ROW_GAP = 80;
const NODE_W = 176;

const NODE_STYLE: Record<string, CSSProperties> = {
  finding: { background: "var(--accent-soft)", border: "1px solid var(--accent)", color: "var(--ink)", fontWeight: 600 },
  concept: { background: "var(--panel)", border: "1px solid var(--rule)", color: "var(--ink-2)", cursor: "pointer" },
  session: { background: "var(--panel-2)", border: "1px dashed var(--rule)", color: "var(--ink-3)" },
};

interface NodeData {
  label: string;
  nodeType: string;
  sessionId?: string;
  conceptId?: string;
}

function clip(text: string, max = 22): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function buildFlow(graph: DiscoveryBridgeGraph): { nodes: Node<NodeData>[]; edges: Edge[] } {
  const byType: Record<string, typeof graph.nodes> = { finding: [], concept: [], session: [] };
  for (const node of graph.nodes) (byType[node.node_type] ??= []).push(node);

  const nodes: Node<NodeData>[] = [];
  for (const type of ["finding", "concept", "session"] as const) {
    const list = byType[type] ?? [];
    const offset = ((list.length - 1) * ROW_GAP) / 2;
    list.forEach((node, index) => {
      const meta = (node.metadata ?? {}) as Record<string, unknown>;
      nodes.push({
        id: node.id,
        position: { x: COL_X[type] ?? 300, y: index * ROW_GAP - offset },
        data: {
          label: clip(node.label),
          nodeType: node.node_type,
          sessionId: node.session_id ?? undefined,
          conceptId: typeof meta.concept_id === "string" ? meta.concept_id : undefined,
        },
        style: {
          ...NODE_STYLE[node.node_type],
          width: NODE_W,
          padding: "6px 10px",
          borderRadius: node.node_type === "concept" ? 999 : 10,
          fontSize: 12,
          fontFamily: "var(--font-ui)",
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        connectable: false,
        draggable: false,
      });
    });
  }

  const edges: Edge[] = graph.edges.map((edge, index) => {
    const structural = edge.edge_type === "from_session";
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

  return { nodes, edges };
}

export function BridgeGraphView({
  graph,
  onConceptClick,
}: {
  graph: DiscoveryBridgeGraph;
  onConceptClick: (sessionId: string, conceptId: string) => void;
}) {
  const { nodes, edges } = useMemo(() => buildFlow(graph), [graph]);
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
          }
        }}
      >
        <Background color="var(--border-color)" gap={18} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <div className="bridge-graph-legend">
        <span><i className="bridge-dot bridge-dot-finding" />发现</span>
        <span><i className="bridge-dot bridge-dot-concept" />知识点（可点击溯源）</span>
        <span><i className="bridge-dot bridge-dot-session" />资料集</span>
      </div>
    </div>
  );
}
