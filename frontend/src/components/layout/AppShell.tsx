import { type ReactNode } from "react";
import { TopBar } from "./TopBar";
import "./AppShell.css";

interface AppShellProps {
  children: ReactNode;
  onOpenCmd?: () => void;
  onOpenTweaks?: () => void;
}

export function AppShell({ children, onOpenCmd, onOpenTweaks }: AppShellProps) {
  return (
    <div className="app-shell">
      <TopBar onOpenCmd={onOpenCmd} onOpenTweaks={onOpenTweaks} />
      <main className="app-shell-content">{children}</main>
    </div>
  );
}
