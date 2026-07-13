import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { GraphArtifact } from "../../types";
import { SearchPanel } from "./SearchPanel";

const { searchGraph } = vi.hoisted(() => ({ searchGraph: vi.fn() }));
vi.mock("../../api/client", () => ({ searchGraph }));

const graph: GraphArtifact = {
  schema_version: "2.0",
  session_id: "s1",
  built_at: "2026-01-01T00:00:00Z",
  topic_clusters: [],
  edges: [],
  concepts: [
    {
      concept_id: "concept:tree",
      name: "二叉搜索树",
      canonical_name: "二叉搜索树",
      aliases: [],
      definition: "用于高效查找的树结构",
      summary: "查找结构",
      key_points: [],
      tags: ["数据结构"],
      prerequisites: [],
      applications: [],
      importance_score: 0.9,
      graph_metrics: {},
    },
  ],
};

describe("SearchPanel", () => {
  it("renders the parent-provided graph without fetching it again", () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SearchPanel sessionId="s1" graph={graph} />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("二叉搜索树")).not.toHaveLength(0);
    expect(searchGraph).not.toHaveBeenCalled();
  });
});
