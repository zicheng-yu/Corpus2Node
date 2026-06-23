import { Link, useLocation } from "react-router-dom";
import clsx from "clsx";
import "./TopBar.css";

interface TopBarProps {
  onOpenCmd?: () => void;
  onOpenTweaks?: () => void;
}

export function TopBar({ onOpenCmd, onOpenTweaks }: TopBarProps) {
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

      <button className="btn btn-ghost btn-sm btn-icon" onClick={onOpenTweaks} type="button" title="外观设置" style={{ width: "auto", padding: "5px 10px" }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="4" y1="6" x2="20" y2="6" />
          <line x1="8" y1="12" x2="20" y2="12" />
          <line x1="12" y1="18" x2="20" y2="18" />
          <circle cx="4" cy="6" r="2" fill="currentColor" stroke="none" />
          <circle cx="8" cy="12" r="2" fill="currentColor" stroke="none" />
          <circle cx="12" cy="18" r="2" fill="currentColor" stroke="none" />
        </svg>
      </button>
    </header>
  );
}
