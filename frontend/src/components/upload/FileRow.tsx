import clsx from "clsx";
import { formatBytes } from "../../utils/format";
import type { SourceKind } from "../../types";
import "./FileRow.css";

export type FileStatus = "queued" | "uploading" | "done" | "failed";

export interface FileEntry {
  id: string;
  file: File;
  kind: SourceKind;
  status: FileStatus;
  progress: number;
  error?: string;
}

const STATUS_LABEL: Record<FileStatus, string> = {
  queued: "等待上传",
  uploading: "上传中…",
  done: "✓ 完成",
  failed: "✗ 失败",
};

const KIND_ICON: Record<SourceKind, string> = {
  pdf: "📄",
  audio: "🎵",
  document: "📝",
  image: "🖼️",
};

export function FileRow({ entry }: { entry: FileEntry }) {
  const { file, kind, status, progress, error } = entry;
  return (
    <div className="file-row">
      <span className="file-row-icon">{KIND_ICON[kind]}</span>
      <div className="file-row-info">
        <div className="file-row-name" title={file.name}>{file.name}</div>
        <div className="file-row-size">{formatBytes(file.size)}</div>
        {status === "uploading" && (
          <div className="file-row-progress-wrap">
            <div className="file-row-progress-bar" style={{ width: `${progress}%` }} />
          </div>
        )}
        {status === "failed" && error && (
          <div className="file-row-size" style={{ color: "var(--color-danger)" }}>{error}</div>
        )}
      </div>
      <span className={clsx("file-row-status", `file-row-status-${status}`)}>
        {STATUS_LABEL[status]}
      </span>
    </div>
  );
}
