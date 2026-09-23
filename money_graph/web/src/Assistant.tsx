import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Bot, ArrowUpRight, ShieldCheck, Send, X } from "lucide-react";
import { api, post, root } from "./api";
import type { NodeRow, Summary } from "./types";
import { Loading, ErrorBox, Empty, RoleBadge, useFormat } from "./components";
type Answer = {
  answer: string;
  mode: string;
  notice: string | null;
  tools_used: string[];
  limitations: string[];
  evidence: { gid: string; reason: string }[];
  edges: { src: string; dst: string; sum_kzt: number; n_tx: number }[];
};
export function Assistant() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<string[]>(() =>
    params.get("node") ? [params.get("node")!] : [],
  );
  const [search, setSearch] = useState("");
  const [question, setQuestion] = useState("");
  const [consent, setConsent] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const urlNode = params.get("node");
  useEffect(() => {
    setSelected(urlNode ? [urlNode] : []);
  }, [pid, urlNode]);
  const status = useQuery({
    queryKey: ["assistant-status"],
    queryFn: () =>
      api<{ configured: boolean; model: string | null }>("/assistant/status"),
  });
  const results = useQuery({
    queryKey: ["assistant-nodes", pid, search],
    queryFn: () =>
      api<{ items: NodeRow[] }>(
        root(pid) + "/nodes?q=" + encodeURIComponent(search) + "&limit=8",
      ),
  });
  const summary = useQuery({
    queryKey: ["summary", pid],
    queryFn: () => api<Summary>(root(pid) + "/summary"),
  });
  const f = useFormat(summary.data?.currency);
  useEffect(() => {
    generation.current++;
    setBusy(false);
    setAnswer(null);
    setError(undefined);
    setConsent(false);
  }, [selected, pid]);
  async function ask(mode: string) {
    const version = generation.current;
    setBusy(true);
    setError(undefined);
    setAnswer(null);
    try {
      const result = await post<Answer>(root(pid) + "/assistant", {
        gids: selected,
        mode,
        question: mode === "question" ? question : "",
        allow_external: mode === "question" && consent,
      });
      if (generation.current === version) setAnswer(result);
    } catch (e) {
      if (generation.current === version) setError(e);
    } finally {
      if (generation.current === version) {
        setBusy(false);
        setConsent(false);
      }
    }
  }
  const graphIds = answer
    ? [
        ...new Set([
          ...answer.evidence.map((e) => e.gid),
          ...answer.edges.flatMap((e) => [e.src, e.dst]),
        ]),
      ]
    : [];
  return (
    <div className="page assistant-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">{t("hypothesis")}</div>
          <h1>{t("assistant")}</h1>
        </div>
        <Bot className="accent" size={28} />
      </div>
      <div className="assistant-grid">
        <aside className="panel" aria-label={t("selection")}>
          <h2>{t("assistantSelection")}</h2>
          <div className="selected-list">
            {selected.map((id) => (
              <div key={id}>
                <code>{id}</code>
                <button
                  className="icon-button"
                  disabled={busy}
                  aria-label={t("close") + " " + id}
                  onClick={() =>
                    setSelected((ids) => ids.filter((x) => x !== id))
                  }
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
          <input
            aria-label={t("search")}
            placeholder={t("searchHint")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="candidate-list">
            {results.data?.items.map((n) => (
              <button
                key={n.gid}
                disabled={
                  selected.includes(n.gid) || selected.length >= 5 || busy
                }
                onClick={() => setSelected((ids) => [...ids, n.gid])}
              >
                <code>{n.gid}</code>
                <small>
                  <RoleBadge role={n.role} />
                  <b>+</b>
                </small>
              </button>
            ))}
          </div>
        </aside>
        <div>
          <section className="panel">
            <div className="section-title">
              <h2>{t("localAssistant")}</h2>
              <ShieldCheck size={18} className="accent" />
            </div>
            <p className="muted">{t("localAssistantNote")}</p>
            <div className="assistant-actions">
              {["explain", "common_recipients", "paths", "missing_data"].map(
                (mode) => (
                  <button
                    key={mode}
                    disabled={
                      busy ||
                      !selected.length ||
                      (mode === "common_recipients" && selected.length < 2) ||
                      (mode === "paths" && selected.length !== 2)
                    }
                    onClick={() => void ask(mode)}
                  >
                    {t("assistant_" + mode)}
                  </button>
                ),
              )}
            </div>
            {status.data?.configured ? (
              <form
                className="assistant-question"
                onSubmit={(e) => {
                  e.preventDefault();
                  void ask("question");
                }}
              >
                <h3>
                  {t("askAI")} · {status.data.model}
                </h3>
                <label>
                  {t("question")}
                  <textarea
                    value={question}
                    maxLength={1000}
                    rows={3}
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  {t("assistantConsent")}
                </label>
                <button
                  className="primary"
                  disabled={
                    busy || !selected.length || !consent || !question.trim()
                  }
                >
                  <Send size={16} />
                  {t("askAI")}
                </button>
              </form>
            ) : (
              <div className="notice">{t("assistantSetup")}</div>
            )}
          </section>
          {busy && <Loading />}
          {error ? <ErrorBox error={error} /> : null}
          {answer ? (
            <section className="panel assistant-answer">
              <div className="section-title">
                <h2>{t("answer")}</h2>
                <span className="status">
                  {answer.mode === "local" ? t("localAssistant") : "OpenAI"}
                </span>
              </div>
              {answer.notice && <div className="notice">{answer.notice}</div>}
              <p className="answer-text">{answer.answer}</p>
              {!!graphIds.length && (
                <Link
                  className="button"
                  to={
                    "/projects/" +
                    pid +
                    "/investigate?node=" +
                    encodeURIComponent(graphIds[0]) +
                    "&selection=" +
                    encodeURIComponent(JSON.stringify(graphIds))
                  }
                >
                  {t("showEvidence")}
                  <ArrowUpRight size={15} />
                </Link>
              )}
              <div className="assistant-evidence">
                {answer.evidence.map((e) => (
                  <article key={e.gid}>
                    <Link
                      className="mono"
                      to={
                        "/projects/" +
                        pid +
                        "/investigate?node=" +
                        encodeURIComponent(e.gid)
                      }
                    >
                      {e.gid}
                      <ArrowUpRight size={12} />
                    </Link>
                    <p>{e.reason}</p>
                  </article>
                ))}
              </div>
              {!!answer.edges.length && (
                <div
                  className="preview-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label={t("showEvidence")}
                >
                  <table>
                    <thead>
                      <tr>
                        <th>{t("from")}</th>
                        <th>{t("to")}</th>
                        <th>{t("turnover")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {answer.edges.map((e) => (
                        <tr key={e.src + ">" + e.dst}>
                          <td className="mono">{e.src}</td>
                          <td className="mono">{e.dst}</td>
                          <td>{f.money(e.sum_kzt, false)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <h3>{t("limitations")}</h3>
              <ul>
                {answer.limitations.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </section>
          ) : (
            !busy && <Empty>{t("assistantEmpty")}</Empty>
          )}
        </div>
      </div>
    </div>
  );
}
