import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ResponsiveContainer, AreaChart, Area, XAxis, Tooltip } from "recharts";
import { Check, CheckCheck, FolderPlus, ShieldOff, X } from "lucide-react";
import { api, post, root, nodePath } from "./api";
import type { NodeRow, Trace, Check as RuleCheck } from "./types";
import { useWorkspace } from "./store";
import { Loading, ErrorBox, RoleBadge, useFormat, Toast } from "./components";
function Checks({ check }: { check: RuleCheck }) {
  const { t } = useTranslation();
  return check.checks ? (
    <div className="checks-group">
      <span className="logical">{check.mode === "all" ? "AND" : "OR"}</span>
      {check.checks.map((c, i) => (
        <Checks check={c} key={i} />
      ))}
    </div>
  ) : (
    <div className={"rule-check " + (check.ok ? "passed" : "")}>
      <span>{check.ok ? "✓" : "✗"}</span>
      <div>
        <code>{t(check.metric || "")}</code>
        <small>
          {typeof check.value === "number"
            ? Number(check.value.toPrecision(5))
            : String(check.value ?? "—")}{" "}
          {check.op}{" "}
          {typeof check.threshold === "number"
            ? Number(check.threshold.toPrecision(5))
            : String(check.threshold)}
        </small>
        {typeof check.value === "number" &&
          typeof check.threshold === "number" &&
          check.threshold > 0 && (
            <span className="check-bar">
              <i
                style={{
                  width:
                    Math.min(
                      100,
                      Math.max(0, (check.value / check.threshold) * 100),
                    ) + "%",
                }}
              />
            </span>
          )}
      </div>
    </div>
  );
}
export function Inspector({
  pid,
  id,
  onSelect,
  onClose,
  currency,
}: {
  pid: string;
  id: string;
  onSelect: (id: string) => void;
  onClose: () => void;
  currency?: string;
}) {
  const { t } = useTranslation();
  const f = useFormat(currency);
  const [toast, setToast] = useState("");
  const [error, setError] = useState<unknown>();
  const [tab, setTab] = useState("evidence");
  const add = useWorkspace((s) => s.add);
  const node = useQuery({
    queryKey: ["node", pid, id],
    queryFn: () => api<NodeRow>(root(pid) + nodePath(id)),
  });
  const trace = useQuery({
    queryKey: ["explain", pid, id],
    queryFn: () => api<Trace>(root(pid) + nodePath(id) + "/explain"),
  });
  const timeline = useQuery({
    queryKey: ["timeline", pid, id],
    queryFn: () =>
      api<{ day: string; incoming: number; outgoing: number }[]>(
        root(pid) + nodePath(id) + "/timeline",
      ),
  });
  const n = node.data;
  async function feedback(verdict: string) {
    try {
      await post(root(pid) + "/feedback", { id, verdict, comment: "" });
      setToast(t("feedbackSaved"));
      setTimeout(() => setToast(""), 2500);
    } catch (e) {
      setError(e);
    }
  }
  return (
    <aside aria-label={t("selection")} className="inspector panel">
      <div className="inspector-heading">
        <span className="eyebrow">{t("selection")}</span>
        <button
          className="icon-button"
          aria-label={t("close")}
          onClick={onClose}
        >
          <X size={17} />
        </button>
      </div>
      {node.isPending ? (
        <Loading />
      ) : node.error ? (
        <ErrorBox error={node.error} />
      ) : (
        n && (
          <>
            <h2 className="node-id">{n.gid}</h2>
            <div className="flex justify-between items-center">
              <RoleBadge role={n.role} />
              <strong className="priority-score">
                {n.priority_score.toFixed(2)}
              </strong>
            </div>
            <div className="node-actions">
              <button
                title={t("toBlock")}
                onClick={() => add(pid, "block", [id])}
              >
                <ShieldOff size={16} />
                {t("toBlock")}
              </button>
              <button onClick={() => add(pid, "caseIds", [id])}>
                <FolderPlus size={16} />
                {t("toCase")}
              </button>
            </div>
            <div
              className="inspector-tabs"
              onKeyDown={(e) => {
                const names = ["evidence", "why", "metrics"];
                const idx = names.indexOf(tab);
                const next =
                  e.key === "ArrowRight"
                    ? (idx + 1) % 3
                    : e.key === "ArrowLeft"
                      ? (idx + 2) % 3
                      : e.key === "Home"
                        ? 0
                        : e.key === "End"
                          ? 2
                          : -1;
                if (next >= 0) {
                  e.preventDefault();
                  setTab(names[next]);
                  document.getElementById("tab-" + names[next])?.focus();
                }
              }}
              role="tablist"
              aria-label={t("metrics")}
            >
              {["evidence", "why", "metrics"].map((x) => (
                <button
                  role="tab"
                  tabIndex={tab === x ? 0 : -1}
                  id={"tab-" + x}
                  aria-controls={"panel-" + x}
                  aria-selected={tab === x}
                  key={x}
                  onClick={() => setTab(x)}
                >
                  {t(x)}
                </button>
              ))}
            </div>
            <div
              role="tabpanel"
              id={"panel-" + tab}
              aria-labelledby={"tab-" + tab}
            >
              {tab === "evidence" && (
                <>
                  <p className="evidence">{n.evidence}</p>
                  <div className="metric-pairs">
                    <div>
                      <span>{t("incoming")}</span>
                      <strong>{f.money(n.in_kzt)}</strong>
                      <small>{n.in_deg} ↗</small>
                    </div>
                    <div>
                      <span>{t("outgoing")}</span>
                      <strong>{f.money(n.out_kzt)}</strong>
                      <small>{n.out_deg} ↘</small>
                    </div>
                    <div>
                      <span>{t("traced")}</span>
                      <strong>{f.money(n.tainted_in_kzt)}</strong>
                    </div>
                    <div>
                      <span>{t("blocking")}</span>
                      <strong>{f.percent(n.block_impact)}</strong>
                    </div>
                  </div>
                  <button className="text-button" onClick={() => setTab("why")}>
                    {t("why")} →
                  </button>
                  {!!timeline.data?.length && (
                    <>
                      <h3>{t("timeline")}</h3>
                      <ResponsiveContainer width="100%" height={145}>
                        <AreaChart data={timeline.data}>
                          <XAxis dataKey="day" hide />
                          <Tooltip formatter={(v) => f.money(Number(v))} />
                          <Area
                            dataKey="incoming"
                            stroke="#0072b2"
                            fill="#0072b2"
                            fillOpacity={0.12}
                            name={t("incoming")}
                            isAnimationActive={false}
                          />
                          <Area
                            dataKey="outgoing"
                            stroke="#d55e00"
                            fill="#d55e00"
                            fillOpacity={0.08}
                            name={t("outgoing")}
                            isAnimationActive={false}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </>
                  )}
                  <h3>{t("counterparties")}</h3>
                  <div className="counterparties">
                    {n.counterparties?.map((e) => {
                      const other = e.src === id ? e.dst : e.src;
                      return (
                        <button
                          key={e.src + "-" + e.dst}
                          onClick={() => onSelect(other)}
                        >
                          <span className="mono">
                            {e.src === id ? "↗" : "↙"} {other}
                          </span>
                          <strong>{f.money(e.amount)}</strong>
                        </button>
                      );
                    })}
                  </div>
                </>
              )}
              {tab === "why" && (
                <>
                  <p className="muted">{t("matched")}</p>
                  {trace.isPending ? (
                    <Loading />
                  ) : trace.error ? (
                    <ErrorBox error={trace.error} />
                  ) : (
                    trace.data?.trace.map((r) => (
                      <details
                        className={"trace-rule " + (r.matched ? "matched" : "")}
                        key={r.rule}
                        open={r.matched}
                      >
                        <summary>
                          <span>{r.passed ? "✓" : "✗"}</span>
                          {t(r.role)}
                          {r.matched && <CheckCheck size={16} />}
                        </summary>
                        <Checks check={r.checks} />
                      </details>
                    ))
                  )}
                </>
              )}
              {tab === "metrics" && (
                <dl className="all-metrics">
                  {(
                    [
                      "role_score",
                      "depth",
                      "is_seed",
                      "in_deg",
                      "out_deg",
                      "pass_through",
                      "betweenness",
                      "taint_share",
                      "seed_sources",
                      "p_onward",
                    ] as const
                  ).map((key) => (
                    <div key={key}>
                      <dt title={t("glossary")}>{t(key)}</dt>
                      <dd>
                        {typeof n[key] === "boolean"
                          ? String(n[key])
                          : typeof n[key] === "number"
                            ? f.num(n[key] as number)
                            : "—"}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
            <Link
              className="button"
              to={
                "/projects/" + pid + "/assistant?node=" + encodeURIComponent(id)
              }
            >
              {t("assistant")}
            </Link>
            <div className="feedback">
              <h3>{t("feedback")}</h3>
              <div className="actions">
                <button
                  title={t("confirm")}
                  onClick={() => void feedback("confirm")}
                >
                  <Check size={15} />
                  {t("confirm")}
                </button>
                <button
                  title={t("reject")}
                  onClick={() => void feedback("reject")}
                >
                  <X size={15} />
                  {t("reject")}
                </button>
                <button onClick={() => void feedback("unsure")}>?</button>
              </div>
            </div>
          </>
        )
      )}
      {error ? <ErrorBox error={error} /> : null}
      <Toast message={toast} />
    </aside>
  );
}
