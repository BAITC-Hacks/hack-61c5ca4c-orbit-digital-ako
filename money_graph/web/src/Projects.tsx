import { useCallback, useEffect, useState } from "react";
import { useWorkspace } from "./store";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  Check,
  Database,
  FileUp,
  FolderOpen,
  Network,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { api, post, put, root } from "./api";
import type { Project, Preview, MappingFile, Quality } from "./types";
import {
  Empty,
  ErrorBox,
  JobProgress,
  Loading,
  Modal,
  useFormat,
} from "./components";

export function Projects() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const forget = useWorkspace((s) => s.forget);
  const cache = useQueryClient();
  const f = useFormat();
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("/projects"),
  });
  const schema = z.object({ name: z.string().trim().min(1).max(120) });
  const form = useForm<{ name: string }>({ resolver: zodResolver(schema) });
  async function create(value: { name: string }) {
    setBusy(true);
    try {
      const p = await post<Project>("/projects", value);
      await cache.invalidateQueries({ queryKey: ["projects"] });
      nav("/projects/" + p.id + "/upload");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function demo() {
    setBusy(true);
    try {
      const r = await post<{ project_id: string; job_id: string }>("/demo");
      nav("/projects/" + r.project_id + "/upload?job=" + r.job_id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page projects-page">
      <div className="eyebrow">
        <ShieldCheck size={15} />
        {t("local")}
      </div>
      <div className="hero-grid">
        <div>
          <h1>{t("intro")}</h1>
          <p className="lead">{t("introText")}</p>
          <div className="actions">
            <button className="primary" onClick={() => setOpen(true)}>
              <Plus size={17} />
              {t("newAnalysis")}
            </button>
            <button disabled={busy} onClick={() => void demo()}>
              {t("demo")}
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
        <div className="hero-network" aria-hidden>
          <svg viewBox="0 0 400 190">
            <g stroke="currentColor" opacity=".2">
              {[
                [40, 120, 140, 60],
                [140, 60, 235, 105],
                [140, 60, 250, 25],
                [235, 105, 335, 50],
                [235, 105, 335, 160],
                [40, 120, 150, 165],
                [150, 165, 235, 105],
                [250, 25, 335, 50],
              ].map((a, i) => (
                <line key={i} x1={a[0]} y1={a[1]} x2={a[2]} y2={a[3]} />
              ))}
            </g>
            <g fill="#c4d9d9">
              <circle cx="40" cy="120" r="9" />
              <circle cx="250" cy="25" r="8" />
              <circle cx="150" cy="165" r="8" />
              <circle cx="335" cy="50" r="11" />
              <circle cx="335" cy="160" r="8" />
            </g>
            <rect x="121" y="41" width="38" height="38" rx="8" fill="#0072b2" />
            <path d="M235 77 263 105 235 133 207 105Z" fill="#d55e00" />
          </svg>
          <span>01 — 02 — 03</span>
        </div>
      </div>
      <div className="process-strip">
        {[FileUp, ShieldCheck, Network].map((Icon, i) => (
          <div key={i}>
            <span className="step-number">0{i + 1}</span>
            <Icon size={20} />
            <strong>{t("step" + (i + 1))}</strong>
          </div>
        ))}
      </div>
      <div className="section-title">
        <h2>{t("projects")}</h2>
        <span className="muted">{query.data?.length || 0}</span>
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} />
      ) : (
        <div className="project-grid">
          {query.data?.map((p) => (
            <article className="project-card" key={p.id}>
              <div className="flex justify-between">
                <FolderOpen className="accent" size={24} />
                <span className={"status " + p.status}>{t(p.status)}</span>
              </div>
              <h3>{p.name}</h3>
              <p className="muted">{f.date(p.created)}</p>
              <div className="project-stats">
                <span>
                  <strong>{f.num(p.summary?.nodes)}</strong>
                  {t("nodes")}
                </span>
                <span>
                  <strong>{f.num(p.summary?.transactions)}</strong>
                  {t("transactions")}
                </span>
              </div>
              <div className="card-footer">
                <button
                  className="text-button"
                  onClick={() =>
                    nav(
                      "/projects/" +
                        p.id +
                        (p.summary ? "/overview" : "/upload"),
                    )
                  }
                >
                  {t("open")}
                  <ArrowRight size={16} />
                </button>
                <button
                  className="icon-button"
                  aria-label={t("delete")}
                  onClick={() => setDeleting(p)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </article>
          ))}
          <button
            className="project-card add-project"
            onClick={() => setOpen(true)}
          >
            <Plus size={24} />
            {t("newAnalysis")}
          </button>
        </div>
      )}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("newAnalysis")}
      >
        <form onSubmit={form.handleSubmit(create)}>
          <label>
            {t("name")}
            <input
              autoFocus
              {...form.register("name")}
              placeholder="Анализ переводов"
              aria-invalid={!!form.formState.errors.name}
            />
          </label>
          {form.formState.errors.name && <p role="alert">1–120</p>}
          <button className="primary" disabled={busy}>
            {t("create")}
          </button>
        </form>
      </Modal>
      <Modal
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={t("delete")}
      >
        <p>{t("deleteConfirm")}</p>
        <button
          className="destructive"
          onClick={async () => {
            if (!deleting) return;
            try {
              await api(root(deleting.id), { method: "DELETE" });
              forget(deleting.id);
              for (const key of Object.keys(localStorage))
                if (key.includes(deleting.id)) localStorage.removeItem(key);
              cache.removeQueries({
                predicate: (q) => q.queryKey.includes(deleting.id),
              });
              setDeleting(null);
              await cache.invalidateQueries({ queryKey: ["projects"] });
            } catch (e) {
              setError(e);
              setDeleting(null);
            }
          }}
        >
          {t("delete")}
        </button>
      </Modal>
    </div>
  );
}

export function UploadWizard() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const nav = useNavigate();
  const [step, setStep] = useState(
    new URLSearchParams(location.search).has("job") ? 4 : 0,
  );
  const [job, setJob] = useState(
    new URLSearchParams(location.search).get("job") || "",
  );
  const [previews, setPreviews] = useState<Preview[]>([]);
  const [mapping, setMapping] = useState<MappingFile[]>([]);
  const [currency, setCurrency] = useState("");
  const [seeds, setSeeds] = useState("");
  const [threshold, setThreshold] = useState("");
  const [depth, setDepth] = useState("");
  const [dayfirst, setDayfirst] = useState(true);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [language, setLanguage] = useState("ru");
  const normalized = useQuery({
    queryKey: ["normalized-preview", pid, mapping, dayfirst],
    queryFn: () =>
      post<
        {
          file_id: string;
          columns: string[];
          rows: Record<string, unknown>[];
        }[]
      >(root(pid) + "/preview", { files: mapping, dayfirst }),
    enabled: step === 1 && mapping.length > 0,
  });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ default_currency: string }>("/health"),
  });
  const project = useQuery({
    queryKey: ["project", pid],
    queryFn: () => api<Project>(root(pid)),
  });
  const done = useCallback(
    () => nav("/projects/" + pid + "/overview"),
    [nav, pid],
  );
  useEffect(() => {
    if (job) return;
    let active = true;
    void api<Preview[]>(root(pid) + "/preview")
      .then((list) => {
        if (!active || !list.length) return;
        setPreviews(list);
        setMapping(
          list.map((f) => ({
            file_id: f.id,
            kind: f.proposal.kind,
            fields: Object.fromEntries(
              Object.entries(f.proposal.fields).map(([k, v]) => [k, v.column]),
            ),
          })),
        );
      })
      .catch(setError);
    return () => {
      active = false;
    };
  }, [pid]);
  async function upload(files: FileList | File[]) {
    setBusy(true);
    setError(undefined);
    try {
      const data = new FormData();
      Array.from(files).forEach((f) => data.append("files", f));
      await api(root(pid) + "/files", { method: "POST", body: data });
      const list = await api<Preview[]>(root(pid) + "/preview");
      setPreviews(list);
      setMapping(
        list.map((f) => ({
          file_id: f.id,
          kind: f.proposal.kind,
          fields: Object.fromEntries(
            Object.entries(f.proposal.fields).map(([k, v]) => [k, v.column]),
          ),
        })),
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  function field(index: number, key: string, value: string) {
    setMapping((m) =>
      m.map((x, i) =>
        i === index ? { ...x, fields: { ...x.fields, [key]: value } } : x,
      ),
    );
  }
  async function check() {
    setBusy(true);
    setError(undefined);
    try {
      const q = await put<Quality>(root(pid) + "/mapping", {
        files: mapping,
        seeds: seeds.split(/[\s,;]+/).filter(Boolean),
        currency: currency || health.data?.default_currency,
        collection_threshold: threshold ? Number(threshold) : null,
        max_depth: depth ? Number(depth) : null,
        dayfirst,
        language,
        confirmed: true,
      });
      setQuality(q);
      setStep(3);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function run() {
    setBusy(true);
    try {
      const r = await post<{ job_id: string }>(root(pid) + "/run");
      setJob(r.job_id);
      setStep(4);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const fieldsFor = (kind: string) =>
    kind === "nodes"
      ? ["id", "depth", "is_seed"]
      : kind === "seeds"
        ? ["id"]
        : kind === "transactions"
          ? ["src", "dst", "amount", "date"]
          : ["src", "dst", "amount", "n_tx"];
  return (
    <div className="page wizard-page">
      <div className="eyebrow">{project.data?.name}</div>
      <h1>{t("newAnalysis")}</h1>
      <ol className="stepper">
        {["files", "mapping", "parameters", "quality", "run"].map((name, i) => (
          <li
            key={name}
            className={step === i ? "active" : step > i ? "done" : ""}
          >
            <button disabled={i > step || !!job} onClick={() => setStep(i)}>
              <span>{step > i ? <Check size={15} /> : i + 1}</span>
              {t(name)}
            </button>
          </li>
        ))}
      </ol>
      {error ? <ErrorBox error={error} /> : null}
      <section className="panel wizard-panel">
        {step === 0 && (
          <>
            <label
              className="dropzone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                void upload(e.dataTransfer.files);
              }}
            >
              <FileUp size={34} />
              <strong>{t("drop")}</strong>
              <span>{t("formats")}</span>
              <input
                type="file"
                accept=".csv,.parquet,.xlsx"
                multiple
                disabled={busy}
                onChange={(e) => e.target.files && void upload(e.target.files)}
              />
            </label>
            {busy && <Loading />}
            {previews.map((p) => (
              <div className="file-row" key={p.id}>
                <Database size={18} />
                <strong>{p.name}</strong>
                <span>
                  {p.format} · {p.encoding || "binary"} · {p.columns.length}{" "}
                  columns
                </span>
                <Check size={18} />
              </div>
            ))}
          </>
        )}
        {step === 1 && (
          <>
            <p className="notice">{t("confirmMapping")}</p>
            {previews.map((file, index) => (
              <div className="mapping-card" key={file.id}>
                <h3>{file.name}</h3>
                <div className="form-grid">
                  <label>
                    {t("fileType")}
                    <select
                      value={mapping[index]?.kind}
                      onChange={(e) =>
                        setMapping((m) =>
                          m.map((x, i) =>
                            i === index ? { ...x, kind: e.target.value } : x,
                          ),
                        )
                      }
                    >
                      {[
                        "transactions",
                        "edges",
                        "nodes",
                        "seeds",
                        "ignore",
                      ].map((k) => (
                        <option key={k} value={k}>
                          {t(k === "seeds" ? "seedFile" : k)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {file.sheets.length > 1 && (
                    <label>
                      Sheet
                      <select
                        onChange={async (e) => {
                          const list = await api<Preview[]>(
                            root(pid) +
                              "/preview?file_id=" +
                              file.id +
                              "&sheet=" +
                              encodeURIComponent(e.target.value),
                          );
                          setPreviews((p) =>
                            p.map((x, i) => (i === index ? list[0] : x)),
                          );
                          setMapping((m) =>
                            m.map((x, i) =>
                              i === index
                                ? {
                                    ...x,
                                    sheet: e.target.value,
                                    fields: Object.fromEntries(
                                      Object.entries(
                                        list[0].proposal.fields,
                                      ).map(([k, v]) => [k, v.column]),
                                    ),
                                  }
                                : x,
                            ),
                          );
                        }}
                      >
                        {file.sheets.map((s) => (
                          <option key={s}>{s}</option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                {mapping[index]?.kind !== "ignore" && (
                  <div className="mapping-fields">
                    {fieldsFor(mapping[index]?.kind).map((key) => (
                      <label key={key}>
                        <span>
                          {key}{" "}
                          {file.proposal.fields[key] && (
                            <small>
                              {Math.round(
                                file.proposal.fields[key].confidence * 100,
                              )}
                              %
                            </small>
                          )}
                        </span>
                        <select
                          value={mapping[index]?.fields[key] || ""}
                          onChange={(e) => field(index, key, e.target.value)}
                        >
                          <option value="">{t("notMapped")}</option>
                          {file.columns.map((c) => (
                            <option key={c}>{c}</option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </div>
                )}
                <h3>{t("normalizedPreview")}</h3>
                {normalized.error ? (
                  <ErrorBox error={normalized.error} />
                ) : normalized.isPending ? (
                  <Loading />
                ) : (
                  <div className="preview-scroll">
                    <table>
                      <thead>
                        <tr>
                          {normalized.data
                            ?.find((x) => x.file_id === file.id)
                            ?.columns.map((key) => (
                              <th key={key}>{key}</th>
                            ))}
                        </tr>
                      </thead>
                      <tbody>
                        {normalized.data
                          ?.find((x) => x.file_id === file.id)
                          ?.rows.slice(0, 5)
                          .map((row, i) => (
                            <tr key={i}>
                              {Object.entries(row).map(([key, value]) => (
                                <td key={key}>{String(value ?? "—")}</td>
                              ))}
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <details>
                  <summary>{file.name}</summary>
                  <div className="preview-scroll">
                    <table>
                      <thead>
                        <tr>
                          {file.columns.map((c) => (
                            <th key={c}>{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {file.rows.slice(0, 5).map((r, i) => (
                          <tr key={i}>
                            {file.columns.map((c) => (
                              <td key={c}>{String(r[c] ?? "—")}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </div>
            ))}
          </>
        )}
        {step === 2 && (
          <div className="parameters-grid">
            <div>
              <label>
                {t("seeds")}
                <textarea
                  value={seeds}
                  onChange={(e) => setSeeds(e.target.value)}
                  rows={8}
                />
              </label>
              <p className="muted">{t("seedHelp")}</p>
            </div>
            <div className="stack">
              <label>
                {t("currency")}
                <input
                  value={currency || health.data?.default_currency || ""}
                  maxLength={3}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                />
              </label>
              <label>
                {t("threshold")}
                <input
                  type="number"
                  min={0}
                  value={threshold}
                  onChange={(e) => setThreshold(e.target.value)}
                />
              </label>
              <label>
                {t("maxDepth")}
                <input
                  type="number"
                  min={1}
                  value={depth}
                  placeholder={t("noBoundary")}
                  onChange={(e) => setDepth(e.target.value)}
                />
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={dayfirst}
                  onChange={(e) => setDayfirst(e.target.checked)}
                />
                {t("dayfirst")}
              </label>
              <label>
                Language
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  <option value="ru">Русский</option>
                  <option value="kk">Қазақша</option>
                  <option value="en">English</option>
                </select>
              </label>
            </div>
          </div>
        )}
        {step === 3 && quality && (
          <>
            <h2>{t("quality")}</h2>
            {quality.profile && (
              <div className="kpi-row">
                <div>
                  <strong>{quality.profile.n_nodes}</strong>
                  {t("nodes")}
                </div>
                <div>
                  <strong>{quality.profile.n_edges}</strong>
                  {t("edges")}
                </div>
                <div>
                  <strong>{quality.profile.n_tx}</strong>
                  {t("transactions")}
                </div>
              </div>
            )}
            {quality.seeds && (
              <p>
                Seed: {quality.seeds.in_edges} / {quality.seeds.requested}
              </p>
            )}
            {quality.findings.length ? (
              quality.findings.map((q, i) => (
                <div
                  key={i}
                  className={
                    "notice " +
                    (q.level === "error"
                      ? "danger"
                      : q.level === "warning"
                        ? "warning"
                        : "")
                  }
                >
                  <strong>{q.count}</strong>
                  {q.message}
                </div>
              ))
            ) : (
              <div className="notice success">
                <Check size={18} />
                {t("quality")} ✓
              </div>
            )}
            {quality.capabilities
              ?.filter((c) => !c.enabled)
              .map((c) => (
                <div key={c.key} className="notice warning">
                  {c.message}
                </div>
              ))}
          </>
        )}
        {step === 4 && job && <JobProgress id={job} onDone={done} />}
      </section>
      {step < 4 && (
        <div className="wizard-footer">
          <button
            disabled={step === 0 || busy}
            onClick={() => setStep(step - 1)}
          >
            {t("back")}
          </button>
          {step < 2 ? (
            <button
              className="primary"
              disabled={!previews.length || busy}
              onClick={() => setStep(step + 1)}
            >
              {t("next")}
              <ArrowRight size={16} />
            </button>
          ) : step === 2 ? (
            <button
              className="primary"
              disabled={busy}
              onClick={() => void check()}
            >
              {t("confirmMapping")}
            </button>
          ) : (
            <button
              className="primary"
              disabled={!quality?.ok || busy}
              onClick={() => void run()}
            >
              {t("run")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
