import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/primitives/Button";
import "./AccountPage.css";

export function LoginPage() {
  const { user, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await signIn(email, password);
    } catch {
      setError("邮箱或密码不正确，或账号已被停用。请联系邀请人确认账号状态。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="account-page">
      <section className="account-card" aria-labelledby="login-title">
        <div className="account-brand"><span className="brand-mark" /> corpus2node</div>
        <h1 id="login-title">登录内测工作区</h1>
        <p className="account-muted">当前为邀请制内测，请使用负责人提供的账号登录。</p>
        <form className="account-form" onSubmit={submit}>
          <label>
            邮箱
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              minLength={12}
              required
            />
          </label>
          {error && <div className="account-error" role="alert">{error}</div>}
          <Button type="submit" loading={submitting}>登录</Button>
        </form>
      </section>
    </main>
  );
}
