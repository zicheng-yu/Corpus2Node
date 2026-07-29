import type { components as ApiComponents } from "./api.generated";

type ApiSchemas = ApiComponents["schemas"];

export type SessionStatus =
  | "draft"
  | "uploaded"
  | "ingesting"
  | "ingested"
  | "building_graph"
  | "merging_graph"
  | "graph_ready"
  | "notes_ready"
  | "failed";

export type SourceKind = "pdf" | "audio" | "document" | "image" | "video";

export interface SourceFile {
  source_id: string;
  kind: SourceKind;
  filename: string;
  content_type: string;
  size_bytes: number;
  content_sha256: string;
  uploaded_at: string;
  ingested: boolean;
}

export interface SessionStats {
  document_count: number;
  audio_count: number;
  chunk_count: number;
  concept_count: number;
  relation_count: number;
  cluster_count: number;
}

export interface CourseSession {
  session_id: string;
  course_title: string;
  lecture_title: string;
  status: SessionStatus;
  source_files: SourceFile[];
  stats: SessionStats;
  created_at: string;
  updated_at: string;
  error_message?: string | null;
  project_id?: string | null;
  created_by_user_id?: string | null;
  published_at?: string | null;
}

export interface EvidenceRef {
  chunk_id: string;
  source_id: string;
  source_type: SourceKind;
  locator: string;
  snippet: string;
  score: number;
}

export interface ConceptNode {
  concept_id: string;
  name: string;
  canonical_name: string;
  aliases: string[];
  definition: string;
  summary: string;
  key_points: string[];
  tags: string[];
  prerequisites: string[];
  applications: string[];
  importance_score: number;
  graph_metrics: Record<string, number>;
  source_count?: number;
  evidence_refs?: EvidenceRef[];
}

export interface TopicClusterNode {
  cluster_id: string;
  title: string;
  summary: string;
  concept_ids: string[];
}

export interface GraphEdge {
  edge_id: string;
  source: string;
  target: string;
  edge_type: "MENTIONS" | "RELATES_TO" | "CO_OCCURS_WITH" | "CONTAINS";
  properties: Record<string, unknown>;
}

export interface CourseGraphMeta {
  core_concept_ids: string[];
  children_map: Record<string, string[]>;
  source_session_ids: string[];
}

export interface GraphArtifact {
  schema_version: string;
  session_id: string;
  concepts: ConceptNode[];
  topic_clusters: TopicClusterNode[];
  edges: GraphEdge[];
  built_at: string;
  course_meta?: CourseGraphMeta | null;
}

export interface SearchConceptHit {
  concept_id: string;
  name: string;
  canonical_name: string;
  score: number;
  source_count?: number;
  evidence_chunk_ids?: string[];
}

export interface SearchChunkHit {
  chunk_id: string;
  source_id: string;
  source_type: SourceKind;
  score: number;
  text: string;
  page_start?: number | null;
  page_end?: number | null;
  time_start?: number | null;
  time_end?: number | null;
}

export interface SearchResponse {
  session_id: string;
  query: string;
  concepts: SearchConceptHit[];
  chunks: SearchChunkHit[];
}

export interface GlobalConceptHit {
  session_id: string;
  course_title: string;
  lecture_title: string;
  concept_id: string;
  name: string;
  canonical_name: string;
  importance_score: number;
}

export interface SubgraphNode {
  id: string;
  label: string;
  node_type: "concept" | "topic_cluster";
  metadata: Record<string, unknown>;
}

export interface SubgraphEdge {
  source: string;
  target: string;
  edge_type: string;
  properties: Record<string, unknown>;
}

export interface SubgraphResponse {
  session_id: string;
  center_concept_id: string;
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
}

export interface NoteReference {
  source_type: SourceKind;
  source_id: string;
  locator: string;
  snippet: string;
}

export interface NoteSection {
  section_id: string;
  title: string;
  content_md: string;
  concept_ids: string[];
  references?: NoteReference[];
}

export interface NoteDocument {
  note_id: string;
  session_id: string;
  title: string;
  topic: string;
  summary: string;
  sections: NoteSection[];
  generated_at: string;
}

export interface TestChoice {
  choice_id: string;
  text: string;
}

export type TestQuestionType =
  | "single_choice"
  | "multiple_choice"
  | "true_false"
  | "fill_blank"
  | "short_answer"
  | "essay";

export interface TestQuestion {
  question_id: string;
  question_type: TestQuestionType | string;
  stem: string;
  choices: TestChoice[];
  answer: string;
  explanation: string;
  difficulty: "easy" | "medium" | "hard" | string;
  concept_ids: string[];
  tested_points: string[];
  importance_basis: string;
  primary_concept_id: string;
  importance_score: number;
}

export interface TestDocument {
  test_id: string;
  session_id: string;
  title: string;
  summary: string;
  questions: TestQuestion[];
  generated_at: string;
}

export interface ChatContextItem {
  context_type: "concept" | "note_selection" | "test_selection" | "exam_selection" | "selection" | string;
  label: string;
  content: string;
  concept_id?: string | null;
}

// ── Online chat: retrieval, citations, trace, streaming (additive) ──────────────

export interface RetrievalResult {
  kind: "chunk" | "concept" | string;
  ref_id: string;
  score: number;
  title: string;
  snippet: string;
  locator: string;
  source_id?: string | null;
  source_type?: SourceKind | null;
  concept_ids: string[];
  metadata: Record<string, unknown>;
}

export interface ChatCitation {
  index: number;
  kind: "chunk" | "concept" | string;
  ref_id: string;
  title: string;
  snippet: string;
  locator: string;
  source_id?: string | null;
  source_type?: SourceKind | null;
}

export interface ChatTraceStep {
  step: number;
  type: "tool_call" | "retrieval" | "answer" | string;
  tool: string;
  args: Record<string, unknown>;
  summary: string;
  result_count: number;
}

export type ChatStreamEventType =
  | "start"
  | "token"
  | "tool_call"
  | "retrieval"
  | "subgraph"
  | "citation"
  | "done"
  | "error";

export interface ChatStreamEvent {
  type: ChatStreamEventType | string;
  data: Record<string, unknown>;
}

export interface ChatMessage {
  message_id: string;
  role: "user" | "assistant" | string;
  content: string;
  context_items: ChatContextItem[];
  citations?: ChatCitation[];
  created_at: string;
}

export interface ChatDocument {
  chat_id: string;
  session_id: string;
  messages: ChatMessage[];
  updated_at: string;
}

export interface ChatResponse {
  chat: ChatDocument;
  assistant_message: ChatMessage;
  citations: ChatCitation[];
  trace: ChatTraceStep[];
  subgraph?: SubgraphResponse | null;
}

// ── Knowledge discovery ─────────────────────────────────────────────────────

export type DiscoveryMode = "selected" | "random";

export interface DiscoveryEvidence {
  session_id: string;
  course_title: string;
  lecture_title: string;
  concept_id: string;
  concept_name: string;
  chunk_id: string;
  source_id: string;
  source_type?: SourceKind | null;
  locator: string;
  snippet: string;
}

export interface DiscoveryParticipant {
  session_id: string;
  course_title: string;
  lecture_title: string;
  concept_id: string;
  concept_name: string;
  summary: string;
}

export interface DiscoveryBridgeNode {
  id: string;
  label: string;
  node_type: string;
  session_id?: string | null;
  metadata: Record<string, unknown>;
}

export interface DiscoveryBridgeEdge {
  source: string;
  target: string;
  edge_type: string;
  weight: number;
  metadata: Record<string, unknown>;
}

export interface DiscoveryBridgeGraph {
  nodes: DiscoveryBridgeNode[];
  edges: DiscoveryBridgeEdge[];
}

export interface DiscoveryFinding {
  finding_id: string;
  title: string;
  summary: string;
  relation_type: string;
  confidence: number;
  novelty: number;
  participants: DiscoveryParticipant[];
  evidence: DiscoveryEvidence[];
  reasoning: string;
  score_components: Record<string, number>;
}

export type ProposalStatus = "new" | "kept" | "discarded";

export interface InnovationProposal {
  proposal_id: string;
  title: string;
  pitch: string;
  combination: string;
  first_step: string;
  risks: string;
  status: ProposalStatus;
  deep_dive: string;
  confidence: number;
  sources: DiscoveryParticipant[];
  evidence: DiscoveryEvidence[];
}

export interface DiscoveryReport {
  discovery_id: string;
  title: string;
  mode: DiscoveryMode;
  intent: string;
  session_ids: string[];
  findings: DiscoveryFinding[];
  proposals: InnovationProposal[];
  bridge_graph: DiscoveryBridgeGraph;
  generated_at: string;
}

export type DiscoveryHistoryType = "cross_corpus" | "scientific_evidence";

export interface DiscoveryHistoryItem {
  report_id: string;
  report_type: DiscoveryHistoryType;
  title: string;
  generated_at: string;
  session_count: number;
  finding_count: number;
  proposal_count: number;
  claim_count: number;
  insight_count: number;
  decision_count: number;
}

// ── Scientific R&D evidence vertical ────────────────────────────────────────

export type ScientificLanguageMode = "zh" | "zh_bilingual";
export type ScientificEntityType =
  | "research_problem" | "method" | "model" | "dataset" | "metric"
  | "material" | "parameter" | "result" | "limitation";
export type ScientificInsightType =
  | "agreement" | "contradiction" | "research_gap" | "transfer_opportunity" | "technical_lineage";

export interface ScientificEvidence {
  evidence_id: string;
  session_id: string;
  source_id: string;
  source_type: SourceKind;
  chunk_id: string;
  locator: string;
  snippet: string;
  structured_locator?: ApiSchemas["ScientificLocator"];
}

export interface ScientificEntity {
  entity_id: string;
  session_id: string;
  entity_type: ScientificEntityType;
  name_zh: string;
  name_en: string;
  canonical_name: string;
  description_zh: string;
  evidence_ids: string[];
}

export interface ScientificRelation {
  relation_id: string;
  session_id: string;
  source_name: string;
  relation_type: string;
  target_name: string;
  statement_zh: string;
  confidence: number;
  evidence_ids: string[];
}

export interface ScientificClaim {
  claim_id: string;
  session_id: string;
  claim_type: string;
  statement_zh: string;
  statement_original: string;
  evidence_quote: string;
  subject: string;
  predicate_zh: string;
  object: string;
  polarity: string;
  modality: string;
  confidence: number;
  evidence_ids: string[];
  experiment_ids: string[];
  metric_result_ids: string[];
  condition_ids: string[];
}

export interface ScientificMetricResult {
  metric_result_id: string;
  metric_name: string;
  value: string;
  unit: string;
  comparison_zh: string;
  evidence_quote: string;
  evidence_ids: string[];
}

export interface ScientificExperiment {
  experiment_id: string;
  session_id: string;
  name_zh: string;
  methods: string[];
  datasets_or_environments: string[];
  baselines: string[];
  condition_ids: string[];
  conditions_zh: string;
  metrics: ScientificMetricResult[];
  conclusion_zh: string;
  evidence_ids: string[];
}

export interface ScientificPaperProfile {
  session_id: string;
  source_title: string;
  title_zh: string;
  title_original: string;
  research_problem_zh: string;
  method_summary_zh: string;
  result_summary_zh: string;
  limitations_zh: string[];
  entity_ids: string[];
  claim_ids: string[];
  experiment_ids: string[];
  evidence_ids: string[];
}

export interface ScientificEvidenceMatrixRow {
  paper_title: string;
  session_id: string;
  research_problem_zh: string;
  core_methods: string[];
  datasets_or_environments: string[];
  metrics: string[];
  main_result_zh: string;
  limitations_zh: string[];
  evidence_ids: string[];
}

export interface ScientificInsight {
  insight_id: string;
  insight_type: ScientificInsightType;
  title_zh: string;
  summary_zh: string;
  reasoning_zh: string;
  confidence: number;
  related_session_ids: string[];
  supporting_claim_ids: string[];
  evidence_ids: string[];
}

export interface RDDecisionCard {
  decision_id: string;
  title_zh: string;
  recommendation_zh: string;
  rationale_zh: string;
  next_experiment_zh: string;
  risks_zh: string[];
  confidence: number;
  evidence_ids: string[];
}

export interface ScientificReport {
  report_id: string;
  title_zh: string;
  objective_zh: string;
  language_mode: ScientificLanguageMode;
  session_ids: string[];
  papers: ScientificPaperProfile[];
  entities: ScientificEntity[];
  relations: ScientificRelation[];
  claims: ScientificClaim[];
  experiments: ScientificExperiment[];
  conditions: ApiSchemas["ScientificCondition"][];
  nary_relations: ApiSchemas["ScientificNaryRelation"][];
  evidence: ScientificEvidence[];
  evidence_matrix: ScientificEvidenceMatrixRow[];
  insights: ScientificInsight[];
  decision_cards: RDDecisionCard[];
  generated_at: string;
}

// ── LLM credential registry (replaces the old flat runtime settings) ────────────

export type ProviderKind = "openai" | "anthropic" | "ollama" | "lmstudio";
export type LlmPurpose = "graph" | "critic" | "chat" | "exam" | "vision" | "embedding";

export interface CredentialView {
  credential_id: string;
  label: string;
  kind: ProviderKind;
  base_url: string;
  default_model: string;
  has_key: boolean;
  api_key_preview: string;
  num_ctx?: number | null;
  max_concurrency?: number | null;
}

export interface BindingView {
  purpose: LlmPurpose;
  credential_id: string;
  model: string;
  temperature?: number | null;
  max_output_tokens?: number | null;
  timeout_seconds?: number | null;
  resolved: boolean;
}

export interface LLMSettingsView {
  credentials: CredentialView[];
  bindings: BindingView[];
  purposes: string[];
}

export interface PromptSettings {
  global_instructions: string;
  chat: string;
  notes: string;
  exam: string;
}

export interface CredentialUpsert {
  credential_id?: string | null;
  label: string;
  kind: ProviderKind;
  base_url?: string;
  api_key?: string;
  default_model?: string;
  num_ctx?: number | null;
  max_concurrency?: number | null;
}

export interface ModelListView {
  models: string[];
  error?: string | null;
}

export interface BindingUpsert {
  credential_id: string;
  model?: string;
  temperature?: number | null;
  max_output_tokens?: number | null;
  timeout_seconds?: number | null;
}

// Upload + workflow response shapes
export interface UploadResponse {
  session_id: string;
  source_id: string;
  kind: SourceKind;
  status: SessionStatus;
}

export interface WorkflowRunResponse {
  session_id: string;
  status: SessionStatus | string;
  chunk_count: number;
  concept_count: number;
  relation_count: number;
  cluster_count: number;
}

// ── Accounts, organizations, projects, plans, and sharing ───────────────────

export type OrganizationRole = "owner" | "admin" | "member" | "viewer";
export type ProductPersona = "executive" | "researcher" | "operator";
export type PersonaNavItem = "home" | "new" | "discover" | "workspace";

export interface MembershipView {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: OrganizationRole;
}

export interface CurrentUser {
  user_id: string;
  email: string;
  display_name: string;
  is_platform_admin: boolean;
  persona?: ProductPersona;
  active_organization_id?: string | null;
  memberships: MembershipView[];
}

export interface PersonaProfile {
  label: string;
  description?: string;
  landing: string;
  nav: PersonaNavItem[];
}

export interface CustomerProfile {
  schema_version: number;
  customer_id: string;
  brand: {
    product_name: string;
    tagline?: string;
  };
  personas: Record<ProductPersona, PersonaProfile>;
  features: {
    discovery: boolean;
    notes: boolean;
    level_test: boolean;
  };
}

export interface PlanEntitlements {
  max_members: number;
  max_projects: number;
  max_active_sources: number;
  max_storage_bytes: number;
  max_ai_tasks_month: number;
  max_chat_turns_month: number;
  max_scientific_papers: number;
  max_active_shares: number;
  max_share_days: number;
  team_graph: boolean;
  auto_project_updates: boolean;
  [key: string]: number | boolean;
}

export interface OrganizationView {
  organization_id: string;
  name: string;
  slug: string;
  plan_code: "free" | "team_beta" | string;
  plan_status: string;
  trial_ends_at?: string | null;
  entitlements: PlanEntitlements;
}

export interface MemberView {
  user_id: string;
  email: string;
  display_name: string;
  role: OrganizationRole;
  status: string;
}

export interface InvitationView {
  invitation_id: string;
  email: string;
  role: OrganizationRole;
  expires_at: string;
  accepted_at?: string | null;
  activation_url?: string | null;
}

export interface ProjectView {
  project_id: string;
  organization_id: string;
  name: string;
  description: string;
  kind: "general" | "scientific";
  latest_revision_id?: string | null;
  created_at: string;
  updated_at: string;
  session_count: number;
}

export interface RevisionDelta {
  added: number;
  removed: number;
}

export interface ProjectRevisionView {
  revision_id: string;
  project_id: string;
  revision_number: number;
  status: string;
  source_session_ids: string[];
  contributor_user_ids: string[];
  scientific_report_id?: string | null;
  summary: Record<string, unknown> & {
    delta?: Record<string, RevisionDelta>;
  };
  model_fingerprint: Record<string, string>;
  error?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface ActivityEventView {
  event_id: string;
  actor_user_id?: string | null;
  action: string;
  resource_type: string;
  resource_key: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface UsageSummary {
  plan_code: string;
  period_start: string;
  ai_tasks: number;
  chat_turns: number;
  storage_bytes: number;
  active_sources: number;
  limits: PlanEntitlements;
}

export interface ShareLinkView {
  share_id: string;
  resource_type: string;
  resource_key: string;
  expires_at: string;
  revoked_at?: string | null;
  share_url?: string | null;
}

export interface ShareSnapshot {
  resource_type: string;
  title: string;
  payload: Record<string, unknown>;
  expires_at: string;
}

export interface HealthResponse {
  status: string;
  auth_mode: "disabled" | "legacy_token" | "accounts";
  customer_profile?: string;
}
