import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLlmSettings, listProviderModels, upsertCredential } from "../../api/client";
import { FALLBACK_PROFILE } from "../../auth/persona";
import { useAuth } from "../../auth/AuthContext";
import { ToastProvider } from "../primitives/Toast";
import type { CurrentUser } from "../../types";
import { SettingsPanel } from "./SettingsPanel";

vi.mock("../../auth/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    getLlmSettings: vi.fn(async () => ({ credentials: [], bindings: [], purposes: [] })),
    listProviderModels: vi.fn(),
    upsertCredential: vi.fn(),
  };
});

const user: CurrentUser = {
  user_id: "user-1",
  email: "user@example.com",
  display_name: "个人用户",
  is_platform_admin: false,
  active_organization_id: "org-1",
  memberships: [{
    organization_id: "org-1",
    organization_name: "演示工作区",
    organization_slug: "demo-workspace",
    role: "owner",
  }],
};

describe("SettingsPanel", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getLlmSettings).mockResolvedValue({ credentials: [], bindings: [], purposes: [] });
    vi.mocked(listProviderModels).mockResolvedValue({ models: ["deepseek-v4-flash"], error: null });
    vi.mocked(useAuth).mockReturnValue({
      mode: "accounts",
      user,
      activeOrganizationId: "org-1",
      loading: false,
      profile: FALLBACK_PROFILE,
      persona: "operator",
      homePath: "/",
      navItems: ["home", "new"],
      signIn: vi.fn(async () => user),
      activate: vi.fn(async () => user),
      signOut: vi.fn(async () => undefined),
      selectOrganization: vi.fn(),
      refreshUser: vi.fn(async () => undefined),
    });
  });

  it("opens as a modal and keeps the original provider API controls", async () => {
    const onClose = vi.fn();
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ToastProvider>
          <SettingsPanel
            open
            onClose={onClose}
            initialSection="appearance"
            graphStyle="force"
            setGraphStyle={vi.fn()}
          />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("dialog", { name: "设置" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "账号" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "团队与成员" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "平台管理" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "模型与 API" }));
    expect(await screen.findByText("模型凭据")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ 新增凭据" }));
    expect(screen.getByText("base_url")).toBeInTheDocument();
    expect(screen.getByText("api_key")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("base_url"), { target: { value: "https://api.deepseek.com" } });
    fireEvent.change(screen.getByLabelText("api_key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: "读取模型" }));
    await waitFor(() => expect(listProviderModels).toHaveBeenCalledWith({
      kind: "openai",
      base_url: "https://api.deepseek.com",
      api_key: "sk-test",
    }));

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("reads models only through a saved credential and updates its default model", async () => {
    const existingSettings = {
      credentials: [{
        credential_id: "cred-deepseek",
        label: "deepseek",
        kind: "openai" as const,
        base_url: "https://api.deepseek.com",
        default_model: "deepseek-v4-pro",
        has_key: true,
        api_key_preview: "••••1234",
      }],
      bindings: [],
      purposes: [],
    };
    vi.mocked(getLlmSettings).mockResolvedValue(existingSettings);
    vi.mocked(listProviderModels).mockResolvedValue({
      models: ["deepseek-v4-flash", "deepseek-v4-pro"],
      error: null,
    });
    vi.mocked(upsertCredential).mockResolvedValue({
      ...existingSettings,
      credentials: [{ ...existingSettings.credentials[0], default_model: "deepseek-v4-flash" }],
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ToastProvider>
          <SettingsPanel
            open
            onClose={vi.fn()}
            initialSection="models"
            graphStyle="force"
            setGraphStyle={vi.fn()}
          />
        </ToastProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "读取模型" }));
    await waitFor(() => expect(listProviderModels).toHaveBeenCalledWith({ credential_id: "cred-deepseek" }));
    const modelSelect = await screen.findByRole("combobox", { name: "deepseek 默认模型" });
    fireEvent.change(modelSelect, { target: { value: "deepseek-v4-flash" } });
    fireEvent.click(screen.getByRole("button", { name: "设为默认" }));

    await waitFor(() => expect(upsertCredential).toHaveBeenCalledWith(expect.objectContaining({
      credential_id: "cred-deepseek",
      api_key: "",
      default_model: "deepseek-v4-flash",
    })));
  });
});
