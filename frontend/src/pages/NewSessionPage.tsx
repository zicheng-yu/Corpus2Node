import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import clsx from "clsx";
import {
  createSession,
  uploadSourceWithProgress,
  listSessions,
} from "../api/client";
import type { FileEntry } from "../components/upload/FileRow";
import { useToast } from "../components/primitives/Toast";
import type { SourceKind } from "../types";
import "./NewSessionPage.css";

const AUDIO_EXTS = ["mp3", "wav", "m4a", "flac", "aac", "ogg"];
const IMAGE_EXTS = ["png", "jpg", "jpeg", "webp", "gif"];
const VIDEO_EXTS = [
  "mp4",
  "mpeg",
  "mpg",
  "mov",
  "avi",
  "flv",
  "webm",
  "wmv",
  "3gp",
  "3gpp",
];
const ACCEPT =
  ".pdf,.txt,.md,.markdown,.docx,.pptx,.csv,.json,.yaml,.yml" +
  ",.png,.jpg,.jpeg,.webp,.gif" +
  ",.mp4,.mpeg,.mpg,.mov,.avi,.flv,.webm,.wmv,.3gp,.3gpp" +
  ",.mp3,.wav,.m4a,.flac,.aac,.ogg";

function guessKind(file: File): SourceKind {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "pdf";
  if (AUDIO_EXTS.includes(ext)) return "audio";
  if (VIDEO_EXTS.includes(ext)) return "video";
  if (IMAGE_EXTS.includes(ext)) return "image";
  return "document";
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

let idCounter = 0;

const STEP_INFO = [
  { label: "基本信息", desc: "设置知识库与资料集名称" },
  { label: "上传资料", desc: "PDF / Word / PPT / 图片 / 音频…" },
  { label: "确认提交", desc: "核对后开始解析" },
];

export function NewSessionPage() {
  const [searchParams] = useSearchParams();
  const presetCourse = searchParams.get("course") ?? "";
  const [step, setStep] = useState(0);
  const [courseTitle, setCourseTitle] = useState(presetCourse);
  const [lectureTitle, setLectureTitle] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [existingCourses, setExistingCourses] = useState<string[]>([]);
  const sessionIdRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const navigate = useNavigate();

  useEffect(() => {
    listSessions()
      .then((sessions) => {
        const seen = new Set<string>();
        const courses: string[] = [];
        for (const s of sessions) {
          if (!seen.has(s.course_title)) {
            seen.add(s.course_title);
            courses.push(s.course_title);
          }
        }
        setExistingCourses(courses);
      })
      .catch(() => {});
  }, []);

  const addFiles = useCallback((files: File[]) => {
    setEntries((prev) => [
      ...prev,
      ...files.map((f) => ({
        id: String(++idCounter),
        file: f,
        kind: guessKind(f),
        status: "queued" as const,
        progress: 0,
      })),
    ]);
  }, []);

  function removeEntry(id: string) {
    setEntries((prev) => prev.filter((e) => e.id !== id));
  }

  function updateEntry(id: string, patch: Partial<FileEntry>) {
    setEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    );
  }

  async function handleUpload() {
    if (entries.length === 0) return;
    setUploading(true);

    // 1) create the session first (sources are sub-resources of it)
    let sessionId = sessionIdRef.current;
    if (!sessionId) {
      try {
        const session = await createSession({
          course_title: courseTitle.trim(),
          lecture_title: lectureTitle.trim(),
        });
        sessionId = session.session_id;
        sessionIdRef.current = sessionId;
      } catch (e) {
        toast(`创建会话失败：${String(e)}`, "error");
        setUploading(false);
        return;
      }
    }

    // 2) upload each file to the unified sources endpoint
    let uploadedCount = 0;
    for (const entry of entries) {
      updateEntry(entry.id, { status: "uploading", progress: 0 });
      try {
        await uploadSourceWithProgress(sessionId, entry.file, (pct) =>
          updateEntry(entry.id, { progress: pct }),
        );
        uploadedCount += 1;
        updateEntry(entry.id, { status: "done", progress: 100 });
      } catch (e) {
        updateEntry(entry.id, { status: "failed", error: String(e) });
        toast(`${entry.file.name} 上传失败`, "error");
      }
    }

    setUploading(false);
    if (uploadedCount === 0) {
      toast("没有文件上传成功，请修正后重试。", "error");
      return;
    }
    navigate(`/session/${sessionId}/pipeline`);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) addFiles(files);
  }

  function canAdvance(): boolean {
    if (step === 0) return !!courseTitle.trim() && !!lectureTitle.trim();
    if (step === 1) return entries.length > 0;
    return true;
  }

  function nextStep() {
    if (step < 2 && canAdvance()) setStep((s) => s + 1);
  }

  function prevStep() {
    if (step > 0) setStep((s) => s - 1);
  }

  return (
    <div className="new-session-page">
      <div className="wizard">
        {/* Rail */}
        <aside className="wizard-rail">
          <div className="wizard-rail-title">新建知识库</div>
          <div className="wizard-rail-sub">分三步导入并解析资料</div>
          <div className="wizard-steps">
            {STEP_INFO.map((info, i) => (
              <div
                key={i}
                className={clsx("wizard-step", {
                  active: step === i,
                  done: step > i,
                })}
              >
                <div className="wizard-step-num">
                  {step > i ? (
                    <svg
                      width="12"
                      height="12"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </div>
                <div className="wizard-step-info">
                  <div className="wizard-step-label">{info.label}</div>
                  <div className="wizard-step-desc">{info.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* Body */}
        <div className="wizard-body">
          {/* Step 0: Course info */}
          {step === 0 && (
            <>
              <div className="wizard-h">基本信息</div>
              <div className="wizard-hsub">设置知识库与资料集名称</div>

              {existingCourses.length > 0 && (
                <div className="field">
                  <label>已有知识库（点击填入）</label>
                  <div className="suggestions">
                    {existingCourses.map((c) => (
                      <button
                        key={c}
                        className="suggestion"
                        type="button"
                        onClick={() => setCourseTitle(c)}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="field">
                <label htmlFor="courseTitle">知识库名称</label>
                <input
                  id="courseTitle"
                  placeholder="例：入职手册 / 课程名 / 项目文档"
                  value={courseTitle}
                  onChange={(e) => setCourseTitle(e.target.value)}
                  autoFocus
                />
              </div>

              <div className="field">
                <label htmlFor="lectureTitle">资料集名称</label>
                <input
                  id="lectureTitle"
                  placeholder="例：第一批资料 / 第三章 / 会议纪要"
                  value={lectureTitle}
                  onChange={(e) => setLectureTitle(e.target.value)}
                  onKeyDown={(e) =>
                    e.key === "Enter" && canAdvance() && nextStep()
                  }
                />
              </div>

              <div className="wizard-actions">
                <button
                  className="btn btn-ghost"
                  onClick={() => navigate("/")}
                  type="button"
                >
                  取消
                </button>
                <button
                  className="btn btn-primary"
                  onClick={nextStep}
                  disabled={!canAdvance()}
                  type="button"
                >
                  下一步
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </button>
              </div>
            </>
          )}

          {/* Step 1: Files */}
          {step === 1 && (
            <>
              <div className="wizard-h">上传文件</div>
              <div className="wizard-hsub">
                支持 PDF / Word / PPT / Markdown / 文本 / 表格 / 图片 / 视频 /
                音频
              </div>

              <div
                className={clsx("dropzone", { "drag-active": dragActive })}
                onClick={() => fileInputRef.current?.click()}
                onDrop={handleDrop}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={() => setDragActive(false)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) =>
                  e.key === "Enter" && fileInputRef.current?.click()
                }
                aria-label="上传文件区域"
              >
                <div className="dropzone-icon">
                  <svg
                    width="32"
                    height="32"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                </div>
                <div className="dropzone-title">拖放文件到此处，或点击选择</div>
                <div className="dropzone-sub">
                  PDF · DOCX · PPTX · MD · CSV · 图片 · 视频 · 音频 · 最大 500
                  MB
                </div>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ACCEPT}
                style={{ display: "none" }}
                onChange={(e) => {
                  if (e.target.files) addFiles(Array.from(e.target.files));
                  e.target.value = "";
                }}
              />

              {entries.length > 0 && (
                <div className="wizard-file-list">
                  {entries.map((entry) => (
                    <div key={entry.id} className="file-row">
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        style={{ flexShrink: 0, color: "var(--ink-3)" }}
                      >
                        {entry.kind === "audio" ? (
                          <>
                            <path d="M9 18V5l12-2v13" />
                            <circle cx="6" cy="18" r="3" />
                            <circle cx="18" cy="16" r="3" />
                          </>
                        ) : entry.kind === "video" ? (
                          <>
                            <rect x="2" y="3" width="20" height="14" rx="2" />
                            <polygon
                              points="10 8 15 10.5 10 13 10 8"
                              fill="currentColor"
                            />
                          </>
                        ) : entry.kind === "image" ? (
                          <>
                            <rect x="3" y="3" width="18" height="18" rx="2" />
                            <circle cx="9" cy="9" r="2" />
                            <path d="m21 15-3.5-3.5L9 20" />
                          </>
                        ) : (
                          <>
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                            <polyline points="14,2 14,8 20,8" />
                          </>
                        )}
                      </svg>
                      <span className="file-row-name">{entry.file.name}</span>
                      <span className="file-row-size">
                        {formatBytes(entry.file.size)}
                      </span>
                      <button
                        className="btn-icon"
                        onClick={() => removeEntry(entry.id)}
                        type="button"
                        aria-label={`移除 ${entry.file.name}`}
                      >
                        <svg
                          width="12"
                          height="12"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                        >
                          <path d="M18 6 6 18M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="wizard-actions">
                <button
                  className="btn btn-ghost"
                  onClick={prevStep}
                  type="button"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m15 18-6-6 6-6" />
                  </svg>
                  上一步
                </button>
                <button
                  className="btn btn-primary"
                  onClick={nextStep}
                  disabled={!canAdvance()}
                  type="button"
                >
                  下一步
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </button>
              </div>
            </>
          )}

          {/* Step 2: Confirm */}
          {step === 2 && (
            <>
              <div className="wizard-h">确认提交</div>
              <div className="wizard-hsub">核对信息后点击开始解析</div>

              <div className="review-grid">
                <div className="review-label">知识库名称</div>
                <div className="review-value">{courseTitle}</div>

                <div className="review-label">资料集名称</div>
                <div className="review-value">{lectureTitle}</div>

                <div className="review-label">文件</div>
                <div className="review-value">
                  {entries.map((e) => (
                    <div
                      key={e.id}
                      style={{
                        marginBottom: 2,
                        fontSize: 14,
                        fontFamily: "var(--font-ui)",
                      }}
                    >
                      {e.file.name}
                      <span
                        style={{
                          fontSize: 11,
                          color: "var(--ink-4)",
                          marginLeft: 8,
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {formatBytes(e.file.size)}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="review-label">解析流程</div>
                <div
                  className="review-value"
                  style={{
                    fontSize: 14,
                    fontFamily: "var(--font-ui)",
                    color: "var(--ink-2)",
                  }}
                >
                  文件解析 → 片段切分 → 概念抽取 → 图谱构建
                </div>
              </div>

              <div className="wizard-actions">
                <button
                  className="btn btn-ghost"
                  onClick={prevStep}
                  disabled={uploading}
                  type="button"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m15 18-6-6 6-6" />
                  </svg>
                  上一步
                </button>
                <button
                  className="btn btn-accent"
                  onClick={handleUpload}
                  disabled={uploading}
                  type="button"
                >
                  {uploading ? (
                    <>
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        style={{ animation: "spin 1s linear infinite" }}
                      >
                        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                      </svg>
                      上传中…
                    </>
                  ) : (
                    <>
                      开始解析
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                    </>
                  )}
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
