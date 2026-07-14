import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/primitives/Button";
import "./AccountPage.css";

export function ActivatePage() {
  const navigate = useNavigate();
  const { activate } = useAuth();
  const token = useMemo(() => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "", []);
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirm) {
      setError("两次输入的密码不一致。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await activate(token, displayName, password);
      window.history.replaceState(null, "", "/activate");
      navigate("/", { replace: true });
    } catch {
      setError("激活链接无效、已使用或已过期，请让管理员重新生成链接。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="account-page">
      <section className="account-card" aria-labelledby="activate-title">
        <div className="account-brand"><span className="brand-mark" /> corpus2node</div>
        <h1 id="activate-title">激活账号</h1>
        <p className="account-muted">设置姓名与密码后，即可进入所属课题组。链接仅能使用一次。</p>
        {!token ? (
          <div className="account-error" role="alert">链接中缺少激活 token，请使用管理员发来的完整链接。</div>
        ) : (
          <form className="account-form" onSubmit={submit}>
            <label>
              姓名
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
            </label>
            <label>
              新密码（至少 12 位）
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="new-password"
                minLength={12}
                required
              />
            </label>
            <label>
              再次输入密码
              <input
                type="password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                autoComplete="new-password"
                minLength={12}
                required
              />
            </label>
            {error && <div className="account-error" role="alert">{error}</div>}
            <Button type="submit" loading={submitting}>完成激活</Button>
          </form>
        )}
      </section>
    </main>
  );
}
