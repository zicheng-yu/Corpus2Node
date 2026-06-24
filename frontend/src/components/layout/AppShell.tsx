import { type ReactNode } from "react";
import { TopBar } from "./TopBar";
import "./AppShell.css";

interface AppShellProps {
  children: ReactNode;
  onOpenCmd?: () => void;
  onOpenSettings?: () => void;
}

export function AppShell({ children, onOpenCmd, onOpenSettings }: AppShellProps) {
  return (
    <div className="app-shell">
      <TopBar onOpenCmd={onOpenCmd} onOpenSettings={onOpenSettings} />
      <main className="app-shell-content">{children}</main>
    </div>
  );
}
