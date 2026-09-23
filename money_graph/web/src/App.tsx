import { useEffect, useRef, useState } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  Link,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Activity,
  Bot,
  ArrowUpRight,
  Command,
  FileText,
  FolderOpen,
  HelpCircle,
  LayoutDashboard,
  List,
  Menu,
  Moon,
  Network,
  Search,
  Settings2,
  ShieldCheck,
  ShieldOff,
  Sun,
  X,
} from "lucide-react";
import { useWorkspace } from "./store";
import { api, root } from "./api";
import type { NodeRow, Project } from "./types";
import { Projects, UploadWizard } from "./Projects";
import { Dashboard } from "./Dashboard";
import { Investigation } from "./Investigation";
import { NodeTable } from "./NodeTable";
import {
  Cases,
  Clusters,
  RuleSettings,
  SimulationScreen,
} from "./AnalysisTools";
import { ErrorBox, Loading, Modal, RoleBadge } from "./components";
import "./i18n";
import { Assistant } from "./Assistant";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15000, retry: 1, refetchOnWindowFocus: false },
  },
});
function Shell() {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const nav = useNavigate();
  const pid = location.pathname.match(/^\/projects\/([^/]+)/)?.[1] || "";
  const [command, setCommand] = useState(false);
  const [help, setHelp] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [search, setSearch] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const state = useWorkspace();
  const previousPath = useRef(location.pathname);
  useEffect(() => {
    if (previousPath.current !== location.pathname) {
      document.getElementById("main-content")?.focus();
      previousPath.current = location.pathname;
    }
    document.title =
      t(location.pathname.split("/").pop() || "projects") + " · " + t("brand");
  }, [location.pathname, t]);
  const project = useQuery({
    queryKey: ["project", pid],
    queryFn: () => api<Project>(root(pid)),
    enabled: !!pid,
  });
  const results = useQuery({
    queryKey: ["command", pid, search],
    queryFn: () =>
      api<{ items: NodeRow[]; total: number }>(
        root(pid) + "/nodes?q=" + encodeURIComponent(search) + "&limit=12",
      ),
    enabled: command && !!pid && !location.pathname.endsWith("/upload"),
  });
  useEffect(() => {
    document.documentElement.dataset.theme = state.theme;
    document.documentElement.lang = state.language;
    void i18n.changeLanguage(state.language);
  }, [state.theme, state.language, i18n]);
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommand(true);
      }
      if ((e.target as HTMLElement).matches("input,textarea,select")) return;
      if (!useWorkspace.getState().shortcuts) return;
      if (e.key === "/") {
        e.preventDefault();
        setCommand(true);
      }
      if (e.key === "?") setHelp(true);
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const navigation = [
    ["overview", LayoutDashboard],
    ["investigate", Network],
    ["nodes", List],
    ["clusters", Activity],
    ["simulate", ShieldOff],
    ["settings", Settings2],
    ["cases", FileText],
    ["assistant", Bot],
  ] as const;
  return (
    <div className="app-shell">
      <aside
        aria-label={t("projects")}
        className={"sidebar " + (mobile ? "mobile-open" : "")}
      >
        <Link to="/" className="brand">
          <span className="brand-symbol">
            <Network size={25} />
          </span>
          <span>
            {t("brand")}
            <small>INVESTIGATION WORKSPACE</small>
          </span>
        </Link>
        <Link
          className={"project-nav " + (!pid ? "active" : "")}
          to="/"
          onClick={() => setMobile(false)}
        >
          <FolderOpen size={18} />
          {t("projects")}
        </Link>
        {pid && (
          <>
            <div className="nav-caption">WORKSPACE</div>
            <nav>
              {navigation.map(([path, Icon]) => (
                <NavLink
                  key={path}
                  to={
                    "/projects/" +
                    pid +
                    "/" +
                    path +
                    (["nodes", "investigate", "assistant"].includes(path)
                      ? location.search
                      : "")
                  }
                  onClick={() => setMobile(false)}
                >
                  <Icon size={18} />
                  {t(path)}
                </NavLink>
              ))}
            </nav>
          </>
        )}
        <div className="sidebar-footer">
          <button onClick={() => setHelp(true)}>
            <HelpCircle size={18} />
            {t("help")}
          </button>
          <div>
            <ShieldCheck size={17} />
            <span>{t("local")}</span>
          </div>
          <small>LOCAL / OFFLINE</small>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            aria-label="Menu"
            onClick={() => setMobile(!mobile)}
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumbs">
            <Link to="/">{t("projects")}</Link>
            {pid && (
              <>
                <span>/</span>
                <strong>{project.data?.name || "…"}</strong>
              </>
            )}
          </div>
          <div className="topbar-actions">
            <button className="command-button" onClick={() => setCommand(true)}>
              <Search size={16} />
              <span>{t("search")}</span>
              <kbd>⌘ K</kbd>
            </button>
            <select
              aria-label="Language"
              value={state.language}
              onChange={(e) => state.setLanguage(e.target.value)}
            >
              <option value="ru">RU</option>
              <option value="kk">ҚАЗ</option>
              <option value="en">EN</option>
            </select>
            <button
              className="icon-button"
              aria-label="Theme"
              onClick={state.setTheme}
            >
              {state.theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
            </button>
            <span className="avatar">AN</span>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <Routes>
            <Route path="/" element={<Projects />} />
            <Route path="/projects/:pid/upload" element={<UploadWizard />} />
            <Route path="/projects/:pid/overview" element={<Dashboard />} />
            <Route
              path="/projects/:pid/investigate"
              element={<Investigation />}
            />
            <Route path="/projects/:pid/nodes" element={<NodeTable />} />
            <Route path="/projects/:pid/clusters" element={<Clusters />} />
            <Route
              path="/projects/:pid/simulate"
              element={<SimulationScreen />}
            />
            <Route path="/projects/:pid/settings" element={<RuleSettings />} />
            <Route path="/projects/:pid/cases" element={<Cases />} />
            <Route path="/projects/:pid/assistant" element={<Assistant />} />
            <Route path="*" element={<Projects />} />
          </Routes>
        </main>
        <footer className="app-footer">
          <span>{t("hypothesis")}</span>
          <button className="text-button" onClick={() => setHelp(true)}>
            ?
          </button>
        </footer>
      </div>
      <Modal
        open={command}
        returnSelector=".command-button"
        onClose={() => setCommand(false)}
        title={t("search")}
      >
        <input
          ref={input}
          autoFocus
          value={search}
          aria-label={t("search")}
          placeholder={t("searchHint")}
          onChange={(e) => setSearch(e.target.value)}
        />
        {!pid ? (
          <p>{t("projects")}</p>
        ) : results.isFetching ? (
          <Loading />
        ) : results.error ? (
          <ErrorBox error={results.error} />
        ) : (
          <div className="command-results">
            {results.data?.items.map((n) => (
              <button
                key={n.gid}
                onClick={() => {
                  nav(
                    "/projects/" +
                      pid +
                      "/investigate?node=" +
                      encodeURIComponent(n.gid),
                  );
                  setCommand(false);
                }}
              >
                <code>{n.gid}</code>
                <RoleBadge role={n.role} />
                <ArrowUpRight size={16} />
              </button>
            ))}
          </div>
        )}
      </Modal>
      <Modal open={help} onClose={() => setHelp(false)} title={t("help")} returnSelector=".sidebar-footer button">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={state.shortcuts}
            onChange={(e) => state.setShortcuts(e.target.checked)}
          />
          {t("characterShortcuts")}
        </label>
        <p>{t("helpText")}</p>
        <hr />
        <p>{t("glossary")}</p>
      </Modal>
    </div>
  );
}
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
