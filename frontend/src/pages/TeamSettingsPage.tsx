import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  deactivateMember,
  getOrganizationUsage,
  inviteMember,
  listInvitations,
  listMembers,
  listOrganizations,
  revokeInvitation,
  updateMemberRole,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/primitives/Button";
import type { InvitationView, MemberView, OrganizationRole, OrganizationView, UsageSummary } from "../types";
import "./AccountPage.css";

const ADMIN_ROLES = new Set(["owner", "admin"]);

interface TeamSettingsPageProps {
  embedded?: boolean;
}

export function TeamSettingsPage({ embedded = false }: TeamSettingsPageProps) {
  const { user, activeOrganizationId } = useAuth();
  const [organization, setOrganization] = useState<OrganizationView | null>(null);
  const [members, setMembers] = useState<MemberView[]>([]);
  const [invitations, setInvitations] = useState<InvitationView[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrganizationRole>("member");
  const [error, setError] = useState("");
  const membership = user?.memberships.find((item) => item.organization_id === activeOrganizationId);
  const canAdmin = user?.is_platform_admin || (membership ? ADMIN_ROLES.has(membership.role) : false);
  const isOwner = user?.is_platform_admin || membership?.role === "owner";

  useEffect(() => {
    let active = true;
    if (!activeOrganizationId) return;
    Promise.all([
      listOrganizations(),
      listMembers(activeOrganizationId),
      getOrganizationUsage(activeOrganizationId),
      canAdmin ? listInvitations(activeOrganizationId) : Promise.resolve([]),
    ])
      .then(([organizations, memberValues, usageValue, invitationValues]) => {
        if (!active) return;
        setOrganization(organizations.find((value) => value.organization_id === activeOrganizationId) ?? null);
        setMembers(memberValues);
        setUsage(usageValue);
        setInvitations(invitationValues);
      })
      .catch(() => {
        if (active) setError("团队设置加载失败。");
      });
    return () => {
      active = false;
    };
  }, [activeOrganizationId, canAdmin]);

  const metrics = useMemo(() => {
    if (!usage) return [];
    return [
      ["成员", members.filter((value) => value.status === "active").length, usage.limits.max_members],
      ["活跃资料", usage.active_sources, usage.limits.max_active_sources],
      ["本月 AI 任务", usage.ai_tasks, usage.limits.max_ai_tasks_month],
      ["本月 Chat", usage.chat_turns, usage.limits.max_chat_turns_month],
    ] as const;
  }, [usage, members]);

  async function submitInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const value = await inviteMember(activeOrganizationId, { email, role });
      setInvitations((current) => [value, ...current]);
      setEmail("");
    } catch (reason) {
      setError(`邀请失败：${String(reason)}`);
    }
  }

  async function changeRole(member: MemberView, nextRole: OrganizationRole) {
    try {
      const value = await updateMemberRole(activeOrganizationId, member.user_id, nextRole);
      setMembers((current) => current.map((item) => item.user_id === value.user_id ? value : item));
    } catch (reason) {
      setError(`角色更新失败：${String(reason)}`);
    }
  }

  async function removeMember(member: MemberView) {
    try {
      await deactivateMember(activeOrganizationId, member.user_id);
      setMembers((current) => current.map((item) => item.user_id === member.user_id ? { ...item, status: "inactive" } : item));
    } catch (reason) {
      setError(`停用失败：${String(reason)}`);
    }
  }

  async function cancelInvitation(invitation: InvitationView) {
    try {
      await revokeInvitation(activeOrganizationId, invitation.invitation_id);
      setInvitations((current) => current.filter((item) => item.invitation_id !== invitation.invitation_id));
    } catch (reason) {
      setError(`撤销失败：${String(reason)}`);
    }
  }

  return (
    <div className="collection-page">
      {!embedded && (
        <header className="collection-head">
          <div>
            <h1>{organization?.name ?? "团队设置"}</h1>
            <p className="account-muted">{organization?.plan_code === "team_beta" ? "Team Beta" : "Free"} · {organization?.plan_status ?? ""}</p>
          </div>
        </header>
      )}
      {embedded && (
        <p className="account-muted">
          {organization?.name ?? "当前工作区"} · {organization?.plan_code === "team_beta" ? "Team Beta" : "Free"} · {organization?.plan_status ?? ""}
        </p>
      )}
      {error && <div className="account-error" role="alert">{error}</div>}

      <div className="metric-grid">
        {metrics.map(([label, value, limit]) => (
          <div className="metric-card" key={label}><span>{label}</span><strong>{value} / {String(limit)}</strong></div>
        ))}
      </div>

      {canAdmin && (
        <section className="content-card">
          <h2>邀请成员</h2>
          <p className="account-muted">系统不会自动发邮件。生成链接后，请复制并通过微信或邮件发给成员。</p>
          <form className="inline-form" onSubmit={submitInvite}>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="member@example.com" required />
            <select value={role} onChange={(event) => setRole(event.target.value as OrganizationRole)}>
              <option value="member">member</option>
              <option value="viewer">viewer</option>
              {isOwner && <option value="admin">admin</option>}
            </select>
            <Button type="submit">生成邀请链接</Button>
          </form>
          {invitations.length > 0 && (
            <div className="card-list" style={{ marginTop: "var(--space-4)" }}>
              {invitations.filter((value) => !value.accepted_at).map((invitation) => (
                <div className="copy-value" key={invitation.invitation_id}>
                  <code>{invitation.activation_url ?? `${invitation.email}（链接只在创建时显示）`}</code>
                  {invitation.activation_url && <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(invitation.activation_url ?? "")}>复制</Button>}
                  <Button size="sm" variant="ghost" onClick={() => cancelInvitation(invitation)}>撤销</Button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="content-card" style={{ marginTop: "var(--space-4)" }}>
        <h2>成员</h2>
        <table className="data-table">
          <thead><tr><th>成员</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.user_id}>
                <td>{member.display_name || member.email}<div className="account-muted">{member.email}</div></td>
                <td>
                  {isOwner && member.user_id !== user?.user_id ? (
                    <select value={member.role} onChange={(event) => changeRole(member, event.target.value as OrganizationRole)}>
                      <option value="owner">owner</option><option value="admin">admin</option>
                      <option value="member">member</option><option value="viewer">viewer</option>
                    </select>
                  ) : member.role}
                </td>
                <td>{member.status}</td>
                <td>{isOwner && member.user_id !== user?.user_id && member.status === "active" && <Button size="sm" variant="ghost" onClick={() => removeMember(member)}>停用</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
