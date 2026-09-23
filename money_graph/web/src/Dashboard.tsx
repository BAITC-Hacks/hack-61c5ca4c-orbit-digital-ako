import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowUpRight,
  Network,
  ShieldCheck,
  Timer,
  Wallet,
} from "lucide-react";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { api, root } from "./api";
import type { Summary, NodeRow, Role } from "./types";
import {
  Loading,
  ErrorBox,
  RoleBadge,
  roleColors,
  useFormat,
} from "./components";
export function Dashboard() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const summary = useQuery({
    queryKey: ["summary", pid],
    queryFn: () => api<Summary>(root(pid) + "/summary"),
  });
  const top = useQuery({
    queryKey: ["top", pid],
    queryFn: () => api<{ items: NodeRow[] }>(root(pid) + "/nodes?limit=10"),
  });
  const s = summary.data;
  const f = useFormat(s?.currency);
  if (summary.isPending) return <Loading />;
  if (summary.error) return <ErrorBox error={summary.error} />;
  if (!s) return null;
  const roles = Object.entries(s.roles).map(([name, value]) => ({
    name: t(name),
    value,
    key: name as Role,
  }));
  return (
    <div className="page dashboard">
      <div className="page-heading">
        <div>
          <div className="eyebrow">{s.profile.period_label}</div>
          <h1>{t("overview")}</h1>
        </div>
        <a className="button" href={"/api" + root(pid) + "/export/all.zip"}>
          {t("export")}
          <ArrowUpRight size={16} />
        </a>
      </div>
      <div className="kpi-grid">
        {[
          {
            icon: Network,
            label: "nodes",
            value: f.num(s.nodes),
            detail: `${f.num(s.edges)} ${t("edges").toLowerCase()}`,
          },
          {
            icon: Wallet,
            label: "turnover",
            value: f.money(s.total_amount),
            detail: `${f.num(s.transactions)} ${t("transactions").toLowerCase()}`,
          },
          {
            icon: ShieldCheck,
            label: "traced",
            value: f.money(s.tainted_flow_kzt),
            detail:
              s.tainted_flow_kzt === null
                ? t("unknown")
                : f.percent(s.tainted_flow_kzt / s.total_amount),
          },
          {
            icon: Timer,
            label: "clusters",
            value: f.num(s.clusters),
            detail: `${s.runtime_sec} s`,
          },
        ].map((k) => (
          <div className="kpi" key={k.label}>
            <div>
              <span>{t(k.label)}</span>
              <k.icon size={18} />
            </div>
            <strong>{k.value}</strong>
            <small>{k.detail}</small>
          </div>
        ))}
      </div>
      <section className="insight-panel">
        <div className="insight-icon">
          <Network size={28} />
        </div>
        <div>
          <div className="eyebrow">{t("insight")}</div>
          <h2>
            {t("insightText", {
              n: s.insight.n,
              share: f.percent(s.insight.removed_share),
              clusters: s.insight.multiseed_clusters,
            })}
          </h2>
          <p>{t("hypothesis")}</p>
        </div>
        <Link className="primary button" to={"/projects/" + pid + "/simulate"}>
          {t("simulate")}
          <ArrowUpRight size={17} />
        </Link>
      </section>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="section-title">
            <h2>{t("top")}</h2>
            <Link to={"/projects/" + pid + "/nodes"}>{t("all")} →</Link>
          </div>
          <table className="top-table">
            <thead>
              <tr>
                <th>#</th>
                <th>ID</th>
                <th>{t("roles")}</th>
                <th>{t("priority")}</th>
                <th>
                  <span className="sr-only">{t("open")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {top.data?.items.map((n, i) => (
                <tr key={n.gid}>
                  <td className="muted">{String(i + 1).padStart(2, "0")}</td>
                  <td>
                    <Link
                      className="id-link"
                      to={
                        "/projects/" +
                        pid +
                        "/investigate?node=" +
                        encodeURIComponent(n.gid)
                      }
                    >
                      {n.gid}
                    </Link>
                  </td>
                  <td>
                    <RoleBadge role={n.role} />
                  </td>
                  <td>
                    <div className="priority-bar">
                      <i style={{ width: n.priority_score * 100 + "%" }} />
                      <span>{n.priority_score.toFixed(2)}</span>
                    </div>
                  </td>
                  <td>
                    <Link
                      aria-label={t("open") + " " + n.gid}
                      to={
                        "/projects/" +
                        pid +
                        "/investigate?node=" +
                        encodeURIComponent(n.gid)
                      }
                    >
                      <ArrowUpRight size={16} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="panel">
          <h2>{t("roles")}</h2>
          <div className="donut">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={roles}
                  dataKey="value"
                  innerRadius={67}
                  outerRadius={95}
                  paddingAngle={2}
                  stroke="none"
                >
                  {roles.map((r) => (
                    <Cell fill={roleColors[r.key]} key={r.key} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="donut-center">
              <strong>{f.num(s.nodes)}</strong>
              <span>{t("nodes")}</span>
            </div>
          </div>
          <div className="role-list">
            {roles.map((r) => (
              <div key={r.key}>
                <RoleBadge role={r.key} />
                <strong>{f.num(r.value)}</strong>
              </div>
            ))}
          </div>
        </section>
        <section className="panel resilience-chart">
          <h2>{t("resilience")}</h2>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={s.resilience}>
              <CartesianGrid strokeDasharray="3 4" vertical={false} />
              <XAxis dataKey="n_blocked" />
              <YAxis tickFormatter={(v) => f.percent(v)} />
              <Tooltip formatter={(v) => f.percent(Number(v))} />
              <Legend />
              <Line
                type="monotone"
                dataKey="tainted_flow_left"
                name={t("targeted")}
                stroke="#087f80"
                strokeWidth={3}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="random_flow_left"
                name={t("random")}
                stroke="#758896"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </section>
        <section className="panel">
          <h2>{t("limitations")}</h2>
          <div className="capabilities">
            {s.capabilities.map((c) => (
              <div key={c.key} className={c.enabled ? "" : "limited"}>
                <span>{c.enabled ? "✓" : "!"}</span>
                <p>{c.message}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
