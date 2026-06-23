import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getGraph, searchGraph } from "../../api/client";
import { Input } from "../primitives/Input";
import { Pill } from "../primitives/Pill";
import { useDebouncedCallback } from "../../hooks/useDebouncedCallback";
import { useLocalStorage } from "../../hooks/useLocalStorage";
import type { ConceptNode, SearchResponse } from "../../types";
import "./SearchPanel.css";

type FilterKind = "all" | "concepts" | "chunks";

interface ContentListItem {
  key: string;
  conceptId: string;
  conceptName: string;
  text: string;
}

export function SearchPanel({ sessionId }: { sessionId: string }) {
  const [, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [filterKind, setFilterKind] = useState<FilterKind>("all");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [conceptsList, setConceptsList] = useState<ConceptNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [recentQueries, setRecentQueries] = useLocalStorage<string[]>(
    `c2n:recent:${sessionId}`,
    [],
  );
  const latestQuery = useRef("");

  const contentList = useMemo<ContentListItem[]>(
    () => conceptsList
      .map((concept) => ({
        key: concept.concept_id,
        conceptId: concept.concept_id,
        conceptName: concept.name,
        text: concept.summary || concept.definition || concept.key_points[0] || concept.name,
      }))
      .filter((item) => Boolean(item.text)),
    [conceptsList],
  );

  useEffect(() => {
    getGraph(sessionId)
      .then((graph) => {
        setConceptsList(
          [...graph.concepts].sort((a, b) => b.importance_score - a.importance_score),
        );
      })
      .catch(() => setConceptsList([]));
  }, [sessionId]);

  const doSearch = useCallback(
    async (q: string) => {
      if (!q.trim()) { setResults(null); return; }
      setLoading(true);
      try {
        const res = await searchGraph({ session_id: sessionId, query: q, limit: 12 });
        if (q === latestQuery.current) setResults(res);
      } catch {
        // silent
      } finally {
        setLoading(false);
      }
    },
    [sessionId],
  );

  const debouncedSearch = useDebouncedCallback(doSearch, 300);

  function handleInput(value: string) {
    setQuery(value);
    latestQuery.current = value;
    debouncedSearch(value);
  }

  function handleSubmit() {
    if (!query.trim()) return;
    doSearch(query);
    setRecentQueries([query, ...recentQueries.filter((q) => q !== query)].slice(0, 8));
  }

  const concepts = results?.concepts ?? [];

  const chunks = results?.chunks ?? [];

  const showConceptResults = filterKind !== "chunks";
  const showChunkResults = filterKind !== "concepts";
  const visibleSearchResultCount =
    (showConceptResults ? concepts.length : 0) + (showChunkResults ? chunks.length : 0);

  return (
    <div className="search-panel">
      <div className="search-input-row">
        <Input
          placeholder="搜索知识点、内容…"
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
        />
      </div>

      <div className="search-filters">
        {(["all", "concepts", "chunks"] as FilterKind[]).map((k) => (
          <Pill key={k} active={filterKind === k} onClick={() => setFilterKind(k)}>
            {{ all: "全部", concepts: "知识点", chunks: "内容片段" }[k]}
          </Pill>
        ))}
      </div>

      {!query && filterKind !== "chunks" && (
        <div className="concept-list">
          <div className="search-section-label">知识点列表 ({conceptsList.length})</div>
          {conceptsList.map((concept) => (
            <button
              key={concept.concept_id}
              className="concept-list-row"
              onClick={() => setSearchParams({ concept: concept.concept_id })}
              type="button"
            >
              <span className="concept-list-name">{concept.name}</span>
              <span className="concept-list-meta">
                重要性 {Math.round(concept.importance_score * 100)}%
                {concept.tags.length > 0 ? ` · ${concept.tags.slice(0, 2).join(" / ")}` : ""}
              </span>
            </button>
          ))}
          {conceptsList.length === 0 && (
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--control-text-color)" }}>
              暂无知识点
            </p>
          )}
        </div>
      )}

      {!query && filterKind !== "concepts" && (
        <div className="concept-list">
          <div className="search-section-label">内容片段 ({contentList.length})</div>
          {contentList.map((item) => (
            <button
              key={item.key}
              className="concept-list-row concept-list-row-chunk"
              onClick={() => setSearchParams({ concept: item.conceptId })}
              type="button"
            >
              <span className="concept-list-name">{item.text}</span>
              <span className="concept-list-meta">
                {item.conceptName}
              </span>
            </button>
          ))}
          {contentList.length === 0 && (
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--control-text-color)" }}>
              暂无内容片段
            </p>
          )}
        </div>
      )}

      {!query && recentQueries.length > 0 && (
        <div className="search-recent">
          <span className="search-recent-label">最近搜索</span>
          {recentQueries.map((q) => (
            <Pill key={q} onClick={() => { setQuery(q); latestQuery.current = q; doSearch(q); }}>
              {q}
            </Pill>
          ))}
        </div>
      )}

      {loading && <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--control-text-color)" }}>搜索中…</p>}

      {results && (
        <div className="search-results">
          {showConceptResults && concepts.length > 0 && (
            <div>
              <div className="search-section-label">知识点 ({concepts.length})</div>
              {concepts.map((c) => (
                <div
                  key={c.concept_id}
                  className="search-concept-hit"
                  onClick={() => setSearchParams({ concept: c.concept_id })}
                >
                  <div className="search-concept-name">{c.name}</div>
                  <div className="search-concept-meta">
                    {c.canonical_name !== c.name && `规范名：${c.canonical_name} · `}
                    相关度 {(c.score * 100).toFixed(0)}%
                  </div>
                </div>
              ))}
            </div>
          )}

          {showChunkResults && chunks.length > 0 && (
            <div>
              <div className="search-section-label">内容片段 ({chunks.length})</div>
              {chunks.map((c) => (
                <div key={c.chunk_id} className="search-chunk-hit">
                  <div className="search-chunk-text">{c.text}</div>
                  <div className="search-chunk-meta">
                    相关度 {(c.score * 100).toFixed(0)}%
                  </div>
                </div>
              ))}
            </div>
          )}

          {visibleSearchResultCount === 0 && (
            <p style={{ fontFamily: "var(--font-ui)", fontSize: 13, color: "var(--control-text-color)" }}>
              未找到相关内容
            </p>
          )}
        </div>
      )}
    </div>
  );
}
