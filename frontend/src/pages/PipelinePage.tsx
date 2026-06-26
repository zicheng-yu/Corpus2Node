import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import clsx from "clsx";
import { getGraph, getSession, streamWorkflow } from "../api/client";
import { useToast } from "../components/primitives/Toast";
import type { CourseSession } from "../types";
import "./PipelinePage.css";

const pipelineRunsInFlight = new Set<string>();
// latest counts per in-flight run, so re-entering the page can show progress
const pipelineProgress = new Map<string, { chunk: number | null; concept: number | null; relation: number | null; cluster: number | null }>();

// ── PipelineCanvas ────────────────────────────────────────────────────────────
// Three tidy stages, all vertically centered on CY, no overlap: docs → chunks → dots.
function PipelineCanvas({ phase, progress }: { phase: number; progress: number }) {
  const CY = 270;
  const tick = (progress / 100) * Math.min(1, (phase + 1) / 3);

  const docs = useMemo(() => Array.from({ length: 3 }, (_, i) => ({ x: 70 + i * 92, y: CY })), []);
  const chunks = useMemo(
    () =>
      Array.from({ length: 8 }, (_, i) => {
        const col = i % 4;
        const row = Math.floor(i / 4);
        return { x: 410 + col * 56, y: CY - 35 + row * 70 };
      }),
    [],
  );
  const dots = useMemo(
    () =>
      // two even rings, centered on CY — a tidy cluster, not flung to a corner
      Array.from({ length: 16 }, (_, i) => {
        const ring = i < 6 ? 0 : 1;
        const inRing = ring === 0 ? 6 : 10;
        const idx = ring === 0 ? i : i - 6;
        const r = ring === 0 ? 52 : 104;
        const angle = (idx / inRing) * Math.PI * 2 - Math.PI / 2;
        return { x: 745 + Math.cos(angle) * r, y: CY + Math.sin(angle) * r };
      }),
    [],
  );

  const docOpacity = phase >= 0 ? Math.min(1, tick * 4) : 0;
  const chunkOpacity = phase >= 1 ? Math.min(1, (tick - 0.2) * 3) : 0;
  const dotOpacity = phase >= 2 ? Math.min(1, (tick - 0.5) * 3) : 0;
  const edgeOpacity = phase >= 3 ? Math.min(1, (tick - 0.8) * 5) : 0;

  return (
    <svg className="viz-canvas" viewBox="0 110 900 320" preserveAspectRatio="xMidYMid meet">
      {/* doc → chunk lines (each doc fans to two chunks) */}
      {phase >= 1 &&
        docs.map((d, di) =>
          chunks.slice(di * 2, di * 2 + 2).map((c, ci) => (
            <line key={`dc-${di}-${ci}`} x1={d.x + 48} y1={d.y} x2={c.x - 18} y2={c.y} stroke="var(--rule-strong)" strokeWidth="0.8" opacity={chunkOpacity * 0.5} />
          )),
        )}
      {docs.map((d, i) => (
        <g key={i} opacity={docOpacity}>
          <rect x={d.x} y={d.y - 36} width={48} height={64} rx="4" fill="var(--panel)" stroke="var(--rule-strong)" strokeWidth="1.2" />
          {[0, 1, 2, 3].map((li) => (
            <line key={li} x1={d.x + 8} y1={d.y - 24 + li * 12} x2={d.x + 40} y2={d.y - 24 + li * 12} stroke="var(--rule)" strokeWidth="1" />
          ))}
        </g>
      ))}
      {chunks.map((c, i) => (
        <rect key={i} x={c.x - 18} y={c.y - 10} width={36} height={20} rx="3" fill="var(--panel-2)" stroke="var(--rule-strong)" strokeWidth="1" opacity={chunkOpacity} />
      ))}
      {/* chunk → dot lines */}
      {phase >= 2 &&
        chunks.map((c, ci) =>
          dots.slice(ci * 2, ci * 2 + 2).map((d, di) => (
            <line key={`cd-${ci}-${di}`} x1={c.x + 18} y1={c.y} x2={d.x} y2={d.y} stroke="var(--rule-strong)" strokeWidth="0.6" opacity={dotOpacity * 0.45} />
          )),
        )}
      {dots.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={4 + (i % 3)} fill="var(--accent)" opacity={dotOpacity * 0.75} />
      ))}
      {phase >= 3 &&
        dots.map((d, i) => {
          const next = dots[(i + 3) % dots.length];
          return <line key={`e-${i}`} x1={d.x} y1={d.y} x2={next.x} y2={next.y} stroke="var(--accent)" strokeWidth="0.9" opacity={edgeOpacity * 0.4} />;
        })}
    </svg>
  );
}

// ── PipelinePage (run-and-wait) ─────────────────────────────────────────────────
// Four stages → one tidy row (the critic/质检 node still runs; its progress and
// repair counts fold into 构建图谱 visually and into the per-node metrics panel).
const STAGES = [
  { label: "解析文档", detail: "提取文本内容" },
  { label: "切分片段", detail: "语义分块" },
  { label: "抽取概念", detail: "识别知识点" },
  { label: "构建图谱", detail: "质检修复 + 建立关系网络" },
];

type RunState = "checking" | "running" | "done" | "failed";

interface Counts {
  chunk: number | null;
  concept: number | null;
  relation: number | null;
  cluster: number | null;
}

interface NodeMetric {
  duration_ms: number;
  total_tokens: number;
  repair_count: number;
}

const METRIC_NODES: Array<{ key: string; label: string }> = [
  { key: "ingest", label: "解析" },
  { key: "extract", label: "抽取" },
  { key: "critic", label: "质检" },
  { key: "build", label: "构建" },
];

function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export function PipelinePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [session, setSession] = useState<CourseSession | null>(null);
  const [runState, setRunState] = useState<RunState>("checking");
  const [counts, setCounts] = useState<Counts>({ chunk: null, concept: null, relation: null, cluster: null });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [phase, setPhase] = useState(0);
  const [tick, setTick] = useState(0);
  const [nodeMetrics, setNodeMetrics] = useState<Record<string, NodeMetric>>({});
  const [runTotals, setRunTotals] = useState<{ total_tokens: number; duration_ms: number } | null>(null);
  const triggered = useRef(false);

  // Animate the progress shimmer
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 200);
    return () => clearInterval(interval);
  }, []);

  // Drive the pipeline from REAL backend step events (SSE). Skip re-running a
  // session that's already built (fixes re-entering re-runs the pipeline).
  useEffect(() => {
    if (!id || triggered.current) return;
    triggered.current = true;

    // A run for this session is already in flight (we left the page and came
    // back): DON'T re-run. Poll for the graph and continue once it's ready, so
    // the background run finishes and we never duplicate the work.
    if (pipelineRunsInFlight.has(id)) {
      setRunState("running");
      setPhase(3); // a run is mid-flight; show later-stage progress
      const cached = pipelineProgress.get(id);
      if (cached) setCounts(cached);
      getSession(id).then((s) => setSession(s as CourseSession)).catch(() => {});
      const poll = setInterval(async () => {
        const p = pipelineProgress.get(id);
        if (p) setCounts(p);
        try {
          const g = await getGraph(id);
          if (g && g.concepts.length > 0) {
            clearInterval(poll);
            navigate(`/session/${id}`);
          }
        } catch {
          /* not ready yet */
        }
      }, 1500);
      return () => clearInterval(poll);
    }

    pipelineRunsInFlight.add(id); // claim synchronously to avoid duplicate runs

    (async () => {
      try {
        // Skip if a graph already exists (robust against stale building_graph status).
        try {
          const g = await getGraph(id);
          if (g && g.concepts.length > 0) {
            navigate(`/session/${id}`);
            return;
          }
        } catch {
          /* no graph yet → build it */
        }
        try {
          setSession((await getSession(id)) as CourseSession);
        } catch {
          /* ignore — stream will surface errors */
        }

        setRunState("running");
        const acc: Counts = { chunk: null, concept: null, relation: null, cluster: null };
        const push = () => {
          setCounts({ ...acc });
          pipelineProgress.set(id, { ...acc });
        };
        await streamWorkflow(id, (event) => {
          const data = event.data as Record<string, unknown>;
          if (event.type === "start") {
            setPhase(0);
          } else if (event.type === "step") {
            const node = String(data.node ?? "");
            if (node === "ingest") {
              setPhase(2);
              acc.chunk = Number(data.chunk_count ?? acc.chunk ?? 0);
              push();
            } else if (node === "extract") {
              setPhase(3);
              acc.concept = Number(data.concept_count ?? acc.concept ?? 0);
              acc.relation = Number(data.relation_count ?? acc.relation ?? 0);
              push();
            } else if (node === "critic") {
              setPhase(3); // critic folds into the 构建图谱 stage
              if (data.concept_count != null) acc.concept = Number(data.concept_count);
              if (data.relation_count != null) acc.relation = Number(data.relation_count);
              push();
            } else if (node === "build") {
              acc.concept = Number(data.concept_count ?? acc.concept ?? 0);
              acc.relation = Number(data.relation_count ?? acc.relation ?? 0);
              acc.cluster = Number(data.cluster_count ?? acc.cluster ?? 0);
              push();
            }
            const metric = data.metrics as Partial<NodeMetric> | undefined;
            if (metric && node) {
              setNodeMetrics((prev) => ({
                ...prev,
                [node]: {
                  duration_ms: Number(metric.duration_ms ?? 0),
                  total_tokens: Number(metric.total_tokens ?? 0),
                  repair_count: Number(metric.repair_count ?? 0),
                },
              }));
            }
          } else if (event.type === "done") {
            acc.chunk = Number(data.chunk_count ?? acc.chunk ?? 0);
            acc.concept = Number(data.concept_count ?? 0);
            acc.relation = Number(data.relation_count ?? 0);
            acc.cluster = Number(data.cluster_count ?? 0);
            push();
            setPhase(4); // all four stages done
            setRunState("done");
            if (data.total_tokens != null || data.duration_ms != null) {
              setRunTotals({ total_tokens: Number(data.total_tokens ?? 0), duration_ms: Number(data.duration_ms ?? 0) });
            }
            // cached run (already built) → nothing to review, go straight in;
            // a fresh run stays so the run-metrics panel is visible.
            if (data.cached) navigate(`/session/${id}`);
          } else if (event.type === "error") {
            setErrorMsg(String(data.message ?? "处理失败"));
            setRunState("failed");
            toast("图谱构建失败，详见错误信息", "error");
          }
        });
      } catch (e) {
        setErrorMsg(String(e));
        setRunState("failed");
        toast("图谱构建失败，详见错误信息", "error");
      } finally {
        pipelineRunsInFlight.delete(id);
        pipelineProgress.delete(id);
      }
    })();
  }, [id, navigate, toast]);

  const progress = Math.min(100, tick % 100);
  const fmt = (v: number | null) => (v == null ? "—" : v);

  return (
    <div className="pipeline-page">
      <div className="pipeline-hero">
        <div>
          <h1 className="pipeline-h">{session?.lecture_title ?? "处理中…"}</h1>
          <p className="pipeline-hsub">{session?.course_title ?? ""}</p>
        </div>
        {(runState === "running" || runState === "checking") && (
          <div className="pipeline-live-badge">
            <span className="pipeline-live-dot" />
            正在解析
          </div>
        )}
      </div>

      <p className="pipeline-hint">耗时取决于资料量与模型</p>

      <div className="stage-track">
        {STAGES.map((s, i) => {
          const active = phase === i;
          const done = phase > i;
          return (
            <div key={i} className={clsx("stage", { active, done })}>
              <div className="stage-num">
                {done ? (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block" }}>
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  `0${i + 1}`
                )}
              </div>
              <div className="stage-name">{s.label}</div>
              <div className="stage-detail">{active ? s.detail : done ? "完成" : ""}</div>
            </div>
          );
        })}
      </div>

      <div className="pipeline-viz">
        <PipelineCanvas phase={phase} progress={progress} />
        <div className="viz-counters">
          <span>片段 <b>{fmt(counts.chunk)}</b></span>
          <span>概念 <b>{fmt(counts.concept)}</b></span>
          <span>关系 <b>{fmt(counts.relation)}</b></span>
          <span>社区 <b>{fmt(counts.cluster)}</b></span>
        </div>
        <div className="viz-label">PIPELINE · {runState === "running" || runState === "checking" ? "LIVE" : runState.toUpperCase()}</div>
      </div>

      {Object.keys(nodeMetrics).length > 0 && (
        <div className="run-metrics">
          <div className="run-metrics-head">
            <span className="run-metrics-title">本次运行 · 各节点</span>
            {runTotals && (
              <span className="run-metrics-total">{fmtMs(runTotals.duration_ms)} · {runTotals.total_tokens} tokens</span>
            )}
          </div>
          <div className="run-metrics-rows">
            {METRIC_NODES.filter((n) => nodeMetrics[n.key]).map((n) => {
              const m = nodeMetrics[n.key];
              return (
                <div className="run-metric-row" key={n.key}>
                  <span className="rm-node">{n.label}</span>
                  <span className="rm-dur">{fmtMs(m.duration_ms)}</span>
                  <span className="rm-tok">{m.total_tokens > 0 ? `${m.total_tokens} tok` : "—"}</span>
                  <span className="rm-rep">{n.key === "critic" ? `修复 ${m.repair_count}` : ""}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {runState === "done" && (
        <div className="log-strip">
          <div className="log-row"><span className="log-ts">✓</span><span className="log-ok">完成：{counts.concept} 概念 / {counts.relation} 关系 / {counts.cluster} 社区，正在进入工作区…</span></div>
        </div>
      )}

      {runState === "failed" && <div className="pipeline-error">{errorMsg ?? "处理失败，请重试。"}</div>}

      <div className="pipeline-actions">
        <button className="btn btn-ghost" onClick={() => navigate("/")} type="button">返回列表</button>
        {runState === "failed" && (
          <button
            className="btn btn-accent"
            onClick={() => {
              triggered.current = false;
              window.location.reload();
            }}
            type="button"
          >
            重试
          </button>
        )}
        {runState === "done" && (
          <button className="btn btn-primary" onClick={() => navigate(`/session/${id}`)} type="button">进入工作区</button>
        )}
      </div>
    </div>
  );
}
