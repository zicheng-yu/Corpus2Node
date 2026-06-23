import { type Node, type Edge } from "reactflow";

// NODE GEOMETRY: each node renders a 36×36 ring centered in a 120px-wide container.
// The ring center is at (60, 18) relative to the node's top-left.
// Layout coordinates here are node-center coordinates; we subtract (60, 18) at output.
// Use 140px as the minimum safe spacing between two node centers.

const NODE_CX = 60; // ring center x within node container
const NODE_CY = 18; // ring center y within node container

// ─── Force-directed layout ───────────────────────────────────────────────────
// Uses Fruchterman-Reingold with a fixed k so the spread doesn't blow up for
// small graphs, and strong gravity to keep everything visible in the viewport.

export function layoutWithForce(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  if (nodes.length === 0) return { nodes, edges };
  if (nodes.length === 1) {
    return { nodes: [{ ...nodes[0], position: { x: -NODE_CX, y: -NODE_CY } }], edges };
  }

  // Fixed repulsion constant – independent of canvas size so the graph
  // doesn't scatter for small N.
  const k = 80;
  const ITERATIONS = 120;

  // Initialize on a tight circle so iterations converge faster.
  const pos = new Map<string, { x: number; y: number }>();
  nodes.forEach((n, i) => {
    const angle = (i / nodes.length) * Math.PI * 2;
    pos.set(n.id, {
      x: Math.cos(angle) * k * 0.6,
      y: Math.sin(angle) * k * 0.6,
    });
  });

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const disp = new Map<string, { x: number; y: number }>();
    nodes.forEach((n) => disp.set(n.id, { x: 0, y: 0 }));

    // Repulsion between every pair
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const pU = pos.get(nodes[i].id)!;
        const pV = pos.get(nodes[j].id)!;
        const dx = pU.x - pV.x;
        const dy = pU.y - pV.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const f = (k * k) / dist;
        const nx = (dx / dist) * f;
        const ny = (dy / dist) * f;
        disp.get(nodes[i].id)!.x += nx;
        disp.get(nodes[i].id)!.y += ny;
        disp.get(nodes[j].id)!.x -= nx;
        disp.get(nodes[j].id)!.y -= ny;
      }
    }

    // Attraction along edges (spring)
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    edges.forEach((e) => {
      if (!nodeById.has(e.source) || !nodeById.has(e.target)) return;
      const pU = pos.get(e.source)!;
      const pV = pos.get(e.target)!;
      const dx = pU.x - pV.x;
      const dy = pU.y - pV.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const f = (dist * dist) / k;
      const nx = (dx / dist) * f;
      const ny = (dy / dist) * f;
      disp.get(e.source)!.x -= nx;
      disp.get(e.source)!.y -= ny;
      disp.get(e.target)!.x += nx;
      disp.get(e.target)!.y += ny;
    });

    // Gravity toward origin – stronger than typical to keep graph compact
    nodes.forEach((n) => {
      const p = pos.get(n.id)!;
      disp.get(n.id)!.x -= p.x * 0.20;
      disp.get(n.id)!.y -= p.y * 0.20;
    });

    // Apply displacement with temperature cooling
    const t = Math.max(2, ((ITERATIONS - iter) / ITERATIONS) * 28);
    nodes.forEach((n) => {
      const d = disp.get(n.id)!;
      const p = pos.get(n.id)!;
      const len = Math.sqrt(d.x * d.x + d.y * d.y);
      if (len > 0) {
        p.x += (d.x / len) * Math.min(len, t);
        p.y += (d.y / len) * Math.min(len, t);
      }
    });
  }

  return {
    nodes: nodes.map((n) => ({
      ...n,
      position: { x: pos.get(n.id)!.x - NODE_CX, y: pos.get(n.id)!.y - NODE_CY },
    })),
    edges,
  };
}

// ─── Radial layout ────────────────────────────────────────────────────────────
// Highest-degree node at center. Remaining nodes placed on concentric rings,
// with arc spacing ≥ MIN_ARC_SPACING to prevent overlap.

export function layoutWithRadial(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  if (nodes.length === 0) return { nodes, edges };
  if (nodes.length === 1) {
    return { nodes: [{ ...nodes[0], position: { x: -NODE_CX, y: -NODE_CY } }], edges };
  }

  // Sort by degree (descending) so the hub is at center.
  const degree = new Map<string, number>();
  nodes.forEach((n) => degree.set(n.id, 0));
  edges.forEach((e) => {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  });
  const sorted = [...nodes].sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0));

  const MIN_ARC_SPACING = 200; // px – minimum arc length between node centers
  const FIRST_RING_R = 200;    // px – radius of the first ring
  const RING_GAP = 180;        // px – distance between consecutive rings

  const pos = new Map<string, { x: number; y: number }>();
  pos.set(sorted[0].id, { x: 0, y: 0 });

  let remaining = sorted.slice(1);
  let currentR = FIRST_RING_R;

  while (remaining.length > 0) {
    // How many nodes fit on this ring without overlapping?
    const maxFit = Math.max(1, Math.floor((2 * Math.PI * currentR) / MIN_ARC_SPACING));
    const count = Math.min(maxFit, remaining.length);

    for (let i = 0; i < count; i++) {
      // Offset by -π/2 so the first node is at the top, not the right.
      const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
      pos.set(remaining[i].id, {
        x: Math.cos(angle) * currentR,
        y: Math.sin(angle) * currentR,
      });
    }

    remaining = remaining.slice(count);
    currentR += RING_GAP;
  }

  return {
    nodes: nodes.map((n) => ({
      ...n,
      position: { x: pos.get(n.id)!.x - NODE_CX, y: pos.get(n.id)!.y - NODE_CY },
    })),
    edges,
  };
}

// ─── Cluster layout ──────────────────────────────────────────────────────────
// Nodes are grouped by their color (topic cluster). Each group is arranged on
// its own circle. Cluster circles are spaced far enough apart that they never
// overlap each other.

export function layoutWithCluster(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  if (nodes.length === 0) return { nodes, edges };

  // Group nodes by cluster color.
  const clusterMap = new Map<string, Node[]>();
  nodes.forEach((n) => {
    const key = (n.data?.color as string) || "default";
    if (!clusterMap.has(key)) clusterMap.set(key, []);
    clusterMap.get(key)!.push(n);
  });

  const clusters = Array.from(clusterMap.values());
  const numClusters = clusters.length;

  // Minimum arc spacing between nodes within one cluster.
  const MIN_NODE_SPACING = 130; // px

  // Inner radius for each cluster – derived from how many nodes it has,
  // ensuring no two nodes overlap within the cluster.
  const innerRadii = clusters.map((cl) => {
    if (cl.length <= 1) return 0;
    // Circumference = count × MIN_NODE_SPACING → R = C / (2π)
    return Math.max(120, (cl.length * MIN_NODE_SPACING) / (2 * Math.PI));
  });

  // The "footprint" of a cluster is innerRadius + half a node width (padding).
  const NODE_PAD = 40;
  const footprints = innerRadii.map((r) => r + NODE_PAD);
  const maxFootprint = Math.max(...footprints);

  // Distance from origin to each cluster center:
  // two adjacent clusters must not overlap → distance ≥ footprint₁ + footprint₂.
  // Use the worst-case pair (both at maxFootprint) plus generous padding.
  const CLUSTER_PADDING = 5;
  const clusterCenterR =
    numClusters <= 1 ? 0 : maxFootprint * 2 + CLUSTER_PADDING;

  const pos = new Map<string, { x: number; y: number }>();

  clusters.forEach((clusterNodes, ci) => {
    // Cluster center – evenly distributed on a circle, starting at top.
    const clusterAngle = numClusters === 1 ? 0 : (ci / numClusters) * Math.PI * 2 - Math.PI / 2;
    const cx = numClusters === 1 ? 0 : Math.cos(clusterAngle) * clusterCenterR;
    const cy = numClusters === 1 ? 0 : Math.sin(clusterAngle) * clusterCenterR;

    if (clusterNodes.length === 1) {
      pos.set(clusterNodes[0].id, { x: cx, y: cy });
    } else {
      const r = innerRadii[ci];
      clusterNodes.forEach((n, ni) => {
        const angle = (ni / clusterNodes.length) * Math.PI * 2 - Math.PI / 2;
        pos.set(n.id, {
          x: cx + Math.cos(angle) * r,
          y: cy + Math.sin(angle) * r,
        });
      });
    }
  });

  return {
    nodes: nodes.map((n) => ({
      ...n,
      position: { x: pos.get(n.id)!.x - NODE_CX, y: pos.get(n.id)!.y - NODE_CY },
    })),
    edges,
  };
}
