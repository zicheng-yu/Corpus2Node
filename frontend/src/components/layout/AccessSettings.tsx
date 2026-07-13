import { useState } from "react";
import {
  getApiAuthToken,
  listSessions,
  setApiAuthToken,
} from "../../api/client";
import { Button } from "../primitives/Button";
import { useToast } from "../primitives/Toast";

export function AccessSettings() {
  const [token, setToken] = useState(getApiAuthToken);
  const [checking, setChecking] = useState(false);
  const toast = useToast();

  async function saveAndVerify() {
    const previous = getApiAuthToken();
    setApiAuthToken(token);
    setChecking(true);
    try {
      await listSessions();
      toast("访问令牌已保存并验证", "success");
    } catch {
      setApiAuthToken(previous);
      setToken(previous);
      toast("令牌验证失败，已恢复原设置", "error");
    } finally {
      setChecking(false);
    }
  }

  function clear() {
    setApiAuthToken("");
    setToken("");
    toast("已清除本机保存的访问令牌", "success");
  }

  return (
    <section className="set-section">
      <h3 className="set-section-title">API 访问令牌</h3>
      <p className="set-section-desc">
        生产部署必须配置同一枚 API_AUTH_TOKEN。令牌只保存在当前浏览器的 localStorage，
        所有 API、上传与 SSE 请求都会自动携带；远程访问仍应由 HTTPS 反向代理保护。
      </p>
      <div className="set-form">
        <label className="set-field set-field-wide">
          <span>Bearer token</span>
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            autoComplete="off"
            placeholder="与部署环境 API_AUTH_TOKEN 一致"
          />
        </label>
        <div className="set-form-actions">
          <button className="set-mini-btn" type="button" onClick={clear}>清除</button>
          <Button size="sm" loading={checking} onClick={saveAndVerify}>保存并验证</Button>
        </div>
      </div>
    </section>
  );
}
