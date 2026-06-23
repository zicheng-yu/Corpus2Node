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

  // Isolated nodes (no edges) get pulled far out by repulsion alone, blowing up
  // the bounding box so fitView shrinks the whole graph. Keep them OUT of the
  // force sim and tile them compactly beside the connected core instead.
  const degree = new Map<string, number>();
  nodes.forEach((n) => degree.set(n.id, 0));
  edges.forEach((e) => {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  });
  const core = nodes.filter((n) => (degree.get(n.id) ?? 0) > 0);
  const isolated = nodes.filter((n) => (degree.get(n.id) ?? 0) === 0);
  const sim = core.length >= 2 ? core : nodes; // if nothing connected, lay all out as grid below

  // Optimal node distance scales with N so a big graph spreads out (fixes the
  // crowded blob) instead of packing at a fixed k.
  const k = Math.min(320, Math.max(110, 34 * Math.sqrt(sim.length)));
  const ITERATIONS = 160;

  // Cluster key per node (topic-cluster color). Same-cluster nodes get a gentle
  // pull toward their cluster centroid so classes cohere instead of scattering.
  const clusterOf = (n: Node) => (n.data?.color as string) ?? "_";

  // Seed nodes near their cluster's slot so clusters start separated.
  const clusterKeys = Array.from(new Set(sim.map(clusterOf)));
  const clusterSeed = new Map(
    clusterKeys.map((key, i) => {
      const a = (i / Math.max(1, clusterKeys.length)) * Math.PI * 2;
      return [key, { x: Math.cos(a) * k, y: Math.sin(a) * k }];
    }),
  );
  const pos = new Map<string, { x: number; y: number }>();
  sim.forEach((n, i) => {
    const seed = clusterSeed.get(clusterOf(n))!;
    pos.set(n.id, { x: seed.x + Math.cos(i) * 12, y: seed.y + Math.sin(i) * 12 });
  });

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const disp = new Map<string, { x: number; y: number }>();
    sim.forEach((n) => disp.set(n.id, { x: 0, y: 0 }));

    // Per-cluster centroids (recomputed each iteration).
    const cSum = new Map<string, { x: number; y: number; n: number }>();
    sim.forEach((n) => {
      const key = clusterOf(n);
      const p = pos.get(n.id)!;
      const acc = cSum.get(key) ?? { x: 0, y: 0, n: 0 };
      acc.x += p.x; acc.y += p.y; acc.n += 1;
      cSum.set(key, acc);
    });

    // Repulsion between every pair
    for (let i = 0; i < sim.length; i++) {
      for (let j = i + 1; j < sim.length; j++) {
        const pU = pos.get(sim[i].id)!;
        const pV = pos.get(sim[j].id)!;
        const dx = pU.x - pV.x;
        const dy = pU.y - pV.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const f = (k * k) / dist;
        const nx = (dx / dist) * f;
        const ny = (dy / dist) * f;
        disp.get(sim[i].id)!.x += nx;
        disp.get(sim[i].id)!.y += ny;
        disp.get(sim[j].id)!.x -= nx;
        disp.get(sim[j].id)!.y -= ny;
      }
    }

    // Attraction along edges (spring)
    const nodeById = new Map(sim.map((n) => [n.id, n]));
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

    // Cluster cohesion: pull each node gently toward its cluster centroid so
    // same-class nodes group together (counters over-dispersion).
    sim.forEach((n) => {
      const acc = cSum.get(clusterOf(n))!;
      const cx = acc.x / acc.n;
      const cy = acc.y / acc.n;
      const p = pos.get(n.id)!;
      disp.get(n.id)!.x += (cx - p.x) * 0.10;
      disp.get(n.id)!.y += (cy - p.y) * 0.10;
    });

    // Weak gravity toward origin keeps the whole graph framed (fitView handles
    // the final viewport), without crushing everything into a blob.
    sim.forEach((n) => {
      const p = pos.get(n.id)!;
      disp.get(n.id)!.x -= p.x * 0.04;
      disp.get(n.id)!.y -= p.y * 0.04;
    });

    // Apply displacement with temperature cooling
    const t = Math.max(2, ((ITERATIONS - iter) / ITERATIONS) * 28);
    sim.forEach((n) => {
      const d = disp.get(n.id)!;
      const p = pos.get(n.id)!;
      const len = Math.sqrt(d.x * d.x + d.y * d.y);
      if (len > 0) {
        p.x += (d.x / len) * Math.min(len, t);
        p.y += (d.y / len) * Math.min(len, t);
      }
    });
  }

  // Tile isolated nodes in a compact grid just beneath the connected core, so
  // they stay near the graph instead of being flung out.
  if (core.length >= 2 && isolated.length > 0) {
    let minX = Infinity, maxX = -Infinity, maxY = -Infinity, minY = Infinity;
    for (const n of sim) {
      const p = pos.get(n.id)!;
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    }
    const spacing = 95;
    const cols = Math.max(1, Math.min(isolated.length, Math.round((maxX - minX) / spacing) || 1));
    const startX = (minX + maxX) / 2 - ((cols - 1) * spacing) / 2;
    const startY = maxY + spacing;
    isolated.forEach((n, i) => {
      pos.set(n.id, { x: startX + (i % cols) * spacing, y: startY + Math.floor(i / cols) * spacing });
    });
  }

  return {
    nodes: nodes.map((n) => ({
      ...n,
      position: { x: (pos.get(n.id)?.x ?? 0) - NODE_CX, y: (pos.get(n.id)?.y ?? 0) - NODE_CY },
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

  // Distance from origin to each cluster center. Adjacent centers on the ring are
  // 2·R·sin(π/numClusters) apart; require that ≥ 2·maxFootprint so clusters just
  // avoid overlap — tight for few clusters, correct for many (was a loose 2× blowup).
  const CLUSTER_PADDING = 40;
  const clusterCenterR =
    numClusters <= 1 ? 0 : maxFootprint / Math.sin(Math.PI / numClusters) + CLUSTER_PADDING;

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
