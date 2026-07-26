import type {
  BindingUpsert,
  ChatContextItem,
  ChatDocument,
  ChatResponse,
  ChatStreamEvent,
  CourseSession,
  CurrentUser,
  CredentialUpsert,
  DiscoveryHistoryItem,
  DiscoveryReport,
  GlobalConceptHit,
  GraphArtifact,
  HealthResponse,
  InvitationView,
  LLMSettingsView,
  LlmPurpose,
  ModelListView,
  NoteDocument,
  OrganizationView,
  MemberView,
  ProjectRevisionView,
  ProjectView,
  PromptSettings,
  ProposalStatus,
  ProviderKind,
  SearchResponse,
  ScientificLanguageMode,
  ScientificReport,
  ShareLinkView,
  ShareSnapshot,
  SubgraphResponse,
  TestDocument,
  UsageSummary,
  UploadResponse,
  WorkflowRunResponse,
} from "../types";

const DEFAULT_BASE = import.meta.env.PROD ? "/api" : "http://localhost:8000";
const BASE = (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE).replace(/\/$/, "");
const AUTH_TOKEN_KEY = "c2n:api-auth-token";
const ACTIVE_ORG_KEY = "c2n:active-organization";
const nativeFetch = window.fetch.bind(window);

export function getApiAuthToken(): string {
  return localStorage.getItem(AUTH_TOKEN_KEY) ?? "";
}

export function setApiAuthToken(token: string): void {
  const value = token.trim();
  if (value) localStorage.setItem(AUTH_TOKEN_KEY, value);
  else localStorage.removeItem(AUTH_TOKEN_KEY);
}

export function getActiveOrganizationId(): string {
  return localStorage.getItem(ACTIVE_ORG_KEY) ?? "";
}

export function setActiveOrganizationId(organizationId: string): void {
  if (organizationId) localStorage.setItem(ACTIVE_ORG_KEY, organizationId);
  else localStorage.removeItem(ACTIVE_ORG_KEY);
}

function cookie(name: string): string {
  const prefix = `${encodeURIComponent(name)}=`;
  const value = document.cookie.split("; ").find((part) => part.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : "";
}

async function fetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getApiAuthToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const method = (init.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  const path = new URL(url, window.location.origin).pathname;
  const organizationId = getActiveOrganizationId();
  if (organizationId && !path.endsWith("/auth/me")) {
    headers.set("X-Organization-ID", organizationId);
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = cookie("c2n_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  return nativeFetch(input, { ...init, headers, credentials: "include" });
}

function apiUrl(path: string): URL {
  return new URL(`${BASE}${path}`, window.location.origin);
}

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

function patchJson<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: "PATCH",
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
      let parsed: T;
      try {
        parsed = JSON.parse(line) as T;
      } catch {
        // ignore malformed / keepalive lines
        continue;
      }
      onEvent(parsed);
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

export function createSession(payload: {
  course_title: string;
  lecture_title: string;
  project_id?: string;
}): Promise<CourseSession> {
  return postJson<CourseSession>("/sessions", payload);
}

export function renameSession(id: string, payload: { lecture_title: string }): Promise<CourseSession> {
  return patchJson<CourseSession>(`/sessions/${id}`, payload);
}

export function renameCourse(payload: { old_course_title: string; new_course_title: string }): Promise<CourseSession[]> {
  return patchJson<CourseSession[]>("/sessions/course/rename", payload);
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
    xhr.withCredentials = true;
    const token = getApiAuthToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    const organizationId = getActiveOrganizationId();
    if (organizationId) xhr.setRequestHeader("X-Organization-ID", organizationId);
    const csrf = cookie("c2n_csrf");
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
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

/** Substring-search concepts across every built graph (global search bars). */
export async function searchConceptsGlobal(q: string, limit = 20): Promise<GlobalConceptHit[]> {
  const url = apiUrl("/graph/concepts");
  url.searchParams.set("q", q);
  url.searchParams.set("limit", String(limit));
  return readJson<GlobalConceptHit[]>(await fetch(url.toString()));
}

export async function fetchSubgraph(sessionId: string, conceptId: string, depth = 1): Promise<SubgraphResponse> {
  const url = apiUrl(`/graph/${sessionId}/subgraph`);
  url.searchParams.set("concept_id", conceptId);
  url.searchParams.set("depth", String(depth));
  return readJson<SubgraphResponse>(await fetch(url.toString()));
}

// ── Discovery ───────────────────────────────────────────────────────────────

export function runDiscovery(payload: {
  session_ids?: string[];
  mode?: "selected" | "random";
  intent?: string;
  limit?: number;
  seed?: number;
}): Promise<DiscoveryReport> {
  return postJson<DiscoveryReport>("/discovery/run", payload);
}

export interface LongJobEvent<T> {
  type: "start" | "done" | "error" | string;
  data: { job_id?: string; report?: T; message?: string };
}

export async function streamDiscovery(
  payload: {
    session_ids?: string[];
    mode?: "selected" | "random";
    intent?: string;
    limit?: number;
    seed?: number;
  },
  onEvent: (event: LongJobEvent<DiscoveryReport>) => void,
): Promise<void> {
  const response = await fetch(`${BASE}/discovery/run/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await pumpSSE(response, onEvent);
}

export async function updateProposalStatus(
  discoveryId: string,
  proposalId: string,
  status: ProposalStatus,
): Promise<DiscoveryReport> {
  return readJson<DiscoveryReport>(
    await fetch(`${BASE}/discovery/${discoveryId}/proposals/${proposalId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),
  );
}

export function deepenProposal(discoveryId: string, proposalId: string): Promise<DiscoveryReport> {
  return postJson<DiscoveryReport>(`/discovery/${discoveryId}/proposals/${proposalId}/deepen`, {});
}

export async function listDiscoveries(): Promise<DiscoveryReport[]> {
  return readJson<DiscoveryReport[]>(await fetch(`${BASE}/discovery`));
}

export async function listDiscoveryHistory(): Promise<DiscoveryHistoryItem[]> {
  return readJson<DiscoveryHistoryItem[]>(await fetch(`${BASE}/discovery/history`));
}

export async function getDiscovery(discoveryId: string): Promise<DiscoveryReport> {
  return readJson<DiscoveryReport>(await fetch(`${BASE}/discovery/${discoveryId}`));
}

export async function deleteDiscovery(discoveryId: string): Promise<void> {
  await readJson<{ ok: boolean }>(
    await fetch(`${BASE}/discovery/${discoveryId}`, { method: "DELETE" }),
  );
}

// ── Scientific R&D evidence ─────────────────────────────────────────────────

export function runScientificAnalysis(payload: {
  session_ids: string[];
  objective_zh?: string;
  language_mode?: ScientificLanguageMode;
}): Promise<ScientificReport> {
  return postJson<ScientificReport>("/scientific/run", payload);
}

export async function streamScientificAnalysis(
  payload: {
    session_ids: string[];
    objective_zh?: string;
    language_mode?: ScientificLanguageMode;
  },
  onEvent: (event: LongJobEvent<ScientificReport>) => void,
): Promise<void> {
  const response = await fetch(`${BASE}/scientific/run/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await pumpSSE(response, onEvent);
}

export async function listScientificReports(): Promise<ScientificReport[]> {
  return readJson<ScientificReport[]>(await fetch(`${BASE}/scientific`));
}

export async function getScientificReport(reportId: string): Promise<ScientificReport> {
  return readJson<ScientificReport>(await fetch(`${BASE}/scientific/${reportId}`));
}

export async function deleteScientificReport(reportId: string): Promise<void> {
  await readJson<{ ok: boolean }>(
    await fetch(`${BASE}/scientific/${reportId}`, { method: "DELETE" }),
  );
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

export function listProviderModels(payload: {
  credential_id?: string;
  kind?: ProviderKind;
  base_url?: string;
  api_key?: string;
}): Promise<ModelListView> {
  return postJson<ModelListView>("/settings/llm/models", payload);
}

// ── Prompt settings (custom instructions appended to built-in system prompts) ──

export async function getPromptSettings(): Promise<PromptSettings> {
  return readJson<PromptSettings>(await fetch(`${BASE}/settings/prompts`));
}

export function savePromptSettings(payload: PromptSettings): Promise<PromptSettings> {
  return fetch(`${BASE}/settings/prompts`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then((r) => readJson<PromptSettings>(r));
}

// ── Notes / level test (streaming generation; survives navigation via server-side jobs) ─

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

export async function streamGenerateTest(
  payload: { session_id: string; question_count?: number },
  onEvent: (event: GenStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${BASE}/generate_test/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  await pumpSSE<GenStreamEvent>(response, onEvent);
}

export async function attachTestStream(
  sessionId: string,
  onEvent: (event: GenStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await pumpSSE<GenStreamEvent>(await fetch(`${BASE}/test/${sessionId}/stream`, { signal }), onEvent);
}

// ── Notes / level test (non-streaming + export) ───────────────────────────────

export function generateNotes(payload: { session_id: string; topic?: string; concept_ids?: string[] }): Promise<NoteDocument> {
  return postJson<NoteDocument>("/generate_notes", payload);
}

export async function getNote(sessionId: string): Promise<NoteDocument> {
  return readJson<NoteDocument>(await fetch(`${BASE}/notes/${sessionId}`));
}

export function generateTest(payload: { session_id: string; question_count?: number }): Promise<TestDocument> {
  return postJson<TestDocument>("/generate_test", payload);
}

export async function getTest(sessionId: string): Promise<TestDocument> {
  return readJson<TestDocument>(await fetch(`${BASE}/test/${sessionId}`));
}

export async function exportNote(sessionId: string, fmt: "markdown" | "tex" | "txt" | "pdf"): Promise<Blob> {
  const response = await fetch(`${BASE}/export/${sessionId}/${fmt}`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.blob();
}

export async function exportTest(sessionId: string, fmt: "markdown" | "tex" | "txt" | "pdf"): Promise<Blob> {
  const response = await fetch(`${BASE}/export/${sessionId}/test/${fmt}`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.blob();
}

export async function exportChat(sessionId: string): Promise<Blob> {
  const response = await fetch(`${BASE}/export/${sessionId}/chat/markdown`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.blob();
}

// ── Accounts and tenant context ─────────────────────────────────────────────

export async function getHealth(): Promise<HealthResponse> {
  return readJson<HealthResponse>(await fetch(`${BASE}/health`));
}

export function login(payload: { email: string; password: string }): Promise<CurrentUser> {
  return postJson<CurrentUser>("/auth/login", payload);
}

export function activateAccount(payload: {
  token: string;
  display_name: string;
  password: string;
}): Promise<CurrentUser> {
  return postJson<CurrentUser>("/auth/activate", payload);
}

export async function getCurrentUser(): Promise<CurrentUser> {
  return readJson<CurrentUser>(await fetch(`${BASE}/auth/me`));
}

export async function logout(): Promise<void> {
  await readJson<{ ok: boolean }>(await fetch(`${BASE}/auth/logout`, { method: "POST" }));
}

export function changePassword(payload: {
  current_password: string;
  new_password: string;
}): Promise<{ ok: boolean }> {
  return postJson<{ ok: boolean }>("/auth/change-password", payload);
}

// ── Organizations, members, invitations, and platform administration ───────

export async function listOrganizations(): Promise<OrganizationView[]> {
  return readJson<OrganizationView[]>(await fetch(`${BASE}/organizations`));
}

export async function listMembers(organizationId: string): Promise<MemberView[]> {
  return readJson<MemberView[]>(await fetch(`${BASE}/organizations/${organizationId}/members`));
}

export async function listInvitations(organizationId: string): Promise<InvitationView[]> {
  return readJson<InvitationView[]>(await fetch(`${BASE}/organizations/${organizationId}/invitations`));
}

export function inviteMember(
  organizationId: string,
  payload: { email: string; role: string },
): Promise<InvitationView> {
  return postJson<InvitationView>(`/organizations/${organizationId}/invitations`, payload);
}

export async function revokeInvitation(organizationId: string, invitationId: string): Promise<void> {
  await readJson<{ ok: boolean }>(
    await fetch(`${BASE}/organizations/${organizationId}/invitations/${invitationId}`, { method: "DELETE" }),
  );
}

export function updateMemberRole(
  organizationId: string,
  userId: string,
  role: string,
): Promise<MemberView> {
  return patchJson<MemberView>(`/organizations/${organizationId}/members/${userId}`, { role });
}

export async function deactivateMember(organizationId: string, userId: string): Promise<void> {
  await readJson<{ ok: boolean }>(
    await fetch(`${BASE}/organizations/${organizationId}/members/${userId}`, { method: "DELETE" }),
  );
}

export async function getOrganizationUsage(organizationId: string): Promise<UsageSummary> {
  return readJson<UsageSummary>(await fetch(`${BASE}/organizations/${organizationId}/usage`));
}

export async function listAdminOrganizations(): Promise<OrganizationView[]> {
  return readJson<OrganizationView[]>(await fetch(`${BASE}/admin/organizations`));
}

export function provisionOrganization(payload: {
  name: string;
  owner_email: string;
  plan_code: string;
  trial_ends_at?: string | null;
}): Promise<{ organization: OrganizationView; owner_invitation: InvitationView }> {
  return postJson("/admin/organizations", payload);
}

export function updateOrganizationPlan(
  organizationId: string,
  payload: {
    plan_code: string;
    plan_status: string;
    trial_ends_at?: string | null;
    entitlement_overrides?: Record<string, number | boolean>;
  },
): Promise<OrganizationView> {
  return patchJson<OrganizationView>(`/admin/organizations/${organizationId}/plan`, payload);
}

// ── Shared projects and revisions ───────────────────────────────────────────

export async function listProjects(): Promise<ProjectView[]> {
  return readJson<ProjectView[]>(await fetch(`${BASE}/projects`));
}

export function createProject(payload: {
  name: string;
  description?: string;
  kind?: "general" | "scientific";
}): Promise<ProjectView> {
  return postJson<ProjectView>("/projects", payload);
}

export async function getProject(projectId: string): Promise<ProjectView> {
  return readJson<ProjectView>(await fetch(`${BASE}/projects/${projectId}`));
}

export async function listProjectSessions(projectId: string): Promise<CourseSession[]> {
  return readJson<CourseSession[]>(await fetch(`${BASE}/projects/${projectId}/sessions`));
}

export async function listProjectRevisions(projectId: string): Promise<ProjectRevisionView[]> {
  return readJson<ProjectRevisionView[]>(await fetch(`${BASE}/projects/${projectId}/revisions`));
}

export async function listProjectActivity(projectId: string): Promise<import("../types").ActivityEventView[]> {
  return readJson<import("../types").ActivityEventView[]>(await fetch(`${BASE}/projects/${projectId}/activity`));
}

export async function getProjectGraph(projectId: string, revisionId?: string): Promise<GraphArtifact> {
  const path = revisionId
    ? `/projects/${projectId}/revisions/${revisionId}/graph`
    : `/projects/${projectId}/graph`;
  return readJson<GraphArtifact>(await fetch(`${BASE}${path}`));
}

export async function getProjectScientific(projectId: string): Promise<ScientificReport> {
  return readJson<ScientificReport>(await fetch(`${BASE}/projects/${projectId}/scientific`));
}

export function refreshProject(projectId: string): Promise<ProjectRevisionView> {
  return postJson<ProjectRevisionView>(`/projects/${projectId}/refresh`, {});
}

export async function deactivateProjectSession(projectId: string, sessionId: string): Promise<void> {
  await readJson<{ ok: boolean }>(
    await fetch(`${BASE}/projects/${projectId}/sessions/${sessionId}`, { method: "DELETE" }),
  );
}

export async function getProjectChat(projectId: string): Promise<ChatDocument> {
  return readJson<ChatDocument>(await fetch(`${BASE}/projects/${projectId}/chat`));
}

export function sendProjectChat(projectId: string, message: string): Promise<ChatResponse> {
  return postJson<ChatResponse>(`/projects/${projectId}/chat`, { message });
}

// ── Fixed read-only share snapshots ─────────────────────────────────────────

export function createShare(payload: {
  resource_type: string;
  resource_key: string;
  expires_in_days: number;
}): Promise<ShareLinkView> {
  return postJson<ShareLinkView>("/shares", payload);
}

export async function listShares(): Promise<ShareLinkView[]> {
  return readJson<ShareLinkView[]>(await fetch(`${BASE}/shares`));
}

export async function revokeShare(shareId: string): Promise<void> {
  await readJson<{ ok: boolean }>(await fetch(`${BASE}/shares/${shareId}`, { method: "DELETE" }));
}

export function resolveShare(token: string): Promise<ShareSnapshot> {
  return postJson<ShareSnapshot>("/public/shares/resolve", { token });
}
