import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listSessions } from "../api/client";
import { ToastProvider } from "../components/primitives/Toast";
import type { CourseSession } from "../types";
import { HomePage } from "./HomePage";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
  },
  deleteSession: vi.fn(),
  listSessions: vi.fn(),
  renameCourse: vi.fn(),
  renameSession: vi.fn(),
  searchConceptsGlobal: vi.fn(async () => []),
}));

const session: CourseSession = {
  session_id: "session-paper-1",
  course_title: "新能源材料",
  lecture_title: "固态电池论文",
  status: "uploaded",
  source_files: [{
    source_id: "source-1",
    kind: "pdf",
    filename: "paper.pdf",
    content_type: "application/pdf",
    size_bytes: 1024,
    content_sha256: "abc",
    uploaded_at: "2026-07-15T08:00:00Z",
    ingested: false,
  }],
  stats: {
    document_count: 1,
    audio_count: 0,
    chunk_count: 0,
    concept_count: 0,
    relation_count: 0,
    cluster_count: 0,
  },
  created_at: "2026-07-15T08:00:00Z",
  updated_at: "2026-07-15T08:00:00Z",
};

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="当前位置">{`${location.pathname}${location.search}`}</output>;
}

describe("HomePage knowledge discovery entry", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(listSessions).mockResolvedValue([session]);
  });

  it("carries selected source sessions into the discovery center", async () => {
    render(
      <MemoryRouter initialEntries={["/"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ToastProvider>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/discover" element={<LocationProbe />} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>,
    );

    const selection = await screen.findByRole("checkbox", { name: "选择 固态电池论文 用于知识发现" });
    expect(selection).toBeEnabled();
    fireEvent.click(selection);
    fireEvent.click(screen.getByRole("button", { name: "知识发现 · 1" }));

    await waitFor(() => {
      const current = screen.getByRole("status", { name: "当前位置" }).textContent ?? "";
      expect(current).toContain("/discover?mode=cross");
      expect(current).toContain("session=session-paper-1");
    });
  });
});
