import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import type { ChatContextItem, NoteDocument } from "../../types";
import { attachNotesStream, streamGenerateNotes, type GenStreamEvent } from "../../api/client";
import { Markdown } from "./Markdown";
import { ExportMenu } from "./ExportMenu";
import { Button } from "../primitives/Button";
import { useToast } from "../primitives/Toast";
import "./panel.css";
import "./NoteView.css";

interface StreamSection {
  index: number;
  title: string;
  content_md: string;
}

export function NoteView({
  sessionId,
  onAskSelection,
}: {
  sessionId: string;
  onAskSelection?: (context: ChatContextItem) => void;
}) {
  const [note, setNote] = useState<NoteDocument | null>(null);
  const [sections, setSections] = useState<StreamSection[]>([]);
  const [generating, setGenerating] = useState(false);
  const [selectedText, setSelectedText] = useState("");
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;

  function handleEvent(event: GenStreamEvent) {
    if (event.type === "section") {
      setGenerating(true);
      const index = Number(event.data.index);
      setSections((current) =>
        current.some((s) => s.index === index)
          ? current
          : [...current, { index, title: String(event.data.title ?? ""), content_md: String(event.data.content_md ?? "") }].sort(
              (a, b) => a.index - b.index,
            ),
      );
    } else if (event.type === "done") {
      setNote(event.data.note as NoteDocument);
      setSections([]);
      setGenerating(false);
    } else if (event.type === "error") {
      setGenerating(false);
      toastRef.current(`笔记生成失败：${String(event.data?.message ?? "")}`, "error");
    }
    // "idle" → no note yet, nothing in flight
  }

  // Attach on mount: replays an in-flight job (fixes blank-on-reentry) or the saved note.
  useEffect(() => {
    const controller = new AbortController();
    setNote(null);
    setSections([]);
    setGenerating(false);
    attachNotesStream(sessionId, handleEvent, controller.signal).catch(() => {});
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function handleGenerate() {
    setNote(null);
    setSections([]);
    setGenerating(true);
    try {
      await streamGenerateNotes(sessionId, handleEvent);
    } catch (error) {
      setGenerating(false);
      toast(error instanceof Error ? `笔记生成失败：${error.message}` : "笔记生成失败", "error");
    }
  }

  function captureSelection(event: SyntheticEvent) {
    if ((event.target as HTMLElement).closest("button")) return;
    const text = window.getSelection()?.toString().trim() ?? "";
    setSelectedText(text.length >= 2 ? text.slice(0, 2200) : "");
  }

  function askSelection() {
    if (!selectedText) return;
    onAskSelection?.({ context_type: "note_selection", label: "笔记选区", content: selectedText });
    setSelectedText("");
  }

  if (generating) {
    return (
      <div className="panel-stream">
        <div className="panel-stream-status">
          <span className="panel-spinner" /> 正在生成笔记…（已完成 {sections.length} 节）
        </div>
        {sections.map((section) => (
          <div key={section.index} className="note-section">
            <h3 className="note-section-title">{section.title}</h3>
            <Markdown>{section.content_md}</Markdown>
          </div>
        ))}
      </div>
    );
  }

  if (!note) {
    return (
      <div className="panel-empty">
        <p className="panel-empty-title">根据当前图谱生成笔记</p>
        <p className="panel-empty-desc">按聚类与核心概念分章，落地原文引用，并对核心概念做覆盖检查。</p>
        <Button size="sm" onClick={handleGenerate}>生成图谱笔记</Button>
      </div>
    );
  }

  return (
    <div className="note-view" onMouseUp={captureSelection} onKeyUp={captureSelection}>
      <div className="panel-bar">
        <span className="panel-bar-title">{note.title}</span>
        <div className="panel-bar-actions">
          {selectedText && onAskSelection && (
            <button className="panel-mini-btn" type="button" onClick={askSelection}>询问选区</button>
          )}
          <button className="panel-mini-btn" type="button" onClick={handleGenerate}>重新生成</button>
          <ExportMenu sessionId={sessionId} />
        </div>
      </div>
      <div className="note-view-summary">
        <Markdown>{note.summary}</Markdown>
      </div>
      {note.sections.map((section) => (
        <div key={section.section_id} className="note-section">
          <h3 className="note-section-title">{section.title}</h3>
          <Markdown>{section.content_md}</Markdown>
        </div>
      ))}
    </div>
  );
}
