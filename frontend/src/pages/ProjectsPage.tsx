import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { createProject, listProjects } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Button } from "../components/primitives/Button";
import type { ProjectView } from "../types";
import "./AccountPage.css";

const PROJECT_ADMIN_ROLES = new Set(["owner", "admin"]);

export function ProjectsPage() {
  const { user, activeOrganizationId } = useAuth();
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<"general" | "scientific">("general");
  const [error, setError] = useState("");
  const role = user?.memberships.find((item) => item.organization_id === activeOrganizationId)?.role;
  const canCreate = user?.is_platform_admin || (role ? PROJECT_ADMIN_ROLES.has(role) : false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listProjects()
      .then((values) => {
        if (active) setProjects(values);
      })
      .catch(() => {
        if (active) setError("项目列表加载失败，请检查当前组织权限。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [activeOrganizationId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const value = await createProject({ name, description, kind });
      setProjects((current) => [value, ...current]);
      setName("");
      setDescription("");
      setShowCreate(false);
    } catch (reason) {
      setError(`创建失败：${String(reason)}`);
    }
  }

  return (
    <div className="collection-page">
      <header className="collection-head">
        <div>
          <h1>团队项目</h1>
          <p className="account-muted">每个项目是一份稳定共享的课题知识库，文献完成抽取后会形成新的公共修订版。</p>
        </div>
        {canCreate && <Button onClick={() => setShowCreate((value) => !value)}>新建项目</Button>}
      </header>

      {showCreate && (
        <form className="content-card account-form" onSubmit={submit}>
          <h2>创建共享项目</h2>
          <label>项目名称<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
          <label>项目类型
            <select value={kind} onChange={(event) => setKind(event.target.value as "general" | "scientific") }>
              <option value="general">通用知识图谱</option>
              <option value="scientific">科研证据与研发机会</option>
            </select>
          </label>
          <label>说明<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} /></label>
          <div className="collection-toolbar">
            <Button type="submit">创建</Button>
            <Button type="button" variant="ghost" onClick={() => setShowCreate(false)}>取消</Button>
          </div>
        </form>
      )}

      {error && <div className="account-error" role="alert">{error}</div>}
      {loading ? (
        <div className="empty-panel">加载项目中…</div>
      ) : projects.length === 0 ? (
        <div className="empty-panel">当前组织还没有项目。{canCreate ? "先创建一个项目，再邀请成员共同维护。" : "请联系管理员创建项目。"}</div>
      ) : (
        <div className="project-grid">
          {projects.map((project) => (
            <Link className="project-card" to={`/projects/${project.project_id}`} key={project.project_id}>
              <h2>{project.name}</h2>
              <p className="account-muted">{project.description || (project.kind === "scientific" ? "科研证据协作项目" : "团队知识图谱项目")}</p>
              <div className="project-meta">
                <span>{project.kind === "scientific" ? "科研" : "通用"}</span>
                <span>{project.session_count} 篇资料</span>
                <span>{project.latest_revision_id ? "已有公共版本" : "待首次构建"}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
