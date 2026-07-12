import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/primitives/Toast";
import { AppShell } from "./components/layout/AppShell";
import { CommandPalette } from "./components/layout/CommandPalette";
import { SettingsPanel } from "./components/layout/SettingsPanel";
import { HomePage } from "./pages/HomePage";
import { NewSessionPage } from "./pages/NewSessionPage";
import { PipelinePage } from "./pages/PipelinePage";
import { NotFoundPage } from "./pages/NotFoundPage";

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
          <Route path="/" element={<HomePage />} />
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

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppInner />
      </ToastProvider>
    </BrowserRouter>
  );
}
