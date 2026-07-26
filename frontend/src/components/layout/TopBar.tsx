import { Link, useLocation } from "react-router-dom";
import clsx from "clsx";
import { useAuth } from "../../auth/AuthContext";
import type { PersonaNavItem } from "../../types";
import "./TopBar.css";

interface TopBarProps {
  onOpenCmd?: () => void;
  onOpenSettings?: () => void;
}

const NAV_LABELS: Record<PersonaNavItem, { to: string; label: (accountsMode: boolean) => string }> = {
  home: { to: "/", label: (accountsMode) => (accountsMode ? "项目" : "知识库") },
  new: { to: "/new", label: () => "新建" },
  discover: { to: "/discover?mode=scientific", label: () => "发现" },
  workspace: { to: "/", label: () => "工作区" },
};

export function TopBar({ onOpenCmd, onOpenSettings }: TopBarProps) {
  const location = useLocation();
  const { mode, profile, homePath, navItems } = useAuth();
  const accountsMode = mode === "accounts";
  const productName = profile.brand.product_name || "corpus2node";
  const tagline = profile.brand.tagline || "knowledge graph";
  const isLongxinBrand = profile.customer_id === "longxin";

  const items = navItems.length > 0 ? navItems : (["home", "new"] as PersonaNavItem[]);

  return (
    <header className="topbar">
      <Link to={homePath} className="brand">
        <span className="brand-mark" />
        <span className="brand-text">
          {isLongxinBrand ? (
            productName
          ) : (
            <>
              corpus<span className="brand-accent">2</span>node
            </>
          )}
        </span>
        <span className="brand-sub">{tagline}</span>
      </Link>

      <nav className="topbar-nav">
        {items.map((item) => {
          const meta = NAV_LABELS[item];
          if (!meta) return null;
          const pathOnly = meta.to.split("?")[0];
          const active =
            item === "discover"
              ? location.pathname === "/discover"
              : location.pathname === pathOnly;
          return (
            <Link key={item} to={meta.to} className={clsx({ active })}>
              {meta.label(accountsMode)}
            </Link>
          );
        })}
      </nav>

      <div className="topbar-spacer" />

      <button className="topbar-cmd" onClick={onOpenCmd} type="button">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
        </svg>
        搜索…
        <kbd>⌘K</kbd>
      </button>

      <button className="btn btn-ghost btn-sm btn-icon topbar-settings" type="button" onClick={onOpenSettings} title="设置" aria-label="设置">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82-.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
    </header>
  );
}
