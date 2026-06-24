import { Link, useLocation } from "react-router-dom";
import clsx from "clsx";
import "./TopBar.css";

interface TopBarProps {
  onOpenCmd?: () => void;
  onOpenSettings?: () => void;
}

export function TopBar({ onOpenCmd, onOpenSettings }: TopBarProps) {
  const location = useLocation();

  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <span className="brand-mark" />
        <span className="brand-text">
          corpus<span className="brand-accent">2</span>node
        </span>
        <span className="brand-sub">knowledge graph</span>
      </Link>

      <nav className="topbar-nav">
        <Link to="/" className={clsx({ active: location.pathname === "/" })}>
          知识库
        </Link>
        <Link to="/new" className={clsx({ active: location.pathname === "/new" })}>
          新建
        </Link>
      </nav>

      <div className="topbar-spacer" />

      <button className="topbar-cmd" onClick={onOpenCmd} type="button">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
        </svg>
        搜索…
        <kbd>⌘K</kbd>
      </button>

      <button className="btn btn-ghost btn-sm btn-icon" onClick={onOpenSettings} type="button" title="设置" style={{ width: "auto", padding: "5px 10px" }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
    </header>
  );
}
