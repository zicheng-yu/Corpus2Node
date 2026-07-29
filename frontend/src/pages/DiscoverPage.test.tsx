import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getDiscovery, listDiscoveryHistory, listSessions } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { FALLBACK_PROFILE } from "../auth/persona";
import { ToastProvider } from "../components/primitives/Toast";
import type {
  CourseSession,
  CurrentUser,
  DiscoveryHistoryItem,
  DiscoveryReport,
} from "../types";
import { DiscoverPage } from "./DiscoverPage";

vi.mock("../auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
  },
  deepenProposal: vi.fn(),
  deleteDiscovery: vi.fn(),
  deleteScientificReport: vi.fn(),
  getDiscovery: vi.fn(),
  getScientificReport: vi.fn(),
  listDiscoveryHistory: vi.fn(),
  listSessions: vi.fn(),
  streamDiscovery: vi.fn(),
  streamScientificAnalysis: vi.fn(),
  updateProposalStatus: vi.fn(),
}));

const member: CurrentUser = {
  user_id: "member-1",
  email: "member@example.com",
  display_name: "普通成员",
  is_platform_admin: false,
  active_organization_id: "org-1",
  memberships: [{
    organization_id: "org-1",
    organization_name: "研发课题组",
    organization_slug: "research-team",
    role: "member",
  }],
};

const session: CourseSession = {
  session_id: "session-1",
  course_title: "电池研发",
  lecture_title: "论文一",
  status: "graph_ready",
  source_files: [{
    source_id: "source-1",
    kind: "pdf",
    filename: "paper.pdf",
    content_type: "application/pdf",
    size_bytes: 2048,
    content_sha256: "hash",
    uploaded_at: "2026-07-15T08:00:00Z",
    ingested: true,
  }],
  stats: {
    document_count: 1,
    audio_count: 0,
    chunk_count: 12,
    concept_count: 8,
    relation_count: 6,
    cluster_count: 2,
  },
  created_at: "2026-07-15T08:00:00Z",
  updated_at: "2026-07-15T08:30:00Z",
};

const history: DiscoveryHistoryItem[] = [
  {
    report_id: "discovery-1",
    report_type: "cross_corpus",
    title: "跨库机会报告",
    generated_at: "2026-07-15T10:00:00Z",
    session_count: 2,
    finding_count: 3,
    proposal_count: 1,
    claim_count: 0,
    insight_count: 0,
    decision_count: 0,
  },
  {
    report_id: "scientific-1",
    report_type: "scientific_evidence",
    title: "固态电池证据报告",
    generated_at: "2026-07-15T11:00:00Z",
    session_count: 1,
    finding_count: 0,
    proposal_count: 0,
    claim_count: 5,
    insight_count: 2,
    decision_count: 1,
  },
];

const report: DiscoveryReport = {
  discovery_id: "discovery-1",
  title: "跨库机会报告",
  mode: "selected",
  intent: "寻找材料机会",
  session_ids: ["session-1"],
  findings: [],
  proposals: [],
  bridge_graph: { nodes: [], edges: [] },
  generated_at: "2026-07-15T10:00:00Z",
};

function authMock(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  return {
    mode: "accounts" as const,
    user: member,
    activeOrganizationId: "org-1",
    loading: false,
    profile: FALLBACK_PROFILE,
    persona: "researcher" as const,
    homePath: "/discover?mode=scientific&focus=evidence",
    navItems: ["discover", "home"] as const,
    signIn: vi.fn(async () => member),
    activate: vi.fn(async () => member),
    signOut: vi.fn(async () => undefined),
    selectOrganization: vi.fn(),
    refreshUser: vi.fn(async () => undefined),
    ...overrides,
  };
}

describe("DiscoverPage unified center", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue(authMock());
    vi.mocked(listSessions).mockResolvedValue([session]);
    vi.mocked(listDiscoveryHistory).mockResolvedValue(history);
    vi.mocked(getDiscovery).mockResolvedValue(report);
  });

  it("shares selection and history while keeping report deletion read-only for members", async () => {
    render(
      <MemoryRouter initialEntries={["/discover?mode=scientific&session=session-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ToastProvider><DiscoverPage /></ToastProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("固态电池证据报告")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /科研证据分析/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.queryByRole("button", { name: /删除历史报告/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "科研证据" }));
    expect(screen.queryByText("跨库机会报告")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部" }));
    fireEvent.click(screen.getByText("跨库机会报告"));

    await waitFor(() => {
      expect(getDiscovery).toHaveBeenCalledWith("discovery-1");
      expect(screen.getByRole("tab", { name: /跨资料发现/ })).toHaveAttribute("aria-selected", "true");
    });
  });

  it("prevents viewers from starting model tasks", async () => {
    vi.mocked(useAuth).mockReturnValue(
      authMock({
        user: {
          ...member,
          memberships: [{ ...member.memberships[0], role: "viewer" }],
        },
      }),
    );

    render(
      <MemoryRouter initialEntries={["/discover?mode=cross&session=session-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ToastProvider><DiscoverPage /></ToastProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("当前角色为只读成员，不能启动模型任务。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始跨资料发现" })).toBeDisabled();
  });

  it("keeps discovery writable when account auth is disabled", async () => {
    vi.mocked(useAuth).mockReturnValue(
      authMock({
        mode: "disabled",
        user: null,
        activeOrganizationId: "",
        persona: "operator",
        homePath: "/",
        navItems: ["home", "new"],
      }),
    );

    render(
      <MemoryRouter initialEntries={["/discover?mode=cross&session=session-1"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ToastProvider><DiscoverPage /></ToastProvider>
      </MemoryRouter>,
    );

    await screen.findByText("跨库机会报告");
    expect(screen.getByRole("button", { name: "开始跨资料发现" })).toBeEnabled();
  });
});
