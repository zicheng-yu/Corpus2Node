import { useEffect, useState } from "react";
import { listScientificReports, listSessions, streamScientificAnalysis } from "../api/client";
import type { CourseSession, ScientificReport } from "../types";
import { ScientificReportView } from "../components/scientific/ScientificReportView";
import { useToast } from "../components/primitives/Toast";
import "./ScientificPage.css";

function isReady(session: CourseSession): boolean {
  return !session.lecture_title.startsWith("[总图谱] ") && session.source_files.length > 0;
}


export function ScientificPage() {
  const [sessions, setSessions] = useState<CourseSession[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [objective, setObjective] = useState("比较多智能体强化学习中的价值分解路线、实验结论与适用边界");
  const [report, setReport] = useState<ScientificReport | null>(null);
  const [history, setHistory] = useState<ScientificReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const toast = useToast();

  useEffect(() => {
    Promise.all([listSessions(), listScientificReports()])
      .then(([sessionData, reportData]) => {
        const ready = sessionData.filter(isReady);
        setSessions(ready);
        const paperIds = ready.filter((item) => item.course_title === "demo: papers").map((item) => item.session_id);
        setSelected(new Set(paperIds.length >= 2 ? paperIds : ready.slice(0, 2).map((item) => item.session_id)));
        setHistory(reportData);
        if (reportData.length) setReport(reportData[0]);
      })
      .catch(() => toast("加载科研文献与历史报告失败", "error"))
      .finally(() => setLoading(false));
  }, [toast]);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function run() {
    if (!selected.size) {
      toast("请至少选择一篇已上传的科技文献", "error");
      return;
    }
    setRunning(true);
    try {
      const result: { report?: ScientificReport } = {};
      await streamScientificAnalysis(
        {
          session_ids: [...selected],
          objective_zh: objective.trim(),
          language_mode: "zh_bilingual",
        },
        (event) => {
          if (event.type === "error") throw new Error(event.data.message || "科研证据分析失败");
          if (event.type === "done" && event.data.report) result.report = event.data.report;
        },
      );
      const next = result.report;
      if (!next) throw new Error("科研证据分析未返回报告");
      setReport(next);
      setHistory((current) => [next, ...current.filter((item) => item.report_id !== next.report_id)]);
      toast("科研证据分析完成", "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "科研证据分析失败，请检查模型配置";
      toast(message, "error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="scientific-page">
      <aside className="science-sidebar">
        <span className="science-eyebrow">SCIENTIFIC R&amp;D</span>
        <h1>科研证据图谱</h1>
        <p>从原始科技文献提取方法、实验、指标、结果与限制，跨论文发现证据关系和研发机会。</p>

        <label className="science-label" htmlFor="science-objective">研发分析目标</label>
        <textarea id="science-objective" rows={4} value={objective} onChange={(event) => setObjective(event.target.value)} maxLength={800} />

        <div className="science-label science-label-row"><span>选择文献</span><span>{selected.size} 篇</span></div>
        <div className="science-session-list">
          {loading && <p className="science-muted">正在加载…</p>}
          {sessions.map((session) => (
            <label className="science-session" key={session.session_id}>
              <input type="checkbox" checked={selected.has(session.session_id)} onChange={() => toggle(session.session_id)} />
              <span><strong>{session.lecture_title}</strong><small>{session.course_title} · {session.stats.chunk_count} 个原文块</small></span>
            </label>
          ))}
        </div>
        <button className="btn btn-accent science-run" type="button" onClick={run} disabled={running || loading}>
          {running ? "正在抽取与综合证据…" : "开始科研证据分析"}
        </button>
        <p className="science-run-note">中文叙述，英文正式名称独立保留；所有结论必须有原文定位。</p>

        {history.length > 0 && (
          <div className="science-history">
            <span className="science-label">历史报告</span>
            {history.slice(0, 8).map((item) => (
              <button type="button" key={item.report_id} className={report?.report_id === item.report_id ? "active" : ""} onClick={() => setReport(item)}>
                <strong>{item.title_zh}</strong>
                <small>{new Date(item.generated_at).toLocaleString("zh-CN")}</small>
              </button>
            ))}
          </div>
        )}
      </aside>

      <main className="science-main">
        {report ? <ScientificReportView report={report} /> : (
          <div className="science-blank">
            <span>01</span><h2>选择科技文献并开始分析</h2>
            <p>系统将构建论文级证据结构，再做跨论文比较，不会把无出处的模型推断当成科研事实。</p>
          </div>
        )}
      </main>
    </div>
  );
}
