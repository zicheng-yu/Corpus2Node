import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import {
  bindPurpose,
  clearBinding,
  deleteCredential,
  getLlmSettings,
  getPromptSettings,
  listProviderModels,
  savePromptSettings,
  upsertCredential,
} from "../../api/client";
import type { CredentialView, LLMSettingsView, LlmPurpose, PromptSettings, ProviderKind } from "../../types";
import { Button } from "../primitives/Button";
import { useToast } from "../primitives/Toast";
import { AccessSettings } from "./AccessSettings";
import { useAuth } from "../../auth/AuthContext";
import { AccountSettings } from "../settings/AccountSettings";
import "../../pages/AccountPage.css";
import "../../pages/SettingsPage.css";
import "./SettingsPanel.css";

export type SettingsPanelSection =
  | "account"
  | "access"
  | "models"
  | "appearance"
  | "prompts";

const ACCOUNT_SECTIONS: Array<{ id: SettingsPanelSection; label: string }> = [
  { id: "account", label: "账号" },
  { id: "models", label: "模型与 API" },
  { id: "appearance", label: "外观设置" },
  { id: "prompts", label: "个人偏好" },
];

const LEGACY_SECTIONS: Array<{ id: SettingsPanelSection; label: string }> = [
  { id: "access", label: "访问安全" },
  { id: "models", label: "模型与 API" },
  { id: "appearance", label: "外观设置" },
  { id: "prompts", label: "提示词设置" },
];

const GRAPH_STYLES = [
  { id: "force", label: "力导向" },
  { id: "radial", label: "径向" },
  { id: "cluster", label: "分组聚类" },
];

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
  initialSection?: SettingsPanelSection;
  graphStyle: string;
  setGraphStyle: (g: string) => void;
}

export function SettingsPanel({ open, onClose, initialSection, graphStyle, setGraphStyle }: SettingsPanelProps) {
  const { mode } = useAuth();
  const sections = mode === "accounts" ? ACCOUNT_SECTIONS : LEGACY_SECTIONS;
  const fallbackSection: SettingsPanelSection = mode === "accounts" ? "account" : "appearance";
  const [section, setSection] = useState<SettingsPanelSection>(initialSection ?? fallbackSection);

  useEffect(() => {
    if (!open) return;
    const requested = initialSection ?? fallbackSection;
    setSection(sections.some((value) => value.id === requested) ? requested : sections[0].id);
  }, [open, initialSection, fallbackSection, sections]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="set-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="设置">
      <div className="set-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="set-head">
          <span className="set-head-title">设置</span>
          <button className="btn-icon" type="button" onClick={onClose} aria-label="关闭">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="set-main">
          <nav className="set-nav">
            {sections.map((s) => (
              <button
                key={s.id}
                type="button"
                className={clsx("set-nav-item", { active: section === s.id })}
                onClick={() => setSection(s.id)}
              >
                {s.label}
              </button>
            ))}
          </nav>
          <div className="set-content">
            {section === "account" && <AccountSettings />}
            {section === "access" && <AccessSettings />}
            {section === "models" && <ModelSettings />}
            {section === "appearance" && (
              <AppearanceSettings graphStyle={graphStyle} setGraphStyle={setGraphStyle} />
            )}
            {section === "prompts" && <PromptsSettings />}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Appearance ──────────────────────────────────────────────────────────────
export function AppearanceSettings({ graphStyle, setGraphStyle }: { graphStyle: string; setGraphStyle: (g: string) => void }) {
  return (
    <section className="set-section">
      <h3 className="set-section-title">图谱布局</h3>
      <p className="set-section-desc">概念图谱的默认排布方式。</p>
      <div className="set-radio-row">
        {GRAPH_STYLES.map((g) => (
          <button
            key={g.id}
            type="button"
            className={clsx("set-radio", { active: graphStyle === g.id })}
            onClick={() => setGraphStyle(g.id)}
          >
            {g.label}
          </button>
        ))}
      </div>
    </section>
  );
}

// ── Prompts ─────────────────────────────────────────────────────────────────
const PROMPT_FIELDS: Array<{ key: keyof PromptSettings; label: string; placeholder: string }> = [
  { key: "global_instructions", label: "全局", placeholder: "例：统一用简体中文、语气专业、专有名词保留英文原词…（对话 / 笔记 / 测试 都生效）" },
  { key: "chat", label: "对话助手", placeholder: "例：先给结论再展开；多用类比解释难点…" },
  { key: "notes", label: "笔记生成", placeholder: "例：每节末尾补一条「一句话记忆」…" },
  { key: "exam", label: "测试生成", placeholder: "例：偏应用与理解，少考死记硬背…" },
];

export function PromptsSettings() {
  const [value, setValue] = useState<PromptSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    getPromptSettings().then(setValue).catch(() => toast("加载提示词失败", "error"));
  }, [toast]);

  if (!value) return <div className="set-loading">加载中…</div>;

  async function save() {
    if (!value) return;
    setSaving(true);
    try {
      setValue(await savePromptSettings(value));
      toast("提示词已保存", "success");
    } catch (e) {
      toast(`保存失败：${String(e)}`, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="set-section">
      <h3 className="set-section-title">提示词设置</h3>
      <p className="set-section-desc">
        系统内置提示词保持不变；这里写的内容会作为「补充偏好」追加到对应场景的系统提示词之后，不会覆盖结构化输出与引用要求。建图抽取与质检为保证可靠性不受此影响。
      </p>
      <div className="set-prompt-fields">
        {PROMPT_FIELDS.map((field) => (
          <label className="set-prompt-field" key={field.key}>
            <span>{field.label}</span>
            <textarea
              rows={3}
              value={value[field.key]}
              placeholder={field.placeholder}
              onChange={(e) => setValue((cur) => ({ ...(cur as PromptSettings), [field.key]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      <div className="set-prompt-actions">
        <Button size="sm" loading={saving} onClick={save}>保存提示词</Button>
      </div>
    </section>
  );
}

// ── Models ──────────────────────────────────────────────────────────────────
const PURPOSES: LlmPurpose[] = ["graph", "chat", "critic", "exam", "vision", "embedding"];
const PURPOSE_LABEL: Record<LlmPurpose, string> = {
  graph: "建图 / 抽取",
  chat: "问答助手",
  critic: "质检 / 求解",
  exam: "测试",
  vision: "图片 / PDF / 视频",
  embedding: "向量嵌入",
};
const PURPOSE_HINT: Record<LlmPurpose, string> = {
  graph: "建图与抽取（也作笔记默认）",
  chat: "问答助手（需 tool calling）",
  critic: "质量校验 / 出题求解（空=回退 graph）",
  exam: "水平测试生成",
  vision: "多模态解析：Kimi 或本地视觉模型（图片 / PDF / 视频）",
  embedding: "向量检索（EMBED_PROVIDER=openai_compatible 时生效，可绑 Ollama）",
};

const KIND_OPTIONS: Array<{ id: ProviderKind; label: string }> = [
  { id: "openai", label: "openai 兼容" },
  { id: "anthropic", label: "anthropic" },
  { id: "ollama", label: "Ollama（本地）" },
  { id: "lmstudio", label: "LM Studio（本地）" },
];
const LOCAL_KINDS: ReadonlySet<ProviderKind> = new Set(["ollama", "lmstudio"]);
const KIND_BASE_PLACEHOLDER: Record<ProviderKind, string> = {
  openai: "https://api.deepseek.com",
  anthropic: "https://api.anthropic.com",
  ollama: "http://127.0.0.1:11434（默认，可留空）",
  lmstudio: "http://127.0.0.1:1234/v1（默认，可留空）",
};

export function ModelSettings() {
  const [settings, setSettings] = useState<LLMSettingsView | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const toast = useToast();

  // add-credential form
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<ProviderKind>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [numCtx, setNumCtx] = useState("");
  const [maxConcurrency, setMaxConcurrency] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelEditor, setModelEditor] = useState<{
    credentialId: string;
    options: string[];
    selected: string;
  } | null>(null);
  const [loadingCredentialId, setLoadingCredentialId] = useState<string | null>(null);
  const isLocal = LOCAL_KINDS.has(kind);

  function switchKind(next: ProviderKind) {
    setKind(next);
    setModelOptions([]);
    if (!label.trim() && LOCAL_KINDS.has(next)) setLabel(next === "ollama" ? "ollama" : "lm-studio");
  }

  async function fetchModels() {
    setLoadingModels(true);
    try {
      const result = await listProviderModels({ kind, base_url: baseUrl.trim(), api_key: apiKey.trim() });
      if (result.error) {
        toast(result.error, "error");
      } else if (result.models.length === 0) {
        toast(isLocal ? "服务在线，但没有已下载的模型" : "端点没有返回模型", "error");
      } else {
        setModelOptions(result.models);
        if (!defaultModel.trim()) setDefaultModel(result.models[0]);
        toast(`发现 ${result.models.length} 个模型`, "success");
      }
    } catch (e) {
      toast(`读取模型失败：${String(e)}`, "error");
    } finally {
      setLoadingModels(false);
    }
  }

  const load = useCallback(async () => {
    try {
      setSettings(await getLlmSettings());
    } catch {
      toast("加载模型设置失败", "error");
    }
  }, [toast]);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  async function addCredential() {
    if (!label.trim() || !defaultModel.trim() || (!isLocal && !apiKey.trim())) {
      toast(isLocal ? "标签、模型必填（本地无需 API Key）" : "标签、API Key、模型都必填", "error");
      return;
    }
    try {
      setSettings(
        await upsertCredential({
          label: label.trim(), kind, base_url: baseUrl.trim(), api_key: apiKey.trim(), default_model: defaultModel.trim(),
          num_ctx: kind === "ollama" && numCtx.trim() ? Number(numCtx) : null,
          max_concurrency: isLocal && maxConcurrency.trim() ? Number(maxConcurrency) : null,
        }),
      );
      setLabel(""); setApiKey(""); setBaseUrl(""); setDefaultModel("");
      setNumCtx(""); setMaxConcurrency(""); setModelOptions([]); setShowAdd(false);
      toast("凭据已保存", "success");
    } catch (e) {
      toast(`保存失败：${String(e)}`, "error");
    }
  }

  async function removeCredential(id: string) {
    try {
      setSettings(await deleteCredential(id));
    } catch (e) {
      toast(`删除失败：${String(e)}`, "error");
    }
  }

  async function fetchSavedModels(credential: CredentialView) {
    setLoadingCredentialId(credential.credential_id);
    try {
      const result = await listProviderModels({ credential_id: credential.credential_id });
      if (result.error) {
        toast(result.error, "error");
      } else if (result.models.length === 0) {
        toast("端点没有返回模型", "error");
      } else {
        setModelEditor({
          credentialId: credential.credential_id,
          options: result.models,
          selected: result.models.includes(credential.default_model)
            ? credential.default_model
            : result.models[0],
        });
        toast(`发现 ${result.models.length} 个模型`, "success");
      }
    } catch (e) {
      toast(`读取模型失败：${String(e)}`, "error");
    } finally {
      setLoadingCredentialId(null);
    }
  }

  async function saveDefaultModel(credential: CredentialView) {
    if (!modelEditor?.selected.trim()) return;
    try {
      setSettings(await upsertCredential({
        credential_id: credential.credential_id,
        label: credential.label,
        kind: credential.kind,
        base_url: credential.base_url,
        api_key: "",
        default_model: modelEditor.selected.trim(),
        num_ctx: credential.num_ctx,
        max_concurrency: credential.max_concurrency,
      }));
      setModelEditor(null);
      toast("默认模型已更新", "success");
    } catch (e) {
      toast(`保存模型失败：${String(e)}`, "error");
    }
  }

  async function applyBinding(purpose: LlmPurpose, credentialId: string) {
    try {
      setSettings(
        credentialId
          ? await bindPurpose(purpose, { credential_id: credentialId, model: "" }) // model comes from the credential
          : await clearBinding(purpose),
      );
    } catch (e) {
      toast(`绑定失败：${String(e)}`, "error");
    }
  }

  if (loading) return <div className="set-loading">加载中…</div>;

  const credentials = settings?.credentials ?? [];
  const bindingByPurpose = new Map((settings?.bindings ?? []).map((b) => [b.purpose, b]));

  return (
    <section className="set-section">
      <h3 className="set-section-title">模型凭据</h3>
      <p className="set-section-desc">每个账号独立保存“端点 + 密钥 + 模型”，密钥仅掩码回显；再在下方为各用途选择凭据。托管站点请使用公网 HTTPS API；Ollama / LM Studio 仅适用于本机部署。</p>

      <div className="set-cred-list">
        {credentials.length === 0 && <div className="set-empty-line">暂无凭据，请新增。</div>}
        {credentials.map((c) => (
          <div className="set-cred-entry" key={c.credential_id}>
            <div className="set-cred-row">
              <div className="set-cred-main">
                <span className="set-cred-label">{c.label}<em>{c.kind}</em></span>
                <span className="set-cred-meta">{c.default_model || "无默认模型"} · {c.api_key_preview || "—"}</span>
              </div>
              <div className="set-cred-actions">
                <button
                  className="set-mini-btn"
                  type="button"
                  disabled={loadingCredentialId === c.credential_id}
                  onClick={() => fetchSavedModels(c)}
                >
                  {loadingCredentialId === c.credential_id ? "读取中…" : "读取模型"}
                </button>
                <button className="set-mini-btn" type="button" onClick={() => removeCredential(c.credential_id)}>删除</button>
              </div>
            </div>
            {modelEditor?.credentialId === c.credential_id && (
              <div className="set-saved-model-editor">
                <select
                  aria-label={`${c.label} 默认模型`}
                  value={modelEditor.selected}
                  onChange={(e) => setModelEditor({ ...modelEditor, selected: e.target.value })}
                >
                  {modelEditor.options.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
                <button className="set-mini-btn" type="button" onClick={() => setModelEditor(null)}>取消</button>
                <Button size="sm" onClick={() => saveDefaultModel(c)}>设为默认</Button>
              </div>
            )}
          </div>
        ))}
      </div>

      {showAdd ? (
        <div className="set-form">
          <div className="set-form-grid">
            <label className="set-field"><span>标签</span><input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="如 deepseek" /></label>
            <label className="set-field"><span>类型</span>
              <select value={kind} onChange={(e) => switchKind(e.target.value as ProviderKind)}>
                {KIND_OPTIONS.map((k) => (
                  <option key={k.id} value={k.id}>{k.label}</option>
                ))}
              </select>
            </label>
            <label className="set-field set-field-wide"><span>base_url</span><input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={KIND_BASE_PLACEHOLDER[kind]} /></label>
            <label className="set-field"><span>api_key{isLocal && <em className="set-field-note">（本地可留空）</em>}</span><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={isLocal ? "本地服务无需密钥" : "sk-…"} /></label>
            <label className="set-field"><span>模型</span>
              <div className="set-model-pick">
                <input
                  list="c2n-model-options"
                  value={defaultModel}
                  onChange={(e) => setDefaultModel(e.target.value)}
                  placeholder={isLocal ? "点「读取模型」或手输，如 gemma3:4b" : "deepseek-chat / kimi-k2.6"}
                />
                <datalist id="c2n-model-options">
                  {modelOptions.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                <button className="set-mini-btn" type="button" disabled={loadingModels} onClick={fetchModels}>
                  {loadingModels ? "读取中…" : "读取模型"}
                </button>
              </div>
            </label>
            {kind === "ollama" && (
              <label className="set-field"><span>上下文窗口 num_ctx</span><input inputMode="numeric" value={numCtx} onChange={(e) => setNumCtx(e.target.value)} placeholder="默认 8192" /></label>
            )}
            {isLocal && (
              <label className="set-field"><span>并发上限</span><input inputMode="numeric" value={maxConcurrency} onChange={(e) => setMaxConcurrency(e.target.value)} placeholder="默认 4（抽取/质检批并发）" /></label>
            )}
          </div>
          <div className="set-form-actions">
            <button className="set-mini-btn" type="button" onClick={() => setShowAdd(false)}>取消</button>
            <Button size="sm" onClick={addCredential}>保存凭据</Button>
          </div>
        </div>
      ) : (
        <button className="set-add-btn" type="button" onClick={() => setShowAdd(true)}>+ 新增凭据</button>
      )}

      <h3 className="set-section-title" style={{ marginTop: "var(--space-5)" }}>用途绑定</h3>
      <p className="set-section-desc">每个用途选一条「凭据 · 模型」。critic 留空回退 graph；vision 用于图片 / PDF / 视频；embedding 仅在用远程嵌入时需要。</p>
      <div className="set-bind-list">
        {PURPOSES.map((p) => {
          const b = bindingByPurpose.get(p);
          const credId = b?.credential_id ?? "";
          return (
            <div className="set-bind-row" key={p}>
              <div className="set-bind-info">
                <span className="set-bind-name">{PURPOSE_LABEL[p]}{b && !b.resolved && <i className="set-bind-bad"> 凭据缺失</i>}</span>
                <span className="set-bind-hint">{PURPOSE_HINT[p]}</span>
              </div>
              <select
                className="set-bind-cred"
                value={credId}
                onChange={(e) => applyBinding(p, e.target.value)}
                disabled={credentials.length === 0}
              >
                <option value="">未绑定</option>
                {credentials.map((c) => (
                  <option key={c.credential_id} value={c.credential_id}>
                    {c.label} · {c.default_model || "无模型"}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
    </section>
  );
}
