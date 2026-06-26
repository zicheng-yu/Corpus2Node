from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from corpus2node.core.clock import utcnow


class SessionStatus(str, Enum):
    draft = "draft"
    uploaded = "uploaded"
    ingesting = "ingesting"
    building_graph = "building_graph"
    merging_graph = "merging_graph"
    graph_ready = "graph_ready"
    notes_ready = "notes_ready"
    failed = "failed"


class SourceKind(str, Enum):
    pdf = "pdf"
    audio = "audio"
    document = "document"  # txt/md/docx/pptx/csv/json/yaml
    image = "image"
    video = "video"


class NodeType(str, Enum):
    concept = "concept"
    topic_cluster = "topic_cluster"


class EdgeType(str, Enum):
    mentions = "MENTIONS"
    relates_to = "RELATES_TO"
    co_occurs_with = "CO_OCCURS_WITH"
    contains = "CONTAINS"


class RelationType(str, Enum):
    is_a = "is_a"
    part_of = "part_of"
    prerequisite_of = "prerequisite_of"
    causes = "causes"
    used_for = "used_for"
    similar_to = "similar_to"


class DiscoveryMode(str, Enum):
    selected = "selected"
    random = "random"


class SourceFile(BaseModel):
    source_id: UUID = Field(default_factory=uuid4)
    kind: SourceKind
    filename: str
    content_type: str
    storage_path: str
    size_bytes: int
    uploaded_at: datetime = Field(default_factory=utcnow)
    ingested: bool = False
    ingest_artifact_path: str | None = None


class SessionStats(BaseModel):
    document_count: int = 0
    audio_count: int = 0
    chunk_count: int = 0
    concept_count: int = 0
    relation_count: int = 0
    cluster_count: int = 0


class CourseSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    course_title: str
    lecture_title: str
    status: SessionStatus = SessionStatus.draft
    source_files: list[SourceFile] = Field(default_factory=list)
    stats: SessionStats = Field(default_factory=SessionStats)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    error_message: str | None = None


class EvidenceChunk(BaseModel):
    chunk_id: str
    source_id: str
    source_type: SourceKind
    text: str
    summary: str
    keywords: list[str] = Field(default_factory=list)
    embedding: list[float] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    time_start: float | None = None
    time_end: float | None = None


class IngestArtifact(BaseModel):
    session_id: UUID
    source_id: UUID
    source_kind: SourceKind
    chunks: list[EvidenceChunk] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    extra: dict[str, Any] = Field(default_factory=dict)


class EvidenceRef(BaseModel):
    chunk_id: str
    source_id: str
    source_type: SourceKind
    locator: str
    snippet: str
    score: float = 0.0


class ConceptNode(BaseModel):
    concept_id: str
    name: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    applications: list[str] = Field(default_factory=list)
    embedding: list[float] = Field(default_factory=list)
    importance_score: float = 0.0
    graph_metrics: dict[str, float] = Field(default_factory=dict)
    source_count: int = Field(default=0, exclude=True)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, exclude=True)


class TopicClusterNode(BaseModel):
    cluster_id: str
    title: str
    summary: str
    concept_ids: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    edge_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    target: str
    edge_type: EdgeType
    properties: dict[str, Any] = Field(default_factory=dict)


class CourseGraphMeta(BaseModel):
    """总图谱嵌套结构元数据，仅总图谱有值。"""
    core_concept_ids: list[str] = Field(default_factory=list)
    children_map: dict[str, list[str]] = Field(default_factory=dict)
    source_session_ids: list[str] = Field(default_factory=list)


class GraphArtifact(BaseModel):
    session_id: UUID
    concepts: list[ConceptNode] = Field(default_factory=list)
    topic_clusters: list[TopicClusterNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=utcnow)
    course_meta: CourseGraphMeta | None = None


class SearchConceptHit(BaseModel):
    concept_id: str
    name: str
    canonical_name: str
    score: float
    source_count: int = Field(exclude=True)
    evidence_chunk_ids: list[str] = Field(default_factory=list, exclude=True)


class SearchChunkHit(BaseModel):
    chunk_id: str
    source_id: str
    source_type: SourceKind
    score: float
    text: str
    page_start: int | None = Field(default=None, exclude=True)
    page_end: int | None = Field(default=None, exclude=True)
    time_start: float | None = Field(default=None, exclude=True)
    time_end: float | None = Field(default=None, exclude=True)


class SearchResponse(BaseModel):
    session_id: UUID
    query: str
    concepts: list[SearchConceptHit] = Field(default_factory=list)
    chunks: list[SearchChunkHit] = Field(default_factory=list)


class SubgraphNode(BaseModel):
    id: str
    label: str
    node_type: NodeType
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubgraphEdge(BaseModel):
    source: str
    target: str
    edge_type: EdgeType
    properties: dict[str, Any] = Field(default_factory=dict)


class SubgraphResponse(BaseModel):
    session_id: UUID
    center_concept_id: str
    nodes: list[SubgraphNode] = Field(default_factory=list)
    edges: list[SubgraphEdge] = Field(default_factory=list)


class NoteReference(BaseModel):
    source_type: SourceKind
    source_id: str
    locator: str
    snippet: str


class NoteSection(BaseModel):
    section_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    content_md: str
    concept_ids: list[str] = Field(default_factory=list)
    references: list[NoteReference] = Field(default_factory=list, exclude=True)


class NoteDocument(BaseModel):
    note_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    title: str
    topic: str
    summary: str
    sections: list[NoteSection] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)


class ExamChoice(BaseModel):
    choice_id: str
    text: str


class ExamQuestion(BaseModel):
    question_id: str = Field(default_factory=lambda: str(uuid4()))
    question_type: str
    stem: str
    choices: list[ExamChoice] = Field(default_factory=list)
    answer: str
    explanation: str
    difficulty: str = "medium"
    concept_ids: list[str] = Field(default_factory=list)
    tested_points: list[str] = Field(default_factory=list)
    importance_basis: str = ""


class ExamDocument(BaseModel):
    exam_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    title: str
    summary: str = ""
    questions: list[ExamQuestion] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)


class RetrievalResult(BaseModel):
    """A unified retrieval hit (chunk or concept) returned by the search layer."""

    kind: str  # "chunk" | "concept"
    ref_id: str
    score: float = 0.0
    title: str = ""
    snippet: str = ""
    locator: str = ""
    source_id: str | None = None
    source_type: SourceKind | None = None
    concept_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatCitation(BaseModel):
    """A numbered source the assistant's answer is grounded in."""

    index: int
    kind: str
    ref_id: str
    title: str = ""
    snippet: str = ""
    locator: str = ""
    source_id: str | None = None
    source_type: SourceKind | None = None


class ChatTraceStep(BaseModel):
    """One structured step of the agent's execution (for the debug panel)."""

    step: int
    type: str  # "tool_call" | "retrieval" | "answer"
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    result_count: int = 0


class ChatStreamEvent(BaseModel):
    """An SSE event: type in {start, token, tool_call, retrieval, subgraph, citation, done, error}."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class ChatContextItem(BaseModel):
    context_type: str
    label: str = ""
    content: str = ""
    concept_id: str | None = None


class ChatMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    role: str
    content: str
    context_items: list[ChatContextItem] = Field(default_factory=list)
    citations: list[ChatCitation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class ChatDocument(BaseModel):
    chat_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    messages: list[ChatMessage] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)


class UploadResponse(BaseModel):
    session_id: UUID
    source_id: UUID
    kind: SourceKind
    status: SessionStatus


class IngestRequest(BaseModel):
    session_id: UUID
    source_id: UUID


class BuildGraphRequest(BaseModel):
    session_id: UUID


class BuildCourseGraphRequest(BaseModel):
    course_title: str
    top_n_core: int = Field(default=15, ge=5, le=50)
    top_n_per_session: int = Field(default=6, ge=3, le=50)


class SearchRequest(BaseModel):
    session_id: UUID
    query: str
    limit: int = 8


class GenerateNotesRequest(BaseModel):
    session_id: UUID
    topic: str = ""
    concept_ids: list[str] = Field(default_factory=list)


class GenerateExamRequest(BaseModel):
    session_id: UUID
    question_count: int = Field(default=10, ge=4, le=30)
    question_types: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1, max_length=8000)
    context_items: list[ChatContextItem] = Field(default_factory=list)
    debug: bool = False


class ChatResponse(BaseModel):
    chat: ChatDocument
    assistant_message: ChatMessage
    citations: list[ChatCitation] = Field(default_factory=list)
    trace: list[ChatTraceStep] = Field(default_factory=list)
    subgraph: SubgraphResponse | None = None


class DiscoveryEvidence(BaseModel):
    session_id: UUID
    course_title: str
    lecture_title: str
    concept_id: str = ""
    concept_name: str = ""
    chunk_id: str = ""
    source_id: str = ""
    source_type: SourceKind | None = None
    locator: str = ""
    snippet: str = ""


class DiscoveryParticipant(BaseModel):
    session_id: UUID
    course_title: str
    lecture_title: str
    concept_id: str
    concept_name: str
    summary: str = ""


class DiscoveryBridgeNode(BaseModel):
    id: str
    label: str
    node_type: str
    session_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryBridgeEdge(BaseModel):
    source: str
    target: str
    edge_type: str
    weight: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryBridgeGraph(BaseModel):
    nodes: list[DiscoveryBridgeNode] = Field(default_factory=list)
    edges: list[DiscoveryBridgeEdge] = Field(default_factory=list)


class DiscoveryFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    summary: str
    relation_type: str = "shared_context"
    confidence: float = 0.0
    novelty: float = 0.0
    participants: list[DiscoveryParticipant] = Field(default_factory=list)
    evidence: list[DiscoveryEvidence] = Field(default_factory=list)
    reasoning: str = ""
    score_components: dict[str, float] = Field(default_factory=dict)


class DiscoveryReport(BaseModel):
    discovery_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = ""  # short LLM-generated (or derived) name shown in history
    mode: DiscoveryMode = DiscoveryMode.selected
    session_ids: list[UUID] = Field(default_factory=list)
    findings: list[DiscoveryFinding] = Field(default_factory=list)
    bridge_graph: DiscoveryBridgeGraph = Field(default_factory=DiscoveryBridgeGraph)
    generated_at: datetime = Field(default_factory=utcnow)


class DiscoveryRequest(BaseModel):
    session_ids: list[UUID] = Field(default_factory=list)
    mode: DiscoveryMode = DiscoveryMode.selected
    focus_concept_ids: dict[str, list[str]] = Field(default_factory=dict)
    limit: int = Field(default=8, ge=1, le=20)
    seed: int | None = None


class RuntimeSettingField(BaseModel):
    key: str
    label: str
    group: str
    value: str = ""
    configured: bool = False
    secret: bool = False
    help_url: str = ""
    placeholder: str = ""


class RuntimeSettingsResponse(BaseModel):
    fields: list[RuntimeSettingField] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RuntimeSettingsUpdate(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class WorkflowNodeRun(BaseModel):
    """Per-node observability for one workflow run (timing / tokens / repairs)."""

    node: str
    status: str = "ok"  # ok | error
    duration_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    repair_count: int = 0  # critic node: number of concrete fixes applied
    error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunArtifact(BaseModel):
    """The observability record for one offline pipeline run (saved per session)."""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: UUID
    status: str = "running"  # running | succeeded | failed
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    duration_ms: float = 0.0
    total_tokens: int = 0
    nodes: list[WorkflowNodeRun] = Field(default_factory=list)
    error: str | None = None
