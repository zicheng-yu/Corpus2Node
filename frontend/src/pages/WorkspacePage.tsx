import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import clsx from "clsx";
import { getGraph, getSession } from "../api/client";
import { ChatView } from "../components/chat/ChatView";
import { NoteView } from "../components/notes/NoteView";
import { TestView } from "../components/notes/ExamView";
import { SearchPanel } from "../components/search/SearchPanel";
import { ConceptDrawer } from "../components/graph/ConceptDrawer";
import { Skeleton } from "../components/primitives/Skeleton";
import type { ChatContextItem, CourseSession, GraphArtifact, CourseGraphMeta } from "../types";
import "./WorkspacePage.css";

const ConceptGraph = lazy(() =>
  import("../components/graph/ConceptGraph").then((m) => ({ default: m.ConceptGraph })),
);

interface WorkspacePageProps {
  graphStyle?: string;
}

const GraphIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" /><circle cx="5" cy="5" r="2" /><circle cx="19" cy="5" r="2" />
    <circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><path d="m7 7 3 3m4 0 3-3m0 10-3-3m-4 0-3 3" />
  </svg>
);

export function WorkspacePage({ graphStyle = "force" }: WorkspacePageProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const conceptId = searchParams.get("concept");

  const [graph, setGraph] = useState<GraphArtifact | null>(null);
  const [session, setSession] = useState<CourseSession | null>(null);
  const [searchCollapsed, setSearchCollapsed] = useState(false);
  const [notesCollapsed, setNotesCollapsed] = useState(false);
  const [graphCollapsed, setGraphCollapsed] = useState(false);
  const [drillCoreId, setDrillCoreId] = useState<string | null>(null);
  const [drawerCollapsed, setDrawerCollapsed] = useState(false);
  const [leftWidth, setLeftWidth] = useState(() => Number(localStorage.getItem("c2n:leftW")) || 320);
  const [rightWidth, setRightWidth] = useState(() => Number(localStorage.getItem("c2n:rightW")) || 420);
  const [activeTab, setActiveTab] = useState<"chat" | "notes" | "test">("chat");
  const [pendingContext, setPendingContext] = useState<ChatContextItem | null>(null);

  useEffect(() => {
    if (!id) return;
    getGraph(id).then(setGraph).catch(() => {});
    getSession(id).then((s) => setSession(s as CourseSession)).catch(() => {});
  }, [id]);

  function startResize(side: "left" | "right", event: React.MouseEvent) {
    event.preventDefault();
    const startX = event.clientX;
    const startW = side === "left" ? leftWidth : rightWidth;
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX;
      if (side === "left") {
        const w = Math.min(560, Math.max(240, startW + delta));
        setLeftWidth(w);
        localStorage.setItem("c2n:leftW", String(w));
      } else {
        const w = Math.min(640, Math.max(300, startW - delta));
        setRightWidth(w);
        localStorage.setItem("c2n:rightW", String(w));
      }
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  useEffect(() => {
    if (conceptId) {
      setDrawerCollapsed(false);
      setGraphCollapsed(false); // focusing a concept needs the graph visible
    }
  }, [conceptId]);

  if (!id) { navigate("/"); return null; }

  function askFromSelection(context: ChatContextItem) {
    setPendingContext(context);
    setActiveTab("chat");
    setNotesCollapsed(false);
  }

  const selectedConcept = conceptId
    ? graph?.concepts.find((c) => c.concept_id === conceptId) ?? null
    : null;

  // ── Hierarchical mode ─────────────────────────────────────────────────
  const courseMeta: CourseGraphMeta | null = graph?.course_meta ?? null;
  const isHierarchical = !!courseMeta;

  const filterNodeIds = useMemo(() => {
    if (!isHierarchical || !courseMeta) return null;
    if (drillCoreId) {
      const children = courseMeta.children_map[drillCoreId] ?? [];
      return new Set([drillCoreId, ...children]);
    }
    return new Set(courseMeta.core_concept_ids);
  }, [isHierarchical, courseMeta, drillCoreId]);

  const drillCoreName = drillCoreId
    ? graph?.concepts.find((c) => c.concept_id === drillCoreId)?.name ?? drillCoreId
    : null;

  // Collapsing the graph hands the freed space to the tools panel (which is forced open).
  const effectiveNotesCollapsed = notesCollapsed && !graphCollapsed;
  const leftCol = searchCollapsed ? "48px" : `${leftWidth}px`;
  const graphCol = graphCollapsed ? "48px" : "1fr";
  const rightCol = graphCollapsed ? "1fr" : effectiveNotesCollapsed ? "48px" : `${rightWidth}px`;

  return (
    <div
      className={clsx("workspace", {
        "search-collapsed": searchCollapsed,
        "notes-collapsed": effectiveNotesCollapsed,
        "graph-collapsed": graphCollapsed,
      })}
      style={{ gridTemplateColumns: `${leftCol} ${graphCol} ${rightCol}` }}
    >
      {/* Left: Search */}
      <div className="ws-col">
        {!searchCollapsed && (
          <div className="ws-resize-handle ws-resize-right" onMouseDown={(e) => startResize("left", e)} />
        )}
        {searchCollapsed ? (
          <div
            className="ws-rail"
            onClick={() => setSearchCollapsed(false)}
            role="button"
            tabIndex={0}
            aria-label="展开搜索面板"
            onKeyDown={(e) => e.key === "Enter" && setSearchCollapsed(false)}
          >
            <button className="btn-icon" type="button">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
              </svg>
            </button>
            <span className="ws-rail-label">搜索</span>
          </div>
        ) : (
          <>
            <div className="ws-head">
              <span className="ws-title">检索</span>
              <div style={{ flex: 1 }} />
              <button
                className="btn-icon"
                onClick={() => setSearchCollapsed(true)}
                type="button"
                aria-label="折叠搜索面板"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m15 18-6-6 6-6" />
                </svg>
              </button>
            </div>
            <div className="ws-search-body">
              <SearchPanel sessionId={id} />
            </div>
          </>
        )}
      </div>

      {/* Middle: Graph */}
      <div className="ws-col ws-col-graph">
        {graphCollapsed ? (
          <div
            className="ws-rail"
            onClick={() => setGraphCollapsed(false)}
            role="button"
            tabIndex={0}
            aria-label="展开图谱"
            onKeyDown={(e) => e.key === "Enter" && setGraphCollapsed(false)}
          >
            <button className="btn-icon" type="button"><GraphIcon /></button>
            <span className="ws-rail-label">图谱</span>
          </div>
        ) : (
          <>
            <div className="ws-head">
              <button
                className="btn-icon"
                onClick={() => setGraphCollapsed(true)}
                type="button"
                title="折叠图谱"
                aria-label="折叠图谱"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m15 18-6-6 6-6" />
                </svg>
              </button>
              <span className="ws-title">{session?.lecture_title ?? "概念图谱"}</span>
              {session?.course_title && <span className="ws-head-course">{session.course_title}</span>}
            </div>
            <div className="ws-graph-wrap">
              <div className="graph-bg" />

              {/* Overlay: breadcrumb */}
              <div className="graph-head">
                <div className="graph-breadcrumb">
                  <GraphIcon />
                  <span
                    className={drillCoreId || selectedConcept ? "breadcrumb-link" : undefined}
                    onClick={() => { if (drillCoreId) setDrillCoreId(null); if (selectedConcept) setSearchParams({}); }}
                    role={drillCoreId || selectedConcept ? "button" : undefined}
                    tabIndex={drillCoreId || selectedConcept ? 0 : undefined}
                  >
                    {isHierarchical ? "总图谱 · 核心节点" : "全景"}
                  </span>
                  {drillCoreId && (
                    <>
                      <span className="divider">/</span>
                      <span className="current">{drillCoreName}</span>
                      <button className="btn-icon" onClick={() => setDrillCoreId(null)} type="button" aria-label="返回核心节点">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                          <path d="M18 6 6 18M6 6l12 12" />
                        </svg>
                      </button>
                    </>
                  )}
                  {!drillCoreId && selectedConcept && (
                    <>
                      <span className="divider">/</span>
                      <span className="current">{selectedConcept.name}</span>
                      <button className="btn-icon" onClick={() => setSearchParams({})} type="button" aria-label="关闭聚焦">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                          <path d="M18 6 6 18M6 6l12 12" />
                        </svg>
                      </button>
                    </>
                  )}
                </div>
              </div>

              <Suspense fallback={<Skeleton style={{ width: "100%", height: "100%", borderRadius: 0 }} />}>
                <ConceptGraph
                  sessionId={id}
                  graphStyle={graphStyle}
                  filterNodeIds={conceptId ? null : filterNodeIds}
                  onConceptSelect={() => {}}
                  onDrillDown={isHierarchical && !conceptId ? (cid) => {
                    if (!drillCoreId && courseMeta?.core_concept_ids.includes(cid)) {
                      const children = courseMeta.children_map[cid] ?? [];
                      if (children.length > 0) {
                        setDrillCoreId(cid);
                        return;
                      }
                    }
                    if (conceptId === cid) {
                      setDrawerCollapsed(true);
                      setSearchParams({});
                    } else {
                      setDrawerCollapsed(false);
                      setSearchParams({ concept: cid });
                    }
                  } : undefined}
                />
              </Suspense>
              {!drawerCollapsed && (
                <ConceptDrawer sessionId={id} onClose={() => setDrawerCollapsed(true)} />
              )}
              {drawerCollapsed && conceptId && (
                <button
                  className="drawer-reopen-btn"
                  onClick={() => setDrawerCollapsed(false)}
                  type="button"
                  title="展开概念详情"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15 18 9 12 15 6" />
                  </svg>
                </button>
              )}

              {graph && (
                <div className="graph-stats">
                  <span><b>{graph.concepts.length}</b> 概念</span>
                  <span><b>{graph.edges.length}</b> 边</span>
                  <span><b>{graph.topic_clusters.length}</b> 聚类</span>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Right: Study tools */}
      <div className="ws-col ws-col-notes">
        {!effectiveNotesCollapsed && (
          <div className="ws-resize-handle ws-resize-left" onMouseDown={(e) => startResize("right", e)} />
        )}
        {effectiveNotesCollapsed ? (
          <div
            className="ws-rail"
            onClick={() => setNotesCollapsed(false)}
            role="button"
            tabIndex={0}
            aria-label="展开面板"
            onKeyDown={(e) => e.key === "Enter" && setNotesCollapsed(false)}
          >
            <button className="btn-icon" type="button">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
            </button>
            <span className="ws-rail-label">面板</span>
          </div>
        ) : (
          <>
            <div className="ws-head">
              <div className="ws-tool-tabs">
                {(["chat", "notes", "test"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={clsx("ws-tool-tab", activeTab === tab && "ws-tool-tab-active")}
                    onClick={() => setActiveTab(tab)}
                  >
                    {{ chat: "对话", notes: "笔记", test: "测试" }[tab]}
                  </button>
                ))}
              </div>
              <div style={{ flex: 1 }} />
              <button
                className="btn-icon"
                onClick={() => setNotesCollapsed(true)}
                type="button"
                aria-label="折叠面板"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m9 18 6-6-6-6" />
                </svg>
              </button>
            </div>
            <div className="ws-notes-body">
              {/* Chat stays mounted (hidden) so an in-flight stream / history survives tab switches.
                  Notes/Test re-attach to their server-side job on (re)mount, so they survive too. */}
              <div style={{ display: activeTab === "chat" ? "contents" : "none" }}>
                <ChatView
                  sessionId={id}
                  selectedConcept={selectedConcept}
                  pendingContext={pendingContext}
                  onContextConsumed={() => setPendingContext(null)}
                />
              </div>
              {activeTab === "notes" && <NoteView sessionId={id} onAskSelection={askFromSelection} />}
              {activeTab === "test" && <TestView sessionId={id} onAskSelection={askFromSelection} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
