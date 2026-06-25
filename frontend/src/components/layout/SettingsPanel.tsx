import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import {
  bindPurpose,
  clearBinding,
  deleteCredential,
  getLlmSettings,
  getPromptSettings,
  savePromptSettings,
  upsertCredential,
} from "../../api/client";
import type { LLMSettingsView, LlmPurpose, PromptSettings, ProviderKind } from "../../types";
import { Button } from "../primitives/Button";
import { useToast } from "../primitives/Toast";
import "./SettingsPanel.css";

type Section = "models" | "appearance" | "prompts";

const SECTIONS: Array<{ id: Section; label: string }> = [
  { id: "models", label: "模型设置" },
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
  graphStyle: string;
  setGraphStyle: (g: string) => void;
}

export function SettingsPanel({ open, onClose, graphStyle, setGraphStyle }: SettingsPanelProps) {
  const [section, setSection] = useState<Section>("models");
  if (!open) return null;

  return (
    <div className="set-overlay" onClick={onClose} role="dialog" aria-label="设置">
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
            {SECTIONS.map((s) => (
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
function AppearanceSettings({ graphStyle, setGraphStyle }: { graphStyle: string; setGraphStyle: (g: string) => void }) {
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
  { key: "global_instructions", label: "全局", placeholder: "例：统一用简体中文、语气专业、专有名词保留英文原词…（对话 / 笔记 / 试卷 都生效）" },
  { key: "chat", label: "对话助手", placeholder: "例：先给结论再展开；多用类比解释难点…" },
  { key: "notes", label: "笔记生成", placeholder: "例：每节末尾补一条「一句话记忆」…" },
  { key: "exam", label: "试卷生成", placeholder: "例：偏应用与理解题，少考死记硬背…" },
];

function PromptsSettings() {
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
const PURPOSES: LlmPurpose[] = ["graph", "chat", "critic", "exam"];
const PURPOSE_HINT: Record<LlmPurpose, string> = {
  graph: "建图与抽取（也作笔记默认）",
  chat: "问答助手（需 tool calling）",
  critic: "质量校验 / 出题求解（空=回退 graph）",
  exam: "出卷生成",
};

function ModelSettings() {
  const [settings, setSettings] = useState<LLMSettingsView | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const toast = useToast();

  // add-credential form
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<ProviderKind>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [defaultModel, setDefaultModel] = useState("");

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
    if (!label.trim() || !apiKey.trim()) {
      toast("标签和 API Key 必填", "error");
      return;
    }
    try {
      setSettings(
        await upsertCredential({
          label: label.trim(), kind, base_url: baseUrl.trim(), api_key: apiKey.trim(), default_model: defaultModel.trim(),
        }),
      );
      setLabel(""); setApiKey(""); setBaseUrl(""); setDefaultModel(""); setShowAdd(false);
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

  async function applyBinding(purpose: LlmPurpose, credentialId: string, model: string) {
    try {
      setSettings(credentialId ? await bindPurpose(purpose, { credential_id: credentialId, model: model.trim() }) : await clearBinding(purpose));
    } catch (e) {
      toast(`绑定失败：${String(e)}`, "error");
    }
  }

  if (loading) return <div className="set-loading">加载中…</div>;

  const credentials = settings?.credentials ?? [];
  const bindingByPurpose = new Map((settings?.bindings ?? []).map((b) => [b.purpose, b]));

  return (
    <section className="set-section">
      <h3 className="set-section-title">凭据</h3>
      <p className="set-section-desc">暂存 API Key（OpenAI 兼容 / Anthropic），密钥仅掩码回显。图片/PDF/Embedding/语音仍由后端 .env 配置。</p>

      <div className="set-cred-list">
        {credentials.length === 0 && <div className="set-empty-line">暂无凭据，请新增。</div>}
        {credentials.map((c) => (
          <div className="set-cred-row" key={c.credential_id}>
            <div className="set-cred-main">
              <span className="set-cred-label">{c.label}<em>{c.kind}</em></span>
              <span className="set-cred-meta">{c.default_model || "无默认模型"} · {c.api_key_preview || "—"}</span>
            </div>
            <button className="set-mini-btn" type="button" onClick={() => removeCredential(c.credential_id)}>删除</button>
          </div>
        ))}
      </div>

      {showAdd ? (
        <div className="set-form">
          <div className="set-form-grid">
            <label className="set-field"><span>标签</span><input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="如 deepseek" /></label>
            <label className="set-field"><span>类型</span>
              <select value={kind} onChange={(e) => setKind(e.target.value as ProviderKind)}>
                <option value="openai">openai 兼容</option>
                <option value="anthropic">anthropic</option>
              </select>
            </label>
            <label className="set-field set-field-wide"><span>base_url</span><input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com" /></label>
            <label className="set-field"><span>api_key</span><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…" /></label>
            <label className="set-field"><span>默认模型</span><input value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)} placeholder="deepseek-chat" /></label>
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
      <p className="set-section-desc">把每个用途绑定到某个凭据 + 模型（留空用默认）。</p>
      <div className="set-bind-list">
        {PURPOSES.map((p) => {
          const b = bindingByPurpose.get(p);
          const credId = b?.credential_id ?? "";
          const model = drafts[p] ?? b?.model ?? "";
          return (
            <div className="set-bind-row" key={p}>
              <div className="set-bind-info">
                <span className="set-bind-name">{p}{b && !b.resolved && <i className="set-bind-bad"> 凭据缺失</i>}</span>
                <span className="set-bind-hint">{PURPOSE_HINT[p]}</span>
              </div>
              <select
                className="set-bind-cred"
                value={credId}
                onChange={(e) => applyBinding(p, e.target.value, model)}
                disabled={credentials.length === 0}
              >
                <option value="">未绑定</option>
                {credentials.map((c) => <option key={c.credential_id} value={c.credential_id}>{c.label}</option>)}
              </select>
              <input
                className="set-bind-model"
                value={model}
                placeholder="默认"
                onChange={(e) => setDrafts((d) => ({ ...d, [p]: e.target.value }))}
                onBlur={() => credId && applyBinding(p, credId, model)}
                disabled={!credId}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}
