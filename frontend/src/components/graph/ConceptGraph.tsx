import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MiniMap,
  Panel,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  type ReactFlowInstance,
  useNodesState,
  useEdgesState,
} from "reactflow";
import { layoutWithForce, layoutWithRadial, layoutWithCluster } from "./layoutUtils";
import "reactflow/dist/style.css";

import type { GraphArtifact } from "../../types";
import "./ConceptGraph.css";

const NODE_CX = 60;
const NODE_CY = 18;

interface GraphProps {
  artifact: GraphArtifact | null;
  graphStyle?: string;
  filterNodeIds?: Set<string> | null;
  onDrillDown?: (conceptId: string) => void;
  onConceptSelect?: (conceptId: string) => void;
}

const EDGE_COLORS: Record<string, string> = {
  RELATES_TO:      "rgba(184, 93, 48, 0.74)",
  CO_OCCURS_WITH:  "rgba(136, 124, 105, 0.18)",
  CONTAINS:        "rgba(63, 123, 80, 0.56)",
  MENTIONS:        "rgba(126, 118, 101, 0.24)",
};

const CLUSTER_COLORS = [
  "#2f63d6",
  "#b85229",
  "#3f7b50",
  "#c47a12",
  "#27221c",
  "#7a5c9e",
];

function ConceptBubbleNode({ data }: NodeProps<{ label: string; color: string; selected?: boolean; dimmed?: boolean }>) {
  return (
    <div className="concept-bubble-node" style={{ opacity: data.dimmed ? 0.22 : 1, transition: "opacity 0.25s" }}>
      <Handle type="target" position={Position.Left} className="concept-handle concept-handle-left" />
      <div
        className="concept-bubble-ring"
        style={{
          borderColor: data.color,
          borderWidth: data.selected ? 3 : undefined,
          boxShadow: data.selected ? `0 0 0 6px color-mix(in oklab, ${data.color} 22%, transparent)` : undefined,
        }}
      />
      <div className="concept-bubble-label" style={{ fontWeight: data.selected ? 700 : undefined }}>{data.label}</div>
      <Handle type="source" position={Position.Right} className="concept-handle concept-handle-right" />
    </div>
  );
}

const nodeTypes = { conceptBubble: ConceptBubbleNode };

function applyLayout(nodes: Node[], edges: Edge[], graphStyle: string) {
  switch (graphStyle) {
    case "radial": return layoutWithRadial(nodes, edges);
    case "cluster": return layoutWithCluster(nodes, edges);
    case "force": default: return layoutWithForce(nodes, edges);
  }
}

function artifactToFlow(
  artifact: GraphArtifact,
  graphStyle: string,
  filterNodeIds?: Set<string> | null,
  showCooccurrence = false,
): { nodes: Node[]; edges: Edge[] } {
  const clusterByConcept = new Map<string, number>();
  artifact.topic_clusters.forEach((cluster, index) => {
    cluster.concept_ids.forEach((conceptId) => clusterByConcept.set(conceptId, index));
  });

  const conceptsToShow = filterNodeIds
    ? artifact.concepts.filter((c) => filterNodeIds.has(c.concept_id))
    : artifact.concepts;

  const shownIds = new Set(conceptsToShow.map((c) => c.concept_id));

  const nodes: Node[] = conceptsToShow.map((c) => {
    const clusterIndex = clusterByConcept.get(c.concept_id) ?? -1;
    const color = CLUSTER_COLORS[(clusterIndex >= 0 ? clusterIndex : Math.abs(c.concept_id.length)) % CLUSTER_COLORS.length];
    return {
      id: c.concept_id,
      type: "conceptBubble",
      data: { label: c.name, nodeType: "concept", color },
      position: { x: 0, y: 0 },
    };
  });

  const edges: Edge[] = artifact.edges
    .filter(
      (e) =>
        shownIds.has(e.source)
        && shownIds.has(e.target)
        && (showCooccurrence || e.edge_type !== "CO_OCCURS_WITH"),
    )
    .map((e) => ({
      id: e.edge_id,
      source: e.source,
      target: e.target,
      style: {
        stroke: EDGE_COLORS[e.edge_type] ?? "rgba(136, 124, 105, 0.18)",
        strokeWidth: e.edge_type === "RELATES_TO" ? 1.8 : 0.9,
      },
      type: "straight",
      animated: false,
    }));

  return applyLayout(nodes, edges, graphStyle);
}

export function ConceptGraph({ artifact, graphStyle = "force", filterNodeIds, onDrillDown, onConceptSelect }: GraphProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const conceptId = searchParams.get("concept");
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [empty, setEmpty] = useState(false);
  const [showCooccurrence, setShowCooccurrence] = useState(false);
  const rfRef = useRef<ReactFlowInstance | null>(null);

  useEffect(() => {
    if (!artifact) {
      setLoading(true);
      return;
    }
    if (artifact.concepts.length === 0) {
      setEmpty(true);
      setLoading(false);
      return;
    }
    const { nodes, edges } = artifactToFlow(
      artifact,
      graphStyle,
      filterNodeIds,
      showCooccurrence,
    );
    setRfNodes(nodes);
    setRfEdges(edges);
    setEmpty(false);
    setLoading(false);
  }, [artifact, graphStyle, filterNodeIds, showCooccurrence, setRfNodes, setRfEdges]);

  // Neighbors of the selected concept (for highlight / dim).
  const neighbors = useMemo(() => {
    const set = new Set<string>();
    if (!conceptId) return set;
    for (const e of rfEdges) {
      if (e.source === conceptId) set.add(e.target);
      if (e.target === conceptId) set.add(e.source);
    }
    return set;
  }, [conceptId, rfEdges]);

  // Derive display nodes/edges with selection highlight + dimming.
  const displayNodes = useMemo(
    () =>
      rfNodes.map((n) => ({
        ...n,
        data: {
          ...n.data,
          selected: conceptId === n.id,
          dimmed: !!conceptId && n.id !== conceptId && !neighbors.has(n.id),
        },
      })),
    [rfNodes, conceptId, neighbors],
  );
  const displayEdges = useMemo(
    () =>
      rfEdges.map((e) => {
        const active = !conceptId || e.source === conceptId || e.target === conceptId;
        return { ...e, style: { ...e.style, opacity: active ? 1 : 0.12 } };
      }),
    [rfEdges, conceptId],
  );

  // Pan/zoom to the selected node (local zoom) instead of replacing the graph.
  useEffect(() => {
    if (!rfRef.current) return;
    if (!conceptId) {
      rfRef.current.fitView({ padding: 0.2, duration: 500 });
      return;
    }
    const node = rfNodes.find((n) => n.id === conceptId);
    if (node) {
      rfRef.current.setCenter(node.position.x + NODE_CX, node.position.y + NODE_CY, { zoom: 1.5, duration: 500 });
    }
  }, [conceptId, rfNodes]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.data?.nodeType !== "concept") return;
      if (onDrillDown && filterNodeIds) {
        onDrillDown(node.id);
        return;
      }
      setSearchParams(conceptId === node.id ? {} : { concept: node.id });
      onConceptSelect?.(node.id);
    },
    [conceptId, setSearchParams, onDrillDown, filterNodeIds, onConceptSelect],
  );

  if (loading) {
    return (
      <div className="concept-graph-wrap">
        <div className="graph-empty">加载图谱中…</div>
      </div>
    );
  }

  if (empty) {
    return (
      <div className="concept-graph-wrap">
        <div className="graph-empty">暂无图谱数据</div>
      </div>
    );
  }

  return (
    <div className="concept-graph-wrap">
      <ReactFlow
        nodeTypes={nodeTypes}
        nodes={displayNodes}
        edges={displayEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onInit={(inst) => (rfRef.current = inst)}
        onPaneClick={() => { if (conceptId) setSearchParams({}); }}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--border-color)" gap={20} />
        <Controls />
        <MiniMap
          nodeColor={() => "var(--accent-soft)"}
          maskColor="rgba(250,249,245,0.6)"
        />
        <Panel position="top-right">
          <button
            className="btn btn-secondary"
            type="button"
            aria-pressed={showCooccurrence}
            onClick={() => setShowCooccurrence((value) => !value)}
          >
            {showCooccurrence ? "隐藏共现边" : "显示共现边"}
          </button>
        </Panel>
      </ReactFlow>
    </div>
  );
}
