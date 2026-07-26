import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "../../auth/AuthContext";
import type { CurrentUser } from "../../types";
import { TopBar } from "./TopBar";

vi.mock("../../auth/AuthContext", () => ({ useAuth: vi.fn() }));

const user: CurrentUser = {
  user_id: "admin-1",
  email: "admin@example.com",
  display_name: "演示用户",
  is_platform_admin: true,
  active_organization_id: "org-1",
  memberships: [
    {
      organization_id: "platform-org",
      organization_name: "Corpus2Node Platform",
      organization_slug: "platform",
      role: "owner",
    },
    {
      organization_id: "org-1",
      organization_name: "演示工作区",
      organization_slug: "demo-workspace",
      role: "member",
    },
  ],
};

describe("TopBar product navigation", () => {
  it("keeps account, role and workspace controls inside settings", () => {
    const onOpenSettings = vi.fn();
    vi.mocked(useAuth).mockReturnValue({
      mode: "accounts",
      user,
      activeOrganizationId: "org-1",
      loading: false,
      signIn: vi.fn(async () => undefined),
      activate: vi.fn(async () => undefined),
      signOut: vi.fn(async () => undefined),
      selectOrganization: vi.fn(),
      refreshUser: vi.fn(async () => undefined),
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TopBar onOpenSettings={onOpenSettings} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "项目" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "科研证据" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "团队" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "平台管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "当前组织" })).not.toBeInTheDocument();
    expect(screen.queryByText("演示用户")).not.toBeInTheDocument();
    expect(screen.queryByText("成员")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });
});
