import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ResponsiveContainer, AreaChart, Area, Brush, XAxis } from "recharts";
import { useTranslation } from "react-i18next";
import {
  EyeOff,
  FolderPlus,
  Pin,
  Play,
  Plus,
  ShieldOff,
  Square,
} from "lucide-react";
import { api, post, root, nodePath } from "./api";
import type { GraphData, NodeRow, Summary, Role, Cluster } from "./types";
import { GraphCanvas } from "./GraphCanvas";
import { Inspector } from "./Inspector";
import {
  Loading,
  ErrorBox,
  RoleBadge,
  roleColors,
  useFormat,
  Modal,
} from "./components";
import { useWorkspace } from "./store";
export function Investigation() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const id = params.get("node") || "";
  const focus = params.get("focus") || id;
  const cid = params.get("cluster") || "";
  const hops = Number(params.get("hops") || 1);
  const limit = Number(params.get("limit") || 150);
  const [hidden, setHidden] = useState<string[]>([]);
  const [pinned, setPinned] = useState<string[]>(
    () => JSON.parse(localStorage.getItem("pins-" + pid) || "[]") as string[],
  );
  const [destination, setDestination] = useState("");
  const [pathError, setPathError] = useState<unknown>();
  const [paths, setPaths] = useState<
    { nodes: string[]; strength: number; bottleneck_amount: number }[]
  >([]);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [playing, setPlaying] = useState(false);
  const [pathBusy, setPathBusy] = useState(false);
  const [pathGraph, setPathGraph] = useState<GraphData | null>(null);
  const [edge, setEdge] = useState<{ src: string; dst: string } | null>(null);
  const tx = useQuery({
    queryKey: ["edge", pid, edge],
    queryFn: () =>
      api<{
        total: number;
        items: {
          src: string;
          dst: string;
          amount: number;
          date: string | null;
        }[];
      }>(
        root(pid) +
          "/transactions?src=" +
          encodeURIComponent(edge!.src) +
          "&dst=" +
          encodeURIComponent(edge!.dst),
      ),
    enabled: !!edge,
  });
  const add = useWorkspace((s) => s.add);
  const summary = useQuery({
    queryKey: ["summary", pid],
    queryFn: () => api<Summary>(root(pid) + "/summary"),
  });
  const f = useFormat(summary.data?.currency);
  const dates = useQuery({
    queryKey: ["project-timeline", pid],
    queryFn: () =>
      api<{ day: string; amount: number }[]>(root(pid) + "/timeline"),
    enabled: !!summary.data?.profile.has_dates,
  });
  const clusterList = useQuery({
    queryKey: ["clusters", pid],
    queryFn: () => api<Cluster[]>(root(pid) + "/clusters"),
  });
  const role = params.get("role") || "";
  const q = params.get("q") || "";
  const minimum = params.get("min_priority") || "0";
  const list = useQuery({
    queryKey: ["investigate-list", pid, role, q, minimum],
    queryFn: () =>
      api<{ items: NodeRow[]; total: number }>(
        root(pid) +
          "/nodes?limit=30&q=" +
          encodeURIComponent(q) +
          "&role=" +
          role +
          "&min_priority=" +
          minimum,
      ),
  });
  function patch(values: Record<string, string>) {
    setParams((prev) => {
      const n = new URLSearchParams(prev);
      Object.entries(values).forEach(([k, v]) =>
        v ? n.set(k, v) : n.delete(k),
      );
      return n;
    });
  }
  function select(next: string) {
    patch({ node: next, focus: focus || next });
  }
  function focusNode(next: string) {
    setPathGraph(null);
    setHidden([]);
    patch({ node: next, focus: next, cluster: "", network: "", selection: "" });
  }
  const endpoint = params.get("network")
    ? "/network-graph?limit=" + limit
    : cid
      ? "/clusters/" + cid + "/graph?limit=" + limit
      : focus
        ? nodePath(focus) +
          "/ego?hops=" +
          hops +
          "&limit=" +
          limit +
          (params.get("start") ? "&start=" + params.get("start") : "") +
          (params.get("end") ? "&end=" + params.get("end") : "")
        : "/overview-graph";
  const selectionParam = params.get("selection") || "";
  let assistantSelection: string[] = [];
  try {
    const values: unknown = JSON.parse(selectionParam);
    if (Array.isArray(values))
      assistantSelection = values
        .filter((v): v is string => typeof v === "string")
        .slice(0, 3000);
  } catch {}
  const graph = useQuery({
    queryKey: ["graph", pid, endpoint, selectionParam],
    queryFn: () =>
      assistantSelection.length
        ? post<GraphData>(root(pid) + "/graph", { ids: assistantSelection })
        : api<GraphData>(root(pid) + endpoint),
  });
  const filtered = useMemo(() => {
    const data = pathGraph || graph.data;
    if (!data || data.overview) return data;
    const roles = role.split(",").filter(Boolean);
    const keep = data.nodes.filter(
      (n) =>
        n.gid === id ||
        ((!roles.length || roles.includes(n.role)) &&
          n.priority_score >= Number(minimum) &&
          (!params.get("seed_path") || n.is_seed || n.seed_sources > 0) &&
          (!params.get("depth") || n.depth === Number(params.get("depth"))) &&
          n.turnover >= Number(params.get("amount") || 0)),
    );
    const ids = new Set(keep.map((n) => n.gid));
    return {
      ...data,
      nodes: keep,
      edges: data.edges.filter((e) => ids.has(e.src) && ids.has(e.dst)),
    };
  }, [graph.data, pathGraph, role, minimum, id, params]);
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (
        (e.target as HTMLElement).matches("input,textarea,select") ||
        e.ctrlKey ||
        e.metaKey
      )
        return;
      if (e.key.toLowerCase() === "e" && id)
        patch({ focus: id, hops: String(Math.min(3, hops + 1)), cluster: "" });
      if (e.key.toLowerCase() === "b" && id) add(pid, "block", [id]);
      if (e.key.toLowerCase() === "a" && id) add(pid, "caseIds", [id]);
      if (e.key === "Escape") patch({ node: "" });
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [id, hops, pid, params]);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const current = params.get("end") || summary.data?.profile.period_start;
      const last = summary.data?.profile.period_end;
      if (!current || !last) {
        setPlaying(false);
        return;
      }
      const next = new Date(current);
      next.setDate(next.getDate() + 1);
      const end = next.toISOString().slice(0, 10);
      if (end > last) {
        setPlaying(false);
        return;
      }
      patch({ end });
    }, 1200);
    return () => clearInterval(timer);
  }, [playing, params, summary.data]);
  async function find() {
    setPathBusy(true);
    setPathError(undefined);
    try {
      const r = await api<{
        paths: {
          nodes: string[];
          strength: number;
          bottleneck_amount: number;
        }[];
      }>(
        root(pid) +
          "/paths?from=" +
          encodeURIComponent(id) +
          "&to=" +
          encodeURIComponent(destination),
      );
      setPaths(r.paths);
      setHighlight(r.paths[0]?.nodes || []);
      if (r.paths.length)
        setPathGraph(
          await post<GraphData>(root(pid) + "/graph", {
            ids: [...new Set(r.paths.flatMap((p) => p.nodes))],
          }),
        );
    } catch (e) {
      setPathError(e);
    } finally {
      setPathBusy(false);
    }
  }
  return (
    <div className="investigation-page">
      <div className="investigation-top">
        <div>
          <h1>{t("investigate")}</h1>
          <span className="muted">{summary.data?.profile.period_label}</span>
        </div>
        <div className="actions">
          <button
            onClick={() => {
              setPathGraph(null);
              patch({ network: "1", cluster: "", limit: "3000" });
            }}
          >
            ≤ 3 000
          </button>
          {id && (
            <>
              <button
                onClick={() =>
                  patch({
                    focus: id,
                    hops: String(Math.min(3, hops + 1)),
                    cluster: "",
                  })
                }
              >
                <Plus size={15} />
                {t("expand")}
              </button>
              <button
                aria-label={t("hide")}
                onClick={() => setHidden((h) => [...h, id])}
              >
                <EyeOff size={16} />
              </button>
              <button
                aria-label={t("pin")}
                aria-pressed={pinned.includes(id)}
                onClick={() => {
                  const pins = pinned.includes(id)
                    ? pinned.filter((x) => x !== id)
                    : [...pinned, id];
                  setPinned(pins);
                  localStorage.setItem("pins-" + pid, JSON.stringify(pins));
                }}
              >
                <Pin size={16} />
              </button>
              <button
                aria-label={t("toBlock")}
                onClick={() => add(pid, "block", [id])}
              >
                <ShieldOff size={16} />
              </button>
              <button
                aria-label={t("toCase")}
                onClick={() => add(pid, "caseIds", [id])}
              >
                <FolderPlus size={16} />
              </button>
            </>
          )}
          <select
            aria-label="Graph limit"
            value={limit}
            onChange={(e) => patch({ limit: e.target.value })}
          >
            {[50, 150, 500, 1000, 3000].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
          {hidden.length > 0 && (
            <button onClick={() => setHidden([])}>↶ {hidden.length}</button>
          )}
        </div>
      </div>
      <div className="investigation-grid">
        <aside aria-label={t("filter")} className="filters panel">
          <h2>{t("filter")}</h2>
          <input
            aria-label={t("search")}
            placeholder={t("search")}
            value={q}
            onChange={(e) => patch({ q: e.target.value })}
          />
          <div className="filter-roles">
            {Object.keys(roleColors).map((r) => (
              <label key={r} className="checkbox">
                <input
                  type="checkbox"
                  checked={role.split(",").includes(r)}
                  onChange={(e) => {
                    const set = new Set(role.split(",").filter(Boolean));
                    e.target.checked ? set.add(r) : set.delete(r);
                    patch({ role: [...set].join(",") });
                  }}
                />
                <RoleBadge role={r as Role} />
                <small>{summary.data?.roles[r as Role] || 0}</small>
              </label>
            ))}
          </div>
          <label>
            {t("clusters")}
            <select
              value={cid}
              onChange={(e) =>
                patch({ cluster: e.target.value, focus: "", node: "" })
              }
            >
              <option value="">{t("all")}</option>
              {clusterList.data?.map((c) => (
                <option key={c.cluster_id} value={c.cluster_id}>
                  #{c.cluster_id} · {c.n_nodes}
                </option>
              ))}
            </select>
          </label>
          <div className="form-grid">
            <label>
              {t("depth")}
              <input
                type="number"
                min={0}
                value={params.get("depth") || ""}
                onChange={(e) => patch({ depth: e.target.value })}
              />
            </label>
            <label>
              {t("amount")}
              <input
                type="number"
                min={0}
                value={params.get("amount") || ""}
                onChange={(e) => patch({ amount: e.target.value })}
              />
            </label>
          </div>
          <label>
            {t("priority")} ≥ {minimum}
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minimum}
              onChange={(e) => patch({ min_priority: e.target.value })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={!!params.get("seed_path")}
              onChange={(e) =>
                patch({ seed_path: e.target.checked ? "1" : "" })
              }
            />
            {t("seedPath")}
          </label>
          <div className="candidate-list">
            {list.data?.items.map((n) => (
              <button
                key={n.gid}
                className={id === n.gid ? "selected" : ""}
                onClick={() => focusNode(n.gid)}
              >
                <span className="mono">{n.gid}</span>
                <small>
                  <RoleBadge role={n.role} />
                  <b>{n.priority_score.toFixed(2)}</b>
                </small>
              </button>
            ))}
          </div>
        </aside>
        <div className="graph-column">
          {graph.isPending ? (
            <Loading />
          ) : graph.error ? (
            <ErrorBox error={graph.error} />
          ) : (
            filtered && (
              <GraphCanvas
                data={filtered}
                selected={id}
                hidden={hidden}
                pinned={pinned}
                highlight={highlight}
                storageKey={"layout-" + pid}
                onEdge={(src, dst) => setEdge({ src, dst })}
                onSelect={(next) =>
                  filtered.overview
                    ? patch({ cluster: next, node: "", focus: "" })
                    : select(next)
                }
                onFocus={focusNode}
              />
            )
          )}
          {!!dates.data?.length && focus && (
            <div className="date-brush">
              <ResponsiveContainer width="100%" height={90}>
                <AreaChart data={dates.data}>
                  <XAxis dataKey="day" hide />
                  <Area
                    dataKey="amount"
                    stroke="#087c78"
                    fill="#d3e9e4"
                    isAnimationActive={false}
                  />
                  <Brush
                    dataKey="day"
                    height={22}
                    stroke="#567487"
                    startIndex={Math.max(
                      0,
                      dates.data.findIndex(
                        (d) =>
                          d.day ===
                          (params.get("start") || dates.data?.[0].day),
                      ),
                    )}
                    endIndex={Math.max(
                      0,
                      dates.data.findIndex(
                        (d) =>
                          d.day ===
                          (params.get("end") ||
                            dates.data?.[dates.data.length - 1].day),
                      ),
                    )}
                    onChange={(range) => {
                      if (
                        range.startIndex !== undefined &&
                        range.endIndex !== undefined &&
                        dates.data
                      )
                        patch({
                          start: dates.data[range.startIndex].day,
                          end: dates.data[range.endIndex].day,
                        });
                    }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="timeline-bar">
            {summary.data?.profile.has_dates ? (
              <>
                <label>
                  {t("dateFrom")}
                  <input
                    type="date"
                    value={
                      params.get("start") ||
                      summary.data.profile.period_start ||
                      ""
                    }
                    onChange={(e) => patch({ start: e.target.value })}
                  />
                </label>
                <label>
                  {t("dateTo")}
                  <input
                    type="date"
                    value={
                      params.get("end") || summary.data.profile.period_end || ""
                    }
                    onChange={(e) => patch({ end: e.target.value })}
                  />
                </label>
                <button
                  disabled={!focus}
                  onClick={() => {
                    if (!playing)
                      patch({ end: summary.data?.profile.period_start || "" });
                    setPlaying(!playing);
                  }}
                >
                  {playing ? <Square size={15} /> : <Play size={15} />}{" "}
                  {t(playing ? "stop" : "play")}
                </button>
              </>
            ) : (
              <span className="muted">
                {
                  summary.data?.capabilities.find((c) => c.key === "temporal")
                    ?.message
                }
              </span>
            )}
          </div>
          {id && (
            <section className="panel paths-panel">
              <h3>{t("paths")}</h3>
              <div className="actions">
                <code>{id}</code>
                <span>→</span>
                <input
                  aria-label={t("to")}
                  placeholder={t("to")}
                  value={destination}
                  onChange={(e) => setDestination(e.target.value)}
                />
                <button
                  disabled={!destination || pathBusy}
                  onClick={() => void find()}
                >
                  {t("findPath")}
                </button>
              </div>
              {pathError ? <ErrorBox error={pathError} /> : null}
              {paths.map((p, i) => (
                <button
                  key={i}
                  className="path-result"
                  onClick={() => setHighlight(p.nodes)}
                >
                  <span className="mono">{p.nodes.join(" → ")}</span>
                  <strong>{f.money(p.bottleneck_amount)}</strong>
                </button>
              ))}
            </section>
          )}
        </div>
        {id ? (
          <Inspector
            key={id}
            pid={pid}
            id={id}
            currency={summary.data?.currency}
            onSelect={focusNode}
            onClose={() => patch({ node: "", focus: focus })}
          />
        ) : (
          <aside aria-label={t("selection")} className="panel inspector">
            <div className="empty">
              <NetworkHint />
              <h3>{t("selection")}</h3>
              <p>{t("noSelection")}</p>
              <p className="muted">{t("hypothesis")}</p>
            </div>
          </aside>
        )}
      </div>
      <Modal
        open={!!edge}
        onClose={() => setEdge(null)}
        title={t("transactions")}
      >
        <p className="mono">
          {edge?.src} → {edge?.dst}
        </p>
        {tx.isPending ? (
          <Loading />
        ) : tx.error ? (
          <ErrorBox error={tx.error} />
        ) : (
          <>
            <p>{tx.data?.total}</p>
            <table>
              <thead>
                <tr>
                  <th>{t("timeline")}</th>
                  <th>{t("turnover")}</th>
                </tr>
              </thead>
              <tbody>
                {tx.data?.items.map((r, i) => (
                  <tr key={i}>
                    <td>{r.date ? f.date(r.date) : "—"}</td>
                    <td>{f.money(r.amount, false)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Modal>
    </div>
  );
}
function NetworkHint() {
  return (
    <svg width="80" height="70" viewBox="0 0 80 70" aria-hidden>
      <path
        d="M15 20 40 35 65 15M40 35 55 60M40 35 12 55"
        stroke="#9aafb9"
        fill="none"
      />
      <circle cx="40" cy="35" r="10" fill="#087f80" />
      {[
        [15, 20],
        [65, 15],
        [55, 60],
        [12, 55],
      ].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="5" fill="#c6d7dd" />
      ))}
    </svg>
  );
}
