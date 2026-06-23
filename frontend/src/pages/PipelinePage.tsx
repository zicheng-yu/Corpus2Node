import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import clsx from "clsx";
import { getSession, runWorkflow } from "../api/client";
import { useToast } from "../components/primitives/Toast";
import type { CourseSession, WorkflowRunResponse } from "../types";
import "./PipelinePage.css";

const pipelineRunsInFlight = new Set<string>();

// ── PipelineCanvas ────────────────────────────────────────────────────────────
function PipelineCanvas({ phase, progress }: { phase: number; progress: number }) {
  const WIDTH = 900;
  const HEIGHT = 540;
  const tick = (progress / 100) * Math.min(1, (phase + 1) / 3);

  const docs = useMemo(() => Array.from({ length: 3 }, (_, i) => ({ x: 100 + i * 120, y: 200 })), []);
  const chunks = useMemo(
    () =>
      Array.from({ length: 12 }, (_, i) => {
        const col = i % 4;
        const row = Math.floor(i / 4);
        return { x: 380 + col * 60, y: 150 + row * 70 };
      }),
    [],
  );
  const dots = useMemo(
    () =>
      Array.from({ length: 18 }, (_, i) => {
        const angle = (i / 18) * Math.PI * 2;
        const r = 80 + ((i * 13) % 40);
        return { x: 720 + Math.cos(angle) * r * 0.6, y: 270 + Math.sin(angle) * r };
      }),
    [],
  );

  const docOpacity = phase >= 0 ? Math.min(1, tick * 4) : 0;
  const chunkOpacity = phase >= 1 ? Math.min(1, (tick - 0.2) * 3) : 0;
  const dotOpacity = phase >= 2 ? Math.min(1, (tick - 0.5) * 3) : 0;
  const edgeOpacity = phase >= 3 ? Math.min(1, (tick - 0.8) * 5) : 0;

  return (
    <svg className="viz-canvas" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="xMidYMid meet">
      {phase >= 1 &&
        docs.map((d, di) =>
          chunks.slice(di * 4, di * 4 + 4).map((c, ci) => (
            <line key={`dc-${di}-${ci}`} x1={d.x + 24} y1={d.y} x2={c.x} y2={c.y} stroke="var(--rule-strong)" strokeWidth="0.8" opacity={chunkOpacity * 0.6} />
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
      {phase >= 2 &&
        chunks.slice(0, 6).map((c, ci) =>
          dots.slice(ci * 3, ci * 3 + 3).map((d, di) => (
            <line key={`cd-${ci}-${di}`} x1={c.x + 18} y1={c.y} x2={d.x} y2={d.y} stroke="var(--rule-strong)" strokeWidth="0.6" opacity={dotOpacity * 0.5} />
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
const STAGES = [
  { label: "解析文档", detail: "提取文本内容" },
  { label: "切分片段", detail: "语义分块" },
  { label: "抽取概念", detail: "识别知识点" },
  { label: "构建图谱", detail: "建立关系网络" },
];

type RunState = "running" | "done" | "failed";

export function PipelinePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [session, setSession] = useState<CourseSession | null>(null);
  const [runState, setRunState] = useState<RunState>("running");
  const [result, setResult] = useState<WorkflowRunResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [phase, setPhase] = useState(0);
  const [tick, setTick] = useState(0);
  const triggered = useRef(false);

  // Animate the progress shimmer
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 200);
    return () => clearInterval(interval);
  }, []);

  // Indeterminate phase advance while running (no sub-step events from a sync call)
  useEffect(() => {
    if (runState !== "running") return;
    const interval = setInterval(() => setPhase((p) => Math.min(2, p + 1)), 2500);
    return () => clearInterval(interval);
  }, [runState]);

  // Load session header
  useEffect(() => {
    if (!id) return;
    getSession(id).then((s) => setSession(s as CourseSession)).catch(() => {});
  }, [id]);

  // Run the workflow once (synchronous: ingest -> extract -> build)
  useEffect(() => {
    if (!id || triggered.current || pipelineRunsInFlight.has(id)) return;
    triggered.current = true;
    pipelineRunsInFlight.add(id);

    runWorkflow(id)
      .then((res) => {
        setResult(res);
        setPhase(4);
        setRunState("done");
        setTimeout(() => navigate(`/session/${id}`), 900);
      })
      .catch((e) => {
        setErrorMsg(String(e));
        setRunState("failed");
        toast("图谱构建失败，详见错误信息", "error");
      })
      .finally(() => pipelineRunsInFlight.delete(id));
  }, [id, navigate, toast]);

  const progress = Math.min(100, tick % 100);
  const stats = session?.stats;
  const conceptCount = result?.concept_count ?? stats?.concept_count ?? "—";
  const chunkCount = result?.chunk_count ?? stats?.chunk_count ?? "—";

  return (
    <div className="pipeline-page">
      <div className="pipeline-hero">
        <div>
          <h1 className="pipeline-h">{session?.lecture_title ?? "处理中…"}</h1>
          <p className="pipeline-hsub">{session?.course_title ?? ""}</p>
        </div>
        {runState === "running" && (
          <div className="pipeline-live-badge">
            <span className="pipeline-live-dot" />
            正在解析
          </div>
        )}
      </div>

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
          <span>片段 <b>{chunkCount}</b></span>
          <span>概念 <b>{conceptCount}</b></span>
          <span>关系 <b>{result?.relation_count ?? "—"}</b></span>
        </div>
        <div className="viz-label">PIPELINE · {runState === "running" ? "LIVE" : runState.toUpperCase()}</div>
      </div>

      <div className="log-strip">
        <div className="log-row"><span className="log-ts">·</span><span className="log-info">同步运行：摄入 → 抽取 → 建图（耗时取决于资料量与模型，详见后端终端日志）</span></div>
        {runState === "done" && (
          <div className="log-row"><span className="log-ts">✓</span><span className="log-ok">完成：{result?.concept_count} 概念 / {result?.relation_count} 关系 / {result?.cluster_count} 社区，正在进入工作区…</span></div>
        )}
        {runState === "failed" && (
          <div className="log-row"><span className="log-ts">✗</span><span className="log-warn">失败：{errorMsg}</span></div>
        )}
      </div>

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
