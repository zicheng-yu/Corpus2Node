import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ToastProvider } from "./components/primitives/Toast";
import { AppShell } from "./components/layout/AppShell";
import { CommandPalette } from "./components/layout/CommandPalette";
import { SettingsPanel } from "./components/layout/SettingsPanel";
import { HomePage } from "./pages/HomePage";
import { NewSessionPage } from "./pages/NewSessionPage";
import { PipelinePage } from "./pages/PipelinePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { ActivatePage } from "./pages/ActivatePage";
import { SharePage } from "./pages/SharePage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectPage } from "./pages/ProjectPage";
import { TeamSettingsPage } from "./pages/TeamSettingsPage";
import { PlatformAdminPage } from "./pages/PlatformAdminPage";

const WorkspacePage = lazy(() =>
  import("./pages/WorkspacePage").then((m) => ({ default: m.WorkspacePage })),
);
const ScientificPage = lazy(() =>
  import("./pages/ScientificPage").then((m) => ({ default: m.ScientificPage })),
);

function AppInner() {
  const [cmdOpen, setCmdOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [graphStyle, setGraphStyle] = useState<string>(() => localStorage.getItem("c2n:graphStyle") ?? "force");
  const { mode, user } = useAuth();
  const accountsMode = mode === "accounts";

  // Force default theme
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", "copper");
  }, []);

  useEffect(() => {
    localStorage.setItem("c2n:graphStyle", graphStyle);
  }, [graphStyle]);

  // Global ⌘K shortcut
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen((v) => !v);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <>
      <AppShell
        onOpenCmd={() => setCmdOpen(true)}
        onOpenSettings={() => setSettingsOpen((v) => !v)}
      >
        <Routes>
          <Route path="/" element={accountsMode ? <ProjectsPage /> : <HomePage />} />
          <Route path="/projects/:id" element={accountsMode ? <ProjectPage /> : <Navigate to="/" replace />} />
          <Route path="/team" element={accountsMode ? <TeamSettingsPage /> : <Navigate to="/" replace />} />
          <Route path="/admin" element={accountsMode && user?.is_platform_admin ? <PlatformAdminPage /> : <Navigate to="/" replace />} />
          <Route path="/new" element={<NewSessionPage />} />
          <Route
            path="/scientific"
            element={
              <Suspense fallback={null}>
                <ScientificPage />
              </Suspense>
            }
          />
          <Route path="/session/:id/pipeline" element={<PipelinePage />} />
          <Route
            path="/session/:id"
            element={
              <Suspense fallback={null}>
                <WorkspacePage graphStyle={graphStyle} />
              </Suspense>
            }
          />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </AppShell>

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        graphStyle={graphStyle}
        setGraphStyle={setGraphStyle}
      />
    </>
  );
}

function RoutedApp() {
  const location = useLocation();
  const { mode, user, loading } = useAuth();
  if (location.pathname === "/share") return <SharePage />;
  if (location.pathname === "/activate") return <ActivatePage />;
  if (loading) return <main className="account-page"><div className="empty-panel">正在连接工作区…</div></main>;
  if (mode === "accounts" && !user) return <LoginPage />;
  if (mode === "accounts" && user && location.pathname === "/login") return <Navigate to="/" replace />;
  return <AppInner />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <RoutedApp />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
