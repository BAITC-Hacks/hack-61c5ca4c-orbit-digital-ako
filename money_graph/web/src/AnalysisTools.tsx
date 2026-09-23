import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ResponsiveContainer,
  Sankey,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import {
  ArrowUpRight,
  Download,
  FileText,
  FolderPlus,
  Network,
  Save,
  ShieldOff,
  X,
} from "lucide-react";
import { api, post, put, root } from "./api";
import type {
  Cluster,
  Simulation,
  Summary,
  NodeRow,
  CaseFile,
  Project,
  Config,
  GraphData,
} from "./types";
import { useWorkspace, emptySelection } from "./store";
import {
  Loading,
  ErrorBox,
  Empty,
  JobProgress,
  RoleBadge,
  Toast,
  useFormat,
  roleColors,
} from "./components";

function ClusterMini({ pid, cid }: { pid: string; cid: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const query = useQuery({
    queryKey: ["cluster-mini", pid, cid],
    queryFn: () =>
      api<GraphData>(root(pid) + "/clusters/" + cid + "/graph?limit=24"),
    enabled: visible,
  });
  const graph = query.data;
  const positions = new Map(
    (graph?.nodes || []).map((n, i) => [
      n.gid,
      {
        x: 140 + Math.cos(i * 2.399963) * Math.sqrt(i + 1) * 11,
        y: 48 + Math.sin(i * 2.399963) * Math.sqrt(i + 1) * 8,
      },
    ]),
  );
  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 280 96"
        className="cluster-mini"
        aria-label="Cluster subgraph"
        role="img"
      >
        {graph?.edges.map((e, i) => (
          <line
            key={i}
            x1={positions.get(e.src)?.x}
            y1={positions.get(e.src)?.y}
            x2={positions.get(e.dst)?.x}
            y2={positions.get(e.dst)?.y}
            stroke="#a0b8c0"
            strokeWidth=".6"
          />
        ))}
        {graph?.nodes.map((n) => (
          <circle
            key={n.gid}
            cx={positions.get(n.gid)?.x}
            cy={positions.get(n.gid)?.y}
            r={n.is_seed ? 4 : 2.7}
            fill={roleColors[n.role]}
          />
        ))}
      </svg>
    </div>
  );
}

export function Clusters() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ["clusters", pid],
    queryFn: () => api<Cluster[]>(root(pid) + "/clusters"),
  });
  const summary = useQuery({
    queryKey: ["summary", pid],
    queryFn: () => api<Summary>(root(pid) + "/summary"),
  });
  const f = useFormat(summary.data?.currency);
  const [sort, setSort] = useState("seed");
  const list = [...(query.data || [])].sort((a, b) =>
    sort === "seed"
      ? b.n_seed - a.n_seed || b.sum_kzt_internal - a.sum_kzt_internal
      : b.sum_kzt_internal - a.sum_kzt_internal,
  );
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">Louvain · {t("hypothesis")}</div>
          <h1>{t("clusters")}</h1>
        </div>
        <select
          aria-label={t("clusters")}
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          <option value="seed">Seed ↓</option>
          <option value="amount">{t("turnover")} ↓</option>
        </select>
      </div>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} />
      ) : (
        <div className="cluster-grid">
          {list.map((c) => (
            <article className="cluster-card panel" key={c.cluster_id}>
              <div className="flex justify-between">
                <span className="cluster-number">
                  #{String(c.cluster_id).padStart(2, "0")}
                </span>
                <span className="seed-badge">{c.n_seed} seed</span>
              </div>
              <h2>
                {c.n_nodes} {t("nodes").toLowerCase()}
              </h2>
              <ClusterMini pid={pid} cid={c.cluster_id} />
              <strong className="cluster-amount">
                {f.money(c.sum_kzt_internal)}
              </strong>
              <div className="cluster-role-bar">
                <i
                  style={{
                    width: (c.n_coordinator / c.n_nodes) * 100 + "%",
                    background: "#d55e00",
                  }}
                />
                <i
                  style={{
                    width: (c.n_consolidator / c.n_nodes) * 100 + "%",
                    background: "#0072b2",
                  }}
                />
                <i
                  style={{
                    width: (c.n_truncated / c.n_nodes) * 100 + "%",
                    background: "#567487",
                  }}
                />
              </div>
              <p>{c.hypothesis}</p>
              <div className="cluster-top">
                {c.top_gids.split(";").map((id) => (
                  <Link
                    key={id}
                    to={
                      "/projects/" +
                      pid +
                      "/investigate?node=" +
                      encodeURIComponent(id)
                    }
                  >
                    {id}
                    <ArrowUpRight size={13} />
                  </Link>
                ))}
              </div>
              <Link
                className="button"
                to={"/projects/" + pid + "/investigate?cluster=" + c.cluster_id}
              >
                {t("investigate")}
                <Network size={16} />
              </Link>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export function SimulationScreen() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const selection = useWorkspace((s) => s.selections[pid] || emptySelection);
  const add = useWorkspace((s) => s.add);
  const remove = useWorkspace((s) => s.remove);
  const save = useWorkspace((s) => s.scenario);
  const [n, setN] = useState(5);
  const [toast, setToast] = useState("");
  const [manual, setManual] = useState("");
  const [error, setError] = useState<unknown>();
  const summary = useQuery({
    queryKey: ["summary", pid],
    queryFn: () => api<Summary>(root(pid) + "/summary"),
  });
  const f = useFormat(summary.data?.currency);
  const query = useQuery({
    queryKey: ["simulation", pid, selection.block],
    queryFn: () =>
      post<Simulation>(root(pid) + "/simulate/block", { ids: selection.block }),
    enabled: selection.block.length > 0,
    retry: false,
  });
  async function top() {
    try {
      const data = await api<{ items: NodeRow[] }>(
        root(pid) + "/nodes?limit=" + n,
      );
      add(
        pid,
        "block",
        data.items.map((x) => x.gid),
      );
    } catch (e) {
      setError(e);
    }
  }
  const s = query.data;
  return (
    <div className="page simulation-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">{t("hypothesis")}</div>
          <h1>{t("simulate")}</h1>
        </div>
        <ShieldOff className="accent" size={28} />
      </div>
      <div className="simulation-grid">
        <aside aria-label={t("selection")} className="panel">
          <h2>{t("selection")}</h2>
          <div className="form-grid">
            <input
              aria-label={t("topN")}
              type="number"
              min={1}
              max={100}
              value={n}
              onChange={(e) =>
                setN(Math.max(1, Math.min(100, Number(e.target.value))))
              }
            />
            <button onClick={() => void top()}>{t("topN")}</button>
          </div>
          <form
            className="actions"
            onSubmit={(e) => {
              e.preventDefault();
              if (manual.trim()) {
                add(pid, "block", [manual.trim()]);
                setManual("");
              }
            }}
          >
            <input
              aria-label="ID"
              placeholder="ID"
              value={manual}
              onChange={(e) => setManual(e.target.value)}
            />
            <button aria-label={t("toBlock")}>+</button>
          </form>
          <div className="selected-list">
            {selection.block.map((id) => (
              <div key={id}>
                <Link
                  className="mono"
                  to={
                    "/projects/" +
                    pid +
                    "/investigate?node=" +
                    encodeURIComponent(id)
                  }
                >
                  {id}
                </Link>
                <button
                  className="icon-button"
                  aria-label={t("close") + " " + id}
                  onClick={() => remove(pid, "block", id)}
                >
                  <X size={15} />
                </button>
              </div>
            ))}
          </div>
          <p className="muted">{t("hypothesis")}</p>
        </aside>
        <div className="simulation-output">
          {query.isFetching && <Loading />}
          {query.error ? <ErrorBox error={query.error} /> : null}
          {error ? <ErrorBox error={error} /> : null}
          {!selection.block.length ? (
            <Empty>{t("noSelection")}</Empty>
          ) : (
            s && (
              <>
                <div className="simulation-result">
                  <div className="eyebrow">{t("remaining")}</div>
                  <strong>{f.percent(s.remaining_share)}</strong>
                  <p>
                    {f.money(s.after)} / {f.money(s.before)}
                  </p>
                  <span>
                    {t("random")}: {f.percent(s.random_share)}
                  </span>
                </div>
                <section className="panel">
                  <h2>
                    {t("before")} → {t("after")}
                  </h2>
                  <ResponsiveContainer width="100%" height={260}>
                    <Sankey
                      data={{
                        nodes: [
                          { name: t("before") },
                          { name: t("remaining") },
                          { name: t("blocking") },
                        ],
                        links: s.sankey.links,
                      }}
                      nodePadding={55}
                      nodeWidth={18}
                      link={{ stroke: "#64afaa" }}
                      margin={{ left: 10, right: 10, top: 20, bottom: 20 }}
                    >
                      <Tooltip />
                    </Sankey>
                  </ResponsiveContainer>
                  <div className="sankey-labels">
                    <span>
                      {t("before")}: {f.money(s.before)}
                    </span>
                    <span>
                      {t("remaining")}: {f.money(s.after)}
                    </span>
                    <span>
                      {t("blocking")}: {f.money(s.before - s.after)}
                    </span>
                  </div>
                </section>
                {s.destinations && (
                  <section className="panel">
                    <h2>{t("destinationFlows")}</h2>
                    <p className="muted">{t("destinationNote")}</p>
                    <div className="destination-grid">
                      {(["before", "after"] as const).map((key) => {
                        const d = s.destinations![key];
                        return (
                          <div key={key}>
                            <h3>
                              {t(key)} · {f.money(d.total)}
                            </h3>
                            {d.links.length ? (
                              <ResponsiveContainer width="100%" height={230}>
                                <Sankey
                                  data={d}
                                  nodePadding={12}
                                  nodeWidth={12}
                                  link={{ stroke: "#0072b2" }}
                                  margin={{
                                    left: 5,
                                    right: 5,
                                    top: 10,
                                    bottom: 10,
                                  }}
                                >
                                  <Tooltip />
                                </Sankey>
                              </ResponsiveContainer>
                            ) : (
                              <Empty />
                            )}
                            <p className="muted">
                              {d.nodes
                                .filter((n) => n.kind === "source")
                                .map((n) => n.name)
                                .join(", ")}{" "}
                              →{" "}
                              {d.nodes
                                .filter((n) => n.kind === "recipient")
                                .map((n) => n.name)
                                .join(", ")}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  </section>
                )}
                <section className="panel">
                  <div className="section-title">
                    <h2>{t("fragments")}</h2>
                    <strong>
                      {s.components_before} → {s.components_after}
                    </strong>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th>{t("clusters")}</th>
                        <th>{t("nodes")}</th>
                        <th>{t("fragments")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.clusters.map((c) => (
                        <tr key={c.cluster_id}>
                          <td>#{c.cluster_id}</td>
                          <td>{c.remaining_nodes}</td>
                          <td>{c.fragments}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <button
                    className="primary"
                    onClick={() => {
                      save(pid, s);
                      setToast(t("scenarioSaved"));
                      setTimeout(() => setToast(""), 3000);
                    }}
                  >
                    <Save size={16} />
                    {t("saveScenario")}
                  </button>
                </section>
              </>
            )
          )}
        </div>
      </div>
      <Toast message={toast} />
    </div>
  );
}

type Preview = {
  counts: Record<string, number>;
  before: Record<string, number>;
  changed_count: number;
  changed: { gid: string; before: string; after: string }[];
  config: Config;
};
export function RuleSettings() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const cache = useQueryClient();
  const project = useQuery({
    queryKey: ["project", pid],
    queryFn: () => api<Project>(root(pid)),
  });
  const [config, setConfig] = useState<Config | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState("");
  const [toast, setToast] = useState("");
  useEffect(() => {
    if (project.data?.config && !config) setConfig(project.data.config);
  }, [project.data, config]);
  const calibration = useQuery({
    queryKey: ["calibration", pid],
    queryFn: () =>
      api<{
        feedback_count: number;
        current_matches: number;
        suggestions: {
          parameter: string;
          before: number;
          after: number;
          matches: number;
          total: number;
        }[];
      }>(root(pid) + "/calibration"),
  });
  const body = config
    ? {
        roles: config.roles,
        priority_weights: config.priority_weights,
        threshold_mode: config.threshold_mode,
      }
    : {};
  useEffect(() => {
    if (!config) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setBusy(true);
      api<Preview>(root(pid) + "/config/preview", {
        method: "POST",
        body: JSON.stringify(body),
        signal: controller.signal,
      })
        .then(setPreview)
        .catch((e) => {
          if (!(e instanceof DOMException && e.name === "AbortError"))
            setError(e);
        })
        .finally(() => setBusy(false));
    }, 600);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [config, pid]);
  const done = useCallback(() => {
    setJob("");
    void cache.invalidateQueries();
    setToast(t("complete"));
  }, [cache, t]);
  async function apply() {
    try {
      const r = await put<{ job_id: string }>(root(pid) + "/config", body);
      setJob(r.job_id);
    } catch (e) {
      setError(e);
    }
  }
  if (!config) return <Loading />;
  const total = Object.values(config.priority_weights).reduce(
    (a, b) => a + b,
    0,
  );
  return (
    <div className="page">
      <div className="page-heading">
        <h1>{t("settings")}</h1>
        <div className="actions">
          <button
            onClick={() => {
              if (project.data) setConfig(project.data.config);
            }}
          >
            {t("reset")}
          </button>
          <button
            onClick={() => {
              localStorage.setItem("rules-preset", JSON.stringify(config));
              setToast(t("preset"));
            }}
          >
            {t("preset")}
          </button>
          <button
            onClick={() => {
              const saved = localStorage.getItem("rules-preset");
              if (saved) setConfig(JSON.parse(saved) as Config);
            }}
          >
            {t("loadPreset")}
          </button>
        </div>
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {job ? <JobProgress id={job} onDone={done} /> : null}
      <div className="settings-grid">
        <div>
          <section className="panel">
            <h2>{t("roles")}</h2>
            <select
              aria-label={t("settings")}
              value={config.threshold_mode}
              onChange={(e) =>
                setConfig({
                  ...config,
                  threshold_mode: e.target.value as Config["threshold_mode"],
                })
              }
            >
              <option value="absolute">{t("absolute")}</option>
              <option value="adaptive">{t("adaptive")}</option>
            </select>
            <div className="rule-settings">
              {Object.entries(config.roles).map(([key, value]) => (
                <label key={key}>
                  <span>{t(key)}</span>
                  <div>
                    <input
                      type="range"
                      min={0}
                      max={
                        key.includes("pct") ||
                        key.includes("share") ||
                        key.includes("_p")
                          ? 1
                          : key.includes("kzt")
                            ? 1000000
                            : Math.max(20, value * 2)
                      }
                      step={
                        key.includes("deg")
                          ? 1
                          : key.includes("kzt")
                            ? 1000
                            : 0.05
                      }
                      value={value}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          roles: {
                            ...config.roles,
                            [key]: Number(e.target.value),
                          },
                        })
                      }
                    />
                    <input
                      type="number"
                      aria-label={key}
                      min={0}
                      step="any"
                      value={value}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          roles: {
                            ...config.roles,
                            [key]: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                </label>
              ))}
            </div>
          </section>
          <section className="panel">
            <h2>{t("weights")}</h2>
            {Object.entries(config.priority_weights).map(([key, value]) => (
              <label className="weight-row" key={key}>
                <span>{t(key)}</span>
                <input
                  aria-label={key}
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={value}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      priority_weights: {
                        ...config.priority_weights,
                        [key]: Number(e.target.value),
                      },
                    })
                  }
                />
                <strong>{total ? (value / total).toFixed(2) : "0"}</strong>
              </label>
            ))}
          </section>
        </div>
        <aside aria-label={t("preview")} className="panel preview-panel">
          <details className="calibration">
            <summary>{t("calibration")}</summary>
            <p>
              {t("feedback")}: {calibration.data?.feedback_count || 0}
            </p>
            {calibration.data?.suggestions.map((s, i) => (
              <div key={i}>
                <p>
                  {t(s.parameter)}: {s.before} → {s.after} · {s.matches}/
                  {s.total}
                </p>
                <button
                  onClick={() =>
                    setConfig({
                      ...config,
                      roles: { ...config.roles, [s.parameter]: s.after },
                    })
                  }
                >
                  {t("preview")}
                </button>
              </div>
            ))}
          </details>
          <h2>{t("preview")}</h2>
          {busy && <span className="status running">{t("processing")}</span>}
          {preview && (
            <>
              <strong className="change-count">
                {t("changed", { count: preview.changed_count })}
              </strong>
              {Object.entries(preview.counts).map(([role, count]) => (
                <div className="preview-count" key={role}>
                  <span>{t(role)}</span>
                  <strong>
                    {count}{" "}
                    <small>
                      ({count - (preview.before[role] || 0) >= 0 ? "+" : ""}
                      {count - (preview.before[role] || 0)})
                    </small>
                  </strong>
                </div>
              ))}
              <div className="changed-nodes">
                {preview.changed.slice(0, 100).map((n) => (
                  <Link
                    key={n.gid}
                    to={
                      "/projects/" +
                      pid +
                      "/investigate?node=" +
                      encodeURIComponent(n.gid)
                    }
                  >
                    <code>{n.gid}</code>
                    <small>
                      {t(n.before)} → {t(n.after)}
                    </small>
                  </Link>
                ))}
              </div>
            </>
          )}
          <button
            className="primary"
            disabled={busy || !!job || total <= 0}
            onClick={() => void apply()}
          >
            {t("apply")}
          </button>
        </aside>
      </div>
      <Toast message={toast} />
    </div>
  );
}

export function Cases() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const cache = useQueryClient();
  const selection = useWorkspace((s) => s.selections[pid] || emptySelection);
  const remove = useWorkspace((s) => s.remove);
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<unknown>();
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const query = useQuery({
    queryKey: ["cases", pid],
    queryFn: () => api<CaseFile[]>(root(pid) + "/cases"),
  });
  async function save() {
    setBusy(true);
    try {
      await post<CaseFile>(root(pid) + "/cases", {
        name,
        ids: selection.caseIds,
        notes,
        scenarios: selection.scenarios,
      });
      await cache.invalidateQueries({ queryKey: ["cases", pid] });
      setToast(t("caseSaved"));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page">
      <div className="page-heading">
        <h1>{t("cases")}</h1>
        <FileText className="accent" size={28} />
      </div>
      {error ? <ErrorBox error={error} /> : null}
      <div className="case-grid">
        <section className="panel">
          <h2>
            {t("selection")} · {selection.caseIds.length}
          </h2>
          <div className="selected-list">
            {selection.caseIds.map((id) => (
              <div key={id}>
                <Link
                  className="mono"
                  to={
                    "/projects/" +
                    pid +
                    "/investigate?node=" +
                    encodeURIComponent(id)
                  }
                >
                  {id}
                </Link>
                <button
                  className="icon-button"
                  aria-label={t("close") + " " + id}
                  onClick={() => remove(pid, "caseIds", id)}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
          {!selection.caseIds.length && <Empty>{t("noSelection")}</Empty>}
          <label>
            {t("name")}
            <input
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            {t("notes")}
            <textarea
              value={notes}
              rows={7}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          <p>
            {t("simulate")}: {selection.scenarios.length}
          </p>
          <button
            className="primary"
            disabled={
              !name.trim() ||
              busy ||
              (!selection.caseIds.length && !selection.scenarios.length)
            }
            onClick={() => void save()}
          >
            <Save size={16} />
            {t("save")}
          </button>
        </section>
        <section className="panel">
          <h2>{t("savedCases")}</h2>
          {query.isPending ? (
            <Loading />
          ) : query.data?.length ? (
            query.data.map((c) => (
              <article className="saved-case" key={c.id}>
                <FileText size={24} />
                <div>
                  <h3>{c.name}</h3>
                  <p>
                    {c.ids.length} {t("nodes").toLowerCase()} ·{" "}
                    {c.scenarios.length} {t("simulate").toLowerCase()}
                  </p>
                  <a
                    className="text-button"
                    target="_blank"
                    rel="noreferrer"
                    href={"/api" + root(pid) + "/cases/" + c.id + "/report"}
                  >
                    {t("report")}
                    <ArrowUpRight size={16} />
                  </a>
                </div>
              </article>
            ))
          ) : (
            <Empty />
          )}
          <a
            className="button"
            href={"/api" + root(pid) + "/export/requests.csv"}
          >
            <Download size={16} />
            requests.csv
          </a>
        </section>
      </div>
      <Toast message={toast} />
    </div>
  );
}
