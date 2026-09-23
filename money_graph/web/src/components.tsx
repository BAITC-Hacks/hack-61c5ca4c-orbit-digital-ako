import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import { AlertCircle, Check, X, LoaderCircle } from "lucide-react";
import { api, post } from "./api";
import type { Job, Role } from "./types";
export const roleColors: Record<Role, string> = {
  coordinator: "#D55E00",
  consolidator: "#0072B2",
  distributor: "#CC79A7",
  transit: "#009E73",
  terminal: "#B07D00",
  truncated: "#567487",
  peripheral: "#687580",
};
export const roleSymbols: Record<Role, string> = {
  coordinator: "◆",
  consolidator: "■",
  distributor: "▲",
  transit: "●",
  terminal: "⬟",
  truncated: "◇",
  peripheral: "○",
};
export function RoleBadge({ role }: { role: Role }) {
  const { t } = useTranslation();
  return (
    <span className={"role role-" + role}>
      <span aria-hidden>{roleSymbols[role]}</span>
      {t(role)}
    </span>
  );
}
export function useFormat(currency?: string) {
  const { i18n } = useTranslation();
  const locale =
    { ru: "ru-RU", kk: "kk-KZ", en: "en-US" }[i18n.language] || "ru-RU";
  return {
    num: (n: number | null | undefined) =>
      n == null
        ? "—"
        : new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(n),
    money: (n: number | null | undefined, compact = true) =>
      n == null
        ? "—"
        : new Intl.NumberFormat(locale, {
            style: currency ? "currency" : "decimal",
            currency,
            notation: compact ? "compact" : "standard",
            maximumFractionDigits: compact ? 1 : 2,
          }).format(n),
    percent: (n: number | null | undefined) =>
      n == null
        ? "—"
        : new Intl.NumberFormat(locale, {
            style: "percent",
            maximumFractionDigits: 1,
          }).format(n),
    date: (v: string) => new Date(v).toLocaleDateString(locale),
  };
}
export function Loading() {
  const { t } = useTranslation();
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} />
      {t("loading")}
      <div className="skeleton" />
    </div>
  );
}
export function ErrorBox({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="notice danger" role="alert">
      <AlertCircle size={18} />
      <div>
        {error instanceof Error ? error.message : String(error)}
        {retry && <button onClick={retry}>{t("retry")}</button>}
      </div>
    </div>
  );
}
export function Empty({ children }: { children?: ReactNode }) {
  const { t } = useTranslation();
  return <div className="empty">{children || t("empty")}</div>;
}
export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content
          className={"modal " + (wide ? "wide" : "")}
          aria-describedby={undefined}
        >
          <div className="modal-heading">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close aria-label={t("close")} className="icon-button">
              <X size={20} />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function JobProgress({
  id,
  onDone,
}: {
  id: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    let done = false;
    const events = new EventSource("/api/jobs/" + id + "/events");
    events.onmessage = (e) => {
      const next = JSON.parse(e.data) as Job;
      setJob(next);
      if (next.status === "complete" && !done) {
        done = true;
        events.close();
        onDone();
      }
      if (["error", "cancelled"].includes(next.status)) events.close();
    };
    events.onerror = () => {
      events.close();
      void api<Job>("/jobs/" + id)
        .then((j) => {
          setJob(j);
          if (j.status === "complete" && !done) {
            done = true;
            onDone();
          }
        })
        .catch(setError);
    };
    return () => events.close();
  }, [id, onDone]);
  return (
    <div className="job-progress">
      <div className="flex justify-between">
        <strong>{t(job?.stage || "processing")}</strong>
        <span>{job?.percent || 0}%</span>
      </div>
      <progress
        value={job?.percent || 0}
        max={100}
        aria-label={t("processing")}
      />
      <ol className="job-timeline">
        {job?.timeline?.map((stage, i) => (
          <li key={i}>
            <span>{t(stage.stage)}</span>
            <time>
              {(
                (job.timeline?.[i + 1]?.elapsed ?? stage.elapsed) -
                stage.elapsed
              ).toFixed(1)}{" "}
              s
            </time>
          </li>
        ))}
      </ol>
      {job?.status === "error" && <ErrorBox error={job.message} />}{" "}
      {error ? <ErrorBox error={error} /> : null}
      {job?.status === "cancelled" ? (
        <p>{t("cancelled")}</p>
      ) : (
        job?.status !== "complete" && (
          <button onClick={() => void post("/jobs/" + id + "/cancel")}>
            {t("cancel")}
          </button>
        )
      )}
    </div>
  );
}
export function Toast({ message }: { message: string }) {
  return message ? (
    <div className="toast" role="status">
      <Check size={16} />
      {message}
    </div>
  ) : null;
}
