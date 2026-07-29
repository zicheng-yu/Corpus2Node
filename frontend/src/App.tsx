import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ToastProvider } from "./components/primitives/Toast";
import { AppShell } from "./components/layout/AppShell";
import { CommandPalette } from "./components/layout/CommandPalette";
import { HomePage } from "./pages/HomePage";
import { NewSessionPage } from "./pages/NewSessionPage";
import { PipelinePage } from "./pages/PipelinePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { ActivatePage } from "./pages/ActivatePage";
import { SharePage } from "./pages/SharePage";
import {
  SettingsPanel,
  type SettingsPanelSection,
} from "./components/layout/SettingsPanel";

const WorkspacePage = lazy(() =>
  import("./pages/WorkspacePage").then((m) => ({ default: m.WorkspacePage })),
);
const DiscoverPage = lazy(() =>
  import("./pages/DiscoverPage").then((m) => ({ default: m.DiscoverPage })),
);

function SettingsRoute({ onOpen }: { onOpen: (section?: SettingsPanelSection) => void }) {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const section = new URLSearchParams(location.search).get("section") as SettingsPanelSection | null;
    onOpen(section ?? undefined);
    navigate("/", { replace: true });
  }, [location.search, navigate, onOpen]);

  return null;
}

function AppInner() {
  const [cmdOpen, setCmdOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsPanelSection>("appearance");
  const [graphStyle, setGraphStyle] = useState<string>(() => localStorage.getItem("c2n:graphStyle") ?? "force");
  const { mode } = useAuth();
  const accountsMode = mode === "accounts";

  const openSettings = useCallback((section?: SettingsPanelSection) => {
    setSettingsSection(section ?? (accountsMode ? "account" : "appearance"));
    setSettingsOpen(true);
  }, [accountsMode]);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);

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
        onOpenSettings={() => openSettings()}
      >
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects/:id" element={<Navigate to="/" replace />} />
          <Route path="/settings" element={<SettingsRoute onOpen={openSettings} />} />
          <Route path="/team" element={<Navigate to="/" replace />} />
          <Route path="/admin" element={<Navigate to="/" replace />} />
          <Route path="/new" element={<NewSessionPage />} />
          <Route
            path="/discover"
            element={
              <Suspense fallback={null}>
                <DiscoverPage />
              </Suspense>
            }
          />
          <Route path="/scientific" element={<Navigate to="/discover?mode=scientific" replace />} />
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
        onClose={closeSettings}
        initialSection={settingsSection}
        graphStyle={graphStyle}
        setGraphStyle={setGraphStyle}
      />
    </>
  );
}

function RoutedApp() {
  const location = useLocation();
  const { mode, user, loading, homePath } = useAuth();
  if (location.pathname === "/share") return <SharePage />;
  if (location.pathname === "/activate") return <ActivatePage />;
  if (loading) return <main className="account-page"><div className="empty-panel">正在连接账号…</div></main>;
  if (mode === "accounts" && !user) return <LoginPage />;
  if (mode === "accounts" && user && location.pathname === "/login") {
    return <Navigate to={homePath} replace />;
  }
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
