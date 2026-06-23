import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/primitives/Toast";
import { AppShell } from "./components/layout/AppShell";
import { CommandPalette } from "./components/layout/CommandPalette";
import { TweaksPanel } from "./components/layout/TweaksPanel";
import { HomePage } from "./pages/HomePage";
import { NewSessionPage } from "./pages/NewSessionPage";
import { PipelinePage } from "./pages/PipelinePage";
import { NotFoundPage } from "./pages/NotFoundPage";

const WorkspacePage = lazy(() =>
  import("./pages/WorkspacePage").then((m) => ({ default: m.WorkspacePage })),
);

function AppInner() {
  const [cmdOpen, setCmdOpen] = useState(false);
  const [tweaksOpen, setTweaksOpen] = useState(false);
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
        onOpenTweaks={() => setTweaksOpen((v) => !v)}
      >
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/new" element={<NewSessionPage />} />
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
      <TweaksPanel
        open={tweaksOpen}
        onClose={() => setTweaksOpen(false)}
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
