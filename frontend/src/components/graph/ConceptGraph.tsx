import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  useNodesState,
  useEdgesState,
} from "reactflow";
import { layoutWithForce, layoutWithRadial, layoutWithCluster } from "./layoutUtils";
import "reactflow/dist/style.css";

import { getGraph, fetchSubgraph } from "../../api/client";
import type { GraphArtifact, SubgraphResponse } from "../../types";
import "./ConceptGraph.css";

interface GraphProps {
  sessionId: string;
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

function ConceptBubbleNode({ data }: NodeProps<{ label: string; color: string; selected?: boolean }>) {
  return (
    <div className="concept-bubble-node">
      <Handle type="target" position={Position.Left} className="concept-handle concept-handle-left" />
      <div
        className="concept-bubble-ring"
        style={{
          borderColor: data.color,
          boxShadow: data.selected ? `0 0 0 5px color-mix(in oklab, ${data.color} 18%, transparent)` : undefined,
        }}
      />
      <div className="concept-bubble-label">{data.label}</div>
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
  filterNodeIds?: Set<string> | null
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
    .filter((e) => shownIds.has(e.source) && shownIds.has(e.target))
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

function subgraphToFlow(sub: SubgraphResponse, graphStyle: string): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = sub.nodes.map((n) => {
    if (n.node_type === "concept") {
      return {
        id: n.id,
        type: "conceptBubble",
        data: {
          label: n.label,
          nodeType: n.node_type,
          color: n.id === sub.center_concept_id ? "#b85229" : "#2f63d6",
          selected: n.id === sub.center_concept_id,
        },
        position: { x: 0, y: 0 },
      };
    }
    return {
      id: n.id,
      type: "default",
      data: { label: n.label, nodeType: n.node_type },
      position: { x: 0, y: 0 },
    };
  });

  const edges: Edge[] = sub.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    type: "straight",
    style: {
      stroke: EDGE_COLORS[e.edge_type] ?? "rgba(136, 124, 105, 0.18)",
      strokeWidth: e.edge_type === "RELATES_TO" ? 1.8 : 0.9,
    },
  }));

  return applyLayout(nodes, edges, graphStyle);
}

export function ConceptGraph({ sessionId, graphStyle = "force", filterNodeIds, onDrillDown, onConceptSelect }: GraphProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const conceptId = searchParams.get("concept");
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [empty, setEmpty] = useState(false);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        if (conceptId) {
          const sub = await fetchSubgraph(sessionId, conceptId, 2);
          const { nodes, edges } = subgraphToFlow(sub, graphStyle);
          setRfNodes(nodes);
          setRfEdges(edges);
          setEmpty(nodes.length === 0);
        } else {
          const artifact = await getGraph(sessionId);
          if (artifact.concepts.length === 0) { setEmpty(true); setLoading(false); return; }
          const { nodes, edges } = artifactToFlow(artifact, graphStyle, filterNodeIds);
          setRfNodes(nodes);
          setRfEdges(edges);
          setEmpty(false);
        }
      } catch {
        setEmpty(true);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [sessionId, conceptId, graphStyle, filterNodeIds, setRfNodes, setRfEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.data?.nodeType !== "concept") return;
      if (onDrillDown && filterNodeIds) {
        onDrillDown(node.id);
        return;
      }
      if (conceptId === node.id) {
        setSearchParams({});
      } else {
        setSearchParams({ concept: node.id });
      }
      if (onConceptSelect) {
        onConceptSelect(node.id);
      }
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
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
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
      </ReactFlow>
    </div>
  );
}
