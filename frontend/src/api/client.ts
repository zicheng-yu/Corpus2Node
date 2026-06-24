import type {
  BindingUpsert,
  ChatContextItem,
  ChatDocument,
  ChatResponse,
  ChatStreamEvent,
  CourseSession,
  CredentialUpsert,
  ExamDocument,
  GraphArtifact,
  LLMSettingsView,
  LlmPurpose,
  NoteDocument,
  SearchResponse,
  SubgraphResponse,
  UploadResponse,
  WorkflowRunResponse,
} from "../types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, text || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => readJson<T>(r));
}

/** Read a `data:`-line SSE stream (\n\n-separated), dispatching each parsed JSON event. */
async function pumpSSE<T>(response: Response, onEvent: (event: T) => void): Promise<void> {
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, (await response.text()) || `HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = raw.replace(/^data: ?/, "").trim();
      if (!line) continue;
      try {
        onEvent(JSON.parse(line) as T);
      } catch {
        // ignore malformed / keepalive lines
      }
    }
  }
}

// ── Sessions ────────────────────────────────────────────────────────────────

export async function listSessions(): Promise<CourseSession[]> {
  return readJson<CourseSession[]>(await fetch(`${BASE}/sessions`));
}

export async function getSession(id: string): Promise<CourseSession> {
  return readJson<CourseSession>(await fetch(`${BASE}/sessions/${id}`));
}

export function createSession(payload: { course_title: string; lecture_title: string }): Promise<CourseSession> {
  return postJson<CourseSession>("/sessions", payload);
}

export async function deleteSession(id: string): Promise<void> {
  await readJson<{ ok: boolean }>(await fetch(`${BASE}/sessions/${id}`, { method: "DELETE" }));
}

// ── Unified upload (any supported format) ─────────────────────────────────────

export function uploadSourceWithProgress(
  sessionId: string,
  file: File,
  onProgress: (pct: number) => void,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/sessions/${sessionId}/sources`);
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResponse);
        } catch {
          reject(new ApiError(xhr.status, "Invalid JSON response"));
        }
      } else {
        reject(new ApiError(xhr.status, xhr.responseText || `HTTP ${xhr.status}`));
      }
    });
    xhr.addEventListener("error", () => reject(new ApiError(0, "Network error")));
    xhr.send(form);
  });
}

// ── Workflow (synchronous: ingest -> extract -> build) ────────────────────────

export function runWorkflow(sessionId: string): Promise<WorkflowRunResponse> {
  return postJson<WorkflowRunResponse>("/workflow/run", { session_id: sessionId });
}

export interface WorkflowEvent {
  type: "start" | "step" | "done" | "error" | string;
  data: Record<string, unknown>;
}

/** Stream the offline pipeline over SSE; onEvent fires per node (start/step/done/error). */
export async function streamWorkflow(
  sessionId: string,
  onEvent: (event: WorkflowEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/workflow/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
    signal,
  });
  await pumpSSE<WorkflowEvent>(response, onEvent);
}

// ── Graph / search / subgraph ─────────────────────────────────────────────────

export async function getGraph(sessionId: string): Promise<GraphArtifact> {
  return readJson<GraphArtifact>(await fetch(`${BASE}/graph/${sessionId}`));
}

export function searchGraph(payload: { session_id: string; query: string; limit?: number }): Promise<SearchResponse> {
  return postJson<SearchResponse>("/graph/search", payload);
}

export async function fetchSubgraph(sessionId: string, conceptId: string, depth = 1): Promise<SubgraphResponse> {
  const url = new URL(`${BASE}/graph/${sessionId}/subgraph`);
  url.searchParams.set("concept_id", conceptId);
  url.searchParams.set("depth", String(depth));
  return readJson<SubgraphResponse>(await fetch(url.toString()));
}

// ── Chat (streaming + fallback) ───────────────────────────────────────────────

export async function getChat(sessionId: string): Promise<ChatDocument> {
  return readJson<ChatDocument>(await fetch(`${BASE}/chat/${sessionId}`));
}

export function sendChatMessage(payload: {
  session_id: string;
  message: string;
  context_items?: ChatContextItem[];
  debug?: boolean;
}): Promise<ChatResponse> {
  return postJson<ChatResponse>("/chat/message", payload);
}

export async function clearChat(sessionId: string): Promise<ChatDocument> {
  return readJson<ChatDocument>(await fetch(`${BASE}/chat/${sessionId}`, { method: "DELETE" }));
}

/** Stream a chat answer over SSE (POST). Calls onEvent for each event; resolves on stream close. */
export async function streamChat(
  payload: { session_id: string; message: string; context_items?: ChatContextItem[]; debug?: boolean },
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  await pumpSSE<ChatStreamEvent>(response, onEvent);
}

// ── LLM credential registry ───────────────────────────────────────────────────

export async function getLlmSettings(): Promise<LLMSettingsView> {
  return readJson<LLMSettingsView>(await fetch(`${BASE}/settings/llm`));
}

export function upsertCredential(payload: CredentialUpsert): Promise<LLMSettingsView> {
  return postJson<LLMSettingsView>("/settings/llm/credentials", payload);
}

export async function deleteCredential(credentialId: string): Promise<LLMSettingsView> {
  return readJson<LLMSettingsView>(
    await fetch(`${BASE}/settings/llm/credentials/${credentialId}`, { method: "DELETE" }),
  );
}

export async function bindPurpose(purpose: LlmPurpose, payload: BindingUpsert): Promise<LLMSettingsView> {
  return readJson<LLMSettingsView>(
    await fetch(`${BASE}/settings/llm/bindings/${purpose}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function clearBinding(purpose: LlmPurpose): Promise<LLMSettingsView> {
  return readJson<LLMSettingsView>(
    await fetch(`${BASE}/settings/llm/bindings/${purpose}`, { method: "DELETE" }),
  );
}

// ── Notes / Exam (streaming generation; survives navigation via server-side jobs) ─

export interface GenStreamEvent {
  type: "section" | "question" | "done" | "idle" | "error" | string;
  data: Record<string, unknown>;
}

/** Start (or attach to) a notes generation job; streams section/done/error events. */
export async function streamGenerateNotes(
  sessionId: string,
  onEvent: (event: GenStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/generate_notes/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
    signal,
  });
  await pumpSSE<GenStreamEvent>(response, onEvent);
}

/** Attach to an in-flight notes job (replay + live), or replay the saved note, or idle. */
export async function attachNotesStream(
  sessionId: string,
  onEvent: (event: GenStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await pumpSSE<GenStreamEvent>(await fetch(`${BASE}/notes/${sessionId}/stream`, { signal }), onEvent);
}

export async function streamGenerateExam(
  payload: { session_id: string; question_count?: number; question_types?: string[] },
  onEvent: (event: GenStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/generate_exam/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  await pumpSSE<GenStreamEvent>(response, onEvent);
}

export async function attachExamStream(
  sessionId: string,
  onEvent: (event: GenStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await pumpSSE<GenStreamEvent>(await fetch(`${BASE}/exam/${sessionId}/stream`, { signal }), onEvent);
}

// ── Notes / Exam (non-streaming + export) ─────────────────────────────────────

export function generateNotes(payload: { session_id: string; topic?: string; concept_ids?: string[] }): Promise<NoteDocument> {
  return postJson<NoteDocument>("/generate_notes", payload);
}

export async function getNote(sessionId: string): Promise<NoteDocument> {
  return readJson<NoteDocument>(await fetch(`${BASE}/notes/${sessionId}`));
}

export function generateExam(payload: { session_id: string; question_count?: number; question_types?: string[] }): Promise<ExamDocument> {
  return postJson<ExamDocument>("/generate_exam", payload);
}

export async function getExam(sessionId: string): Promise<ExamDocument> {
  return readJson<ExamDocument>(await fetch(`${BASE}/exam/${sessionId}`));
}

export async function exportNote(sessionId: string, fmt: "markdown" | "tex" | "txt" | "pdf"): Promise<Blob> {
  const response = await fetch(`${BASE}/export/${sessionId}/${fmt}`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.blob();
}

export async function exportExam(sessionId: string, fmt: "markdown" | "tex" | "txt" | "pdf"): Promise<Blob> {
  const response = await fetch(`${BASE}/export/${sessionId}/exam/${fmt}`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.blob();
}

export async function exportChat(sessionId: string): Promise<Blob> {
  const response = await fetch(`${BASE}/export/${sessionId}/chat/markdown`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.blob();
}
