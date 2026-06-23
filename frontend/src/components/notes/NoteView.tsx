import { useEffect, useState, type SyntheticEvent } from "react";
import type { ChatContextItem, NoteDocument } from "../../types";
import { generateNotes, getNote } from "../../api/client";
import { Markdown } from "./Markdown";
import { ExportMenu } from "./ExportMenu";
import { Button } from "../primitives/Button";
import { useToast } from "../primitives/Toast";
import "./NoteView.css";

export function NoteView({
  sessionId,
  initialNote,
  onNoteChange,
  onAskSelection,
}: {
  sessionId: string;
  initialNote: NoteDocument | null;
  onNoteChange?: (note: NoteDocument) => void;
  onAskSelection?: (context: ChatContextItem) => void;
}) {
  const [note, setNote] = useState<NoteDocument | null>(initialNote);
  const [generating, setGenerating] = useState(false);
  const [selectedText, setSelectedText] = useState("");
  const toast = useToast();

  useEffect(() => {
    setNote(initialNote);
  }, [initialNote]);

  async function handleGenerate() {
    setGenerating(true);
    try {
      await generateNotes({ session_id: sessionId });
      const fresh = await getNote(sessionId);
      setNote(fresh);
      onNoteChange?.(fresh);
    } catch (error) {
      toast(error instanceof Error ? `笔记生成失败：${error.message}` : "笔记生成失败", "error");
    } finally {
      setGenerating(false);
    }
  }

  function captureSelection(event: SyntheticEvent) {
    if ((event.target as HTMLElement).closest("button")) return;
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? "";
    setSelectedText(text.length >= 2 ? text.slice(0, 2200) : "");
  }

  function askSelection() {
    if (!selectedText) return;
    onAskSelection?.({
      context_type: "note_selection",
      label: "笔记选区",
      content: selectedText,
    });
    setSelectedText("");
  }

  if (!note) {
    return (
      <div className="note-generate">
        <div>
          <p className="note-generate-title">根据当前图数据库生成笔记</p>
          <p className="note-generate-label">
            将使用当前图谱中的知识点、聚类和关系生成结构化课堂笔记。
          </p>
        </div>
        <Button onClick={handleGenerate} loading={generating}>生成图谱笔记</Button>
      </div>
    );
  }

  return (
    <div className="note-view" onMouseUp={captureSelection} onKeyUp={captureSelection}>
      <div className="note-view-header">
        <div>
          <h2 className="note-view-title">{note.title}</h2>
          <p className="note-view-subtitle">由当前知识图谱生成</p>
        </div>
        <div className="note-view-actions">
          {selectedText && onAskSelection && (
            <Button variant="ghost" size="sm" onClick={askSelection}>
              询问选区
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={handleGenerate} loading={generating}>
            重新生成
          </Button>
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
