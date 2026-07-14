import { useEffect, useState, type FormEvent } from "react";
import {
  getOrganizationUsage,
  listAdminOrganizations,
  provisionOrganization,
  updateOrganizationPlan,
} from "../api/client";
import { Button } from "../components/primitives/Button";
import type { OrganizationView, UsageSummary } from "../types";
import "./AccountPage.css";

export function PlatformAdminPage() {
  const [organizations, setOrganizations] = useState<OrganizationView[]>([]);
  const [name, setName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [planCode, setPlanCode] = useState("team_beta");
  const [activationUrl, setActivationUrl] = useState("");
  const [usage, setUsage] = useState<Record<string, UsageSummary>>({});
  const [selectedOrganizationId, setSelectedOrganizationId] = useState("");
  const [planStatus, setPlanStatus] = useState("active");
  const [trialEnd, setTrialEnd] = useState("");
  const [overrides, setOverrides] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    listAdminOrganizations()
      .then(async (values) => {
        if (!active) return;
        setOrganizations(values);
        setSelectedOrganizationId((current) => current || values[0]?.organization_id || "");
        setPlanStatus(values[0]?.plan_status ?? "active");
        setTrialEnd(values[0]?.trial_ends_at?.slice(0, 10) ?? "");
        const summaries = await Promise.all(values.map(async (value) => [
          value.organization_id,
          await getOrganizationUsage(value.organization_id),
        ] as const));
        if (active) setUsage(Object.fromEntries(summaries));
      })
      .catch(() => setError("平台组织列表或用量加载失败。"));
    return () => {
      active = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const result = await provisionOrganization({ name, owner_email: ownerEmail, plan_code: planCode });
      setOrganizations((current) => [...current, result.organization]);
      setSelectedOrganizationId(result.organization.organization_id);
      setPlanStatus(result.organization.plan_status);
      setTrialEnd(result.organization.trial_ends_at?.slice(0, 10) ?? "");
      setActivationUrl(result.owner_invitation.activation_url ?? "");
      getOrganizationUsage(result.organization.organization_id)
        .then((summary) => setUsage((current) => ({
          ...current,
          [result.organization.organization_id]: summary,
        })))
        .catch(() => undefined);
      setName("");
      setOwnerEmail("");
    } catch (reason) {
      setError(`创建客户组织失败：${String(reason)}`);
    }
  }

  async function setPlan(organization: OrganizationView, nextPlan: string) {
    try {
      const value = await updateOrganizationPlan(organization.organization_id, {
        plan_code: nextPlan,
        plan_status: "active",
      });
      setOrganizations((current) => current.map((item) => item.organization_id === value.organization_id ? value : item));
      setUsage((current) => current[value.organization_id] ? ({
        ...current,
        [value.organization_id]: {
          ...current[value.organization_id],
          plan_code: value.plan_code,
          limits: value.entitlements,
        },
      }) : current);
    } catch (reason) {
      setError(`套餐更新失败：${String(reason)}`);
    }
  }

  async function applyOrganizationSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const organization = organizations.find((value) => value.organization_id === selectedOrganizationId);
    if (!organization) return;
    try {
      const parsedOverrides = overrides.trim()
        ? JSON.parse(overrides) as Record<string, number | boolean>
        : undefined;
      const value = await updateOrganizationPlan(organization.organization_id, {
        plan_code: organization.plan_code,
        plan_status: planStatus,
        trial_ends_at: trialEnd ? new Date(`${trialEnd}T23:59:59`).toISOString() : null,
        ...(parsedOverrides ? { entitlement_overrides: parsedOverrides } : {}),
      });
      setOrganizations((current) => current.map((item) => item.organization_id === value.organization_id ? value : item));
      const summary = await getOrganizationUsage(value.organization_id);
      setUsage((current) => ({ ...current, [value.organization_id]: summary }));
      setOverrides("");
    } catch (reason) {
      setError(`组织设置更新失败：${String(reason)}`);
    }
  }

  return (
    <div className="collection-page">
      <header className="collection-head"><div><h1>平台管理</h1><p className="account-muted">创建客户课题组、生成负责人激活链接并手工分配内测套餐。</p></div></header>
      {error && <div className="account-error" role="alert">{error}</div>}
      <section className="content-card">
        <h2>创建客户组织</h2>
        <form className="inline-form" onSubmit={submit}>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="课题组名称" required />
          <input type="email" value={ownerEmail} onChange={(event) => setOwnerEmail(event.target.value)} placeholder="负责人邮箱" required />
          <select value={planCode} onChange={(event) => setPlanCode(event.target.value)}>
            <option value="team_beta">Team Beta</option>
            <option value="free">Free</option>
          </select>
          <Button type="submit">创建并生成链接</Button>
        </form>
        {activationUrl && (
          <div className="copy-value" style={{ marginTop: "var(--space-4)" }}>
            <code>{activationUrl}</code>
            <Button size="sm" onClick={() => navigator.clipboard.writeText(activationUrl)}>复制激活链接</Button>
          </div>
        )}
      </section>

      <section className="content-card" style={{ marginTop: "var(--space-4)" }}>
        <h2>试用与单项额度</h2>
        <form className="inline-form" onSubmit={applyOrganizationSettings}>
          <select value={selectedOrganizationId} onChange={(event) => {
            const nextId = event.target.value;
            const selected = organizations.find((value) => value.organization_id === nextId);
            setSelectedOrganizationId(nextId);
            setPlanStatus(selected?.plan_status ?? "active");
            setTrialEnd(selected?.trial_ends_at?.slice(0, 10) ?? "");
          }}>
            {organizations.map((organization) => <option key={organization.organization_id} value={organization.organization_id}>{organization.name}</option>)}
          </select>
          <select value={planStatus} onChange={(event) => setPlanStatus(event.target.value)}>
            <option value="active">active</option>
            <option value="trialing">trialing</option>
            <option value="inactive">inactive / 只读</option>
          </select>
          <input type="date" value={trialEnd} onChange={(event) => setTrialEnd(event.target.value)} aria-label="试用截止日" />
          <input value={overrides} onChange={(event) => setOverrides(event.target.value)} placeholder={'额度覆盖 JSON，如 {"max_members":20}'} />
          <Button type="submit">应用设置</Button>
        </form>
        <p className="account-muted">额度 JSON 留空时保留现有覆盖；填写时会整体替换组织的覆盖项。</p>
      </section>

      <section className="content-card" style={{ marginTop: "var(--space-4)" }}>
        <h2>组织与套餐</h2>
        <table className="data-table">
          <thead><tr><th>组织</th><th>套餐</th><th>状态</th><th>本月用量</th><th>调整</th></tr></thead>
          <tbody>
            {organizations.map((organization) => (
              <tr key={organization.organization_id}>
                <td>{organization.name}<div className="account-muted">{organization.slug}</div></td>
                <td>{organization.plan_code}</td>
                <td>{organization.plan_status}</td>
                <td>{usage[organization.organization_id]
                  ? `AI ${usage[organization.organization_id].ai_tasks} · Chat ${usage[organization.organization_id].chat_turns} · 资料 ${usage[organization.organization_id].active_sources}`
                  : "-"}</td>
                <td>
                  <select value={organization.plan_code} onChange={(event) => setPlan(organization, event.target.value)}>
                    <option value="free">Free</option>
                    <option value="team_beta">Team Beta</option>
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
