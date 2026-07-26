import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { changePassword } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { Button } from "../primitives/Button";

export function AccountSettings() {
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  if (!user) return null;

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (newPassword.length < 12) {
      setError("新密码至少需要 12 位。");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致。");
      return;
    }
    setSaving(true);
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setMessage("密码已更新，其他设备上的登录会话已撤销。");
    } catch {
      setError("密码修改失败，请确认当前密码是否正确。");
    } finally {
      setSaving(false);
    }
  }

  async function logout() {
    await signOut();
    navigate("/login");
  }

  return (
    <div className="settings-stack">
      <section className="content-card settings-profile-card">
        <div className="settings-avatar" aria-hidden="true">
          {(user.display_name || user.email).slice(0, 1).toUpperCase()}
        </div>
        <div>
          <h2>{user.display_name || "Corpus2Node 用户"}</h2>
          <p className="account-muted">{user.email}</p>
          <p className="settings-current-role">个人资料与模型配置仅当前账号可见</p>
        </div>
      </section>

      <section className="content-card">
        <h2>修改密码</h2>
        <p className="account-muted">修改后会撤销其他设备上的登录会话，当前设备保持登录。</p>
        <form className="settings-password-form" onSubmit={submitPassword}>
          <label>
            当前密码
            <input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required />
          </label>
          <label>
            新密码
            <input type="password" autoComplete="new-password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required />
          </label>
          <label>
            再次输入新密码
            <input type="password" autoComplete="new-password" minLength={12} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required />
          </label>
          {error && <div className="account-error" role="alert">{error}</div>}
          {message && <div className="settings-success" role="status">{message}</div>}
          <div><Button type="submit" loading={saving}>更新密码</Button></div>
        </form>
      </section>

      <section className="content-card settings-session-card">
        <div>
          <h2>登录会话</h2>
          <p className="account-muted">退出当前账号，返回登录页面。</p>
        </div>
        <Button variant="ghost" onClick={logout}>退出登录</Button>
      </section>
    </div>
  );
}
