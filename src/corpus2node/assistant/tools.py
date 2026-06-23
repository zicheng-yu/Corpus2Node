"""Chat tools + the per-request retrieval context.

Tools are deterministic (the LLM only chooses which to call and how to phrase the
answer). Each tool records its structured results into the ChatContext so the
response's citations/subgraph are built from real retrieval data, not parsed text.
"""
from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.tools import tool

from corpus2node.core.types import ChatCitation, EvidenceChunk, GraphArtifact, RetrievalResult, SubgraphResponse
from corpus2node.index import search


class ChatContext:
    """Holds the session's graph/chunks/embedder and accumulates retrieval results."""

    def __init__(
        self,
        graph: GraphArtifact,
        chunks: list[EvidenceChunk],
        embeddings: Embeddings,
        *,
        chunk_limit: int = 6,
        concept_limit: int = 6,
        subgraph_depth: int = 1,
        subgraph_max_nodes: int = 20,
    ) -> None:
        self.graph = graph
        self.chunks = chunks
        self.embeddings = embeddings
        self.chunk_limit = chunk_limit
        self.concept_limit = concept_limit
        self.subgraph_depth = subgraph_depth
        self.subgraph_max_nodes = subgraph_max_nodes
        self.retrievals: list[RetrievalResult] = []
        self.subgraph: SubgraphResponse | None = None
        self._seen: set[tuple[str, str]] = set()

    def add(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        added: list[RetrievalResult] = []
        for result in results:
            key = (result.kind, result.ref_id)
            if key in self._seen:
                continue
            self._seen.add(key)
            self.retrievals.append(result)
            added.append(result)
        return added

    def index_of(self, result: RetrievalResult) -> int:
        return self.retrievals.index(result) + 1

    def citations(self) -> list[ChatCitation]:
        return [
            ChatCitation(
                index=position + 1,
                kind=result.kind,
                ref_id=result.ref_id,
                title=result.title,
                snippet=result.snippet,
                locator=result.locator,
                source_id=result.source_id,
                source_type=result.source_type,
            )
            for position, result in enumerate(self.retrievals)
        ]


def build_tools(ctx: ChatContext):
    @tool
    def retrieve_chunks(query: str) -> str:
        """检索与问题最相关的资料原文片段（chunk），用于回答并提供可溯源引用。"""
        return _format(ctx, search.retrieve_chunks(query, chunks=ctx.chunks, embeddings=ctx.embeddings, limit=ctx.chunk_limit))

    @tool
    def search_concepts(query: str) -> str:
        """检索与问题最相关的知识图谱概念（含定义），用于定位核心知识点。"""
        return _format(ctx, search.search_concepts(query, graph=ctx.graph, embeddings=ctx.embeddings, limit=ctx.concept_limit))

    @tool
    def get_subgraph(concept_id: str) -> str:
        """给定 concept_id，返回其邻域子图（相邻概念与关系），用于解释概念间关联。"""
        subgraph = search.get_subgraph(
            ctx.graph, concept_id, depth=ctx.subgraph_depth, max_nodes=ctx.subgraph_max_nodes
        )
        ctx.subgraph = subgraph
        if not subgraph.nodes:
            return f"未找到概念 {concept_id} 的子图。"
        names = "、".join(node.label for node in subgraph.nodes[:8])
        return f"子图：{len(subgraph.nodes)} 个概念 / {len(subgraph.edges)} 条关系。相关概念：{names}"

    return [retrieve_chunks, search_concepts, get_subgraph]


def _format(ctx: ChatContext, results: list[RetrievalResult]) -> str:
    added = ctx.add(results)
    if not added:
        return "（没有检索到新的相关内容）"
    lines: list[str] = []
    for result in added:
        marker = ctx.index_of(result)
        locator = f"（{result.locator}）" if result.locator else ""
        # surface concept_id so the agent can pass it to get_subgraph
        ref = f" [concept_id={result.ref_id}]" if result.kind == "concept" else ""
        lines.append(f"[{marker}] {result.title}{locator}{ref}: {result.snippet}")
    return "\n".join(lines)
