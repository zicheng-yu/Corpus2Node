import { describe, expect, it } from "vitest";
import type { GraphArtifact } from "../../types";
import { artifactToFlow } from "./ConceptGraph";

describe("artifactToFlow", () => {
  it("keeps co-occurrence edges in the default force layout", () => {
    const artifact = {
      concepts: [
        { concept_id: "concept-a", name: "A" },
        { concept_id: "concept-b", name: "B" },
      ],
      topic_clusters: [],
      edges: [{
        edge_id: "edge-cooccurrence",
        source: "concept-a",
        target: "concept-b",
        edge_type: "CO_OCCURS_WITH",
      }],
    } as unknown as GraphArtifact;

    const result = artifactToFlow(artifact, "force");

    expect(result.edges.map((edge) => edge.id)).toEqual(["edge-cooccurrence"]);
  });
});
