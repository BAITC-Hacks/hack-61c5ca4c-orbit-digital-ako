import { useMemo, useRef, useState } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useTranslation } from "react-i18next";
import { api, root } from "./api";
import type { NodeRow, Summary, Role } from "./types";
import { Inspector } from "./Inspector";
import { useWorkspace } from "./store";
import {
  Loading,
  ErrorBox,
  RoleBadge,
  roleColors,
  useFormat,
} from "./components";
export function NodeTable() {
  const { pid = "" } = useParams();
  const { t } = useTranslation();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const id = params.get("node") || "";
  const [selected, setSelected] = useState<string[]>([]);
  const [exportError, setExportError] = useState<unknown>();
  async function exportSelected() {
    setExportError(undefined);
    try {
      const response = await fetch(
        "/api" + root(pid) + "/export/selection.csv",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: selected }),
        },
      );
      if (!response.ok) throw new Error((await response.json()).detail);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "selected_nodes.csv";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setExportError(error);
    }
  }
  const [visibility, setVisibility] = useState<Record<string, boolean>>({
    depth: false,
    betweenness: false,
  });
  const add = useWorkspace((s) => s.add);
  const scroll = useRef<HTMLDivElement>(null);
  const limit = 500;
  const page = Number(params.get("page") || 0);
  function patch(k: string, v: string) {
    setParams((p) => {
      const n = new URLSearchParams(p);
      v ? n.set(k, v) : n.delete(k);
      if (k !== "page" && k !== "node") n.delete("page");
      return n;
    });
  }
  const qs = new URLSearchParams(params);
  qs.delete("node");
  qs.set("offset", String(page * limit));
  qs.set("limit", String(limit));
  const query = useQuery({
    queryKey: ["table", pid, qs.toString()],
    queryFn: () =>
      api<{ items: NodeRow[]; total: number }>(root(pid) + "/nodes?" + qs),
  });
  const summary = useQuery({
    queryKey: ["summary", pid],
    queryFn: () => api<Summary>(root(pid) + "/summary"),
  });
  const f = useFormat(summary.data?.currency);
  const cols = useMemo<ColumnDef<NodeRow>[]>(
    () => [
      {
        id: "select",
        header: () => (
          <input
            aria-label={t("selection")}
            type="checkbox"
            checked={
              !!query.data?.items.length &&
              query.data.items.every((n) => selected.includes(n.gid))
            }
            onChange={(e) =>
              setSelected(
                e.target.checked
                  ? query.data?.items.map((n) => n.gid) || []
                  : [],
              )
            }
          />
        ),
        cell: ({ row }) => (
          <input
            aria-label={row.original.gid}
            type="checkbox"
            checked={selected.includes(row.original.gid)}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) =>
              setSelected((s) =>
                e.target.checked
                  ? [...s, row.original.gid]
                  : s.filter((x) => x !== row.original.gid),
              )
            }
          />
        ),
      },
      {
        accessorKey: "gid",
        header: "ID",
        cell: ({ getValue }) => (
          <span className="mono">{String(getValue())}</span>
        ),
      },
      {
        accessorKey: "role",
        header: t("roles"),
        cell: ({ getValue }) => <RoleBadge role={getValue() as Role} />,
      },
      {
        accessorKey: "priority_score",
        header: t("priority"),
        cell: ({ getValue }) => Number(getValue()).toFixed(4),
      },
      { accessorKey: "cluster_id", header: t("clusters") },
      {
        accessorKey: "in_kzt",
        header: t("incoming"),
        cell: ({ getValue }) => f.money(Number(getValue())),
      },
      {
        accessorKey: "out_kzt",
        header: t("outgoing"),
        cell: ({ getValue }) => f.money(Number(getValue())),
      },
      {
        accessorKey: "block_impact",
        header: t("blocking"),
        cell: ({ getValue }) => f.percent(getValue() as number | null),
      },
      { accessorKey: "depth", header: t("depth") },
      { accessorKey: "betweenness", header: "Betweenness" },
    ],
    [query.data, selected, t, summary.data?.currency],
  );
  const table = useReactTable({
    data: query.data?.items || [],
    columns: cols,
    getCoreRowModel: getCoreRowModel(),
    state: { columnVisibility: visibility },
    onColumnVisibilityChange: setVisibility,
  });
  const rows = table.getRowModel().rows;
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroll.current,
    estimateSize: () => 48,
    overscan: 12,
  });
  return (
    <div className="page nodes-page">
      <div className="page-heading">
        <h1>
          {t("nodes")} <small>{query.data?.total}</small>
        </h1>
        <div className="actions">
          <button
            onClick={() =>
              localStorage.setItem(
                "table-view-" + pid,
                JSON.stringify({ params: params.toString(), visibility }),
              )
            }
          >
            {t("savedView")}
          </button>
          <button
            onClick={() => {
              const saved = localStorage.getItem("table-view-" + pid);
              if (saved) {
                const v = JSON.parse(saved) as {
                  params: string;
                  visibility: Record<string, boolean>;
                };
                setParams(v.params);
                setVisibility(v.visibility);
              }
            }}
          >
            {t("restoreView")}
          </button>
        </div>
      </div>
      <div className="table-filterbar">
        <input
          aria-label={t("search")}
          placeholder={t("search")}
          value={params.get("q") || ""}
          onChange={(e) => patch("q", e.target.value)}
        />
        <select
          aria-label={t("roles")}
          value={params.get("role") || ""}
          onChange={(e) => patch("role", e.target.value)}
        >
          <option value="">{t("all")}</option>
          {Object.keys(roleColors).map((r) => (
            <option value={r} key={r}>
              {t(r)}
            </option>
          ))}
        </select>
        <details className="column-picker">
          <summary>{t("columns")}</summary>
          <div>
            {table
              .getAllLeafColumns()
              .filter((c) => c.id !== "select")
              .map((c) => (
                <label className="checkbox" key={c.id}>
                  <input
                    type="checkbox"
                    checked={c.getIsVisible()}
                    onChange={c.getToggleVisibilityHandler()}
                  />
                  {c.id}
                </label>
              ))}
          </div>
        </details>
        <span className="spacer" />
        <button
          disabled={!selected.length}
          onClick={() => void exportSelected()}
        >
          {t("exportSelected")}
        </button>
        <button
          disabled={!selected.length}
          onClick={() => add(pid, "caseIds", selected)}
        >
          {t("toCase")} ({selected.length})
        </button>
        <button
          disabled={!selected.length}
          onClick={() => add(pid, "block", selected)}
        >
          {t("toBlock")}
        </button>
      </div>
      {exportError ? <ErrorBox error={exportError} /> : null}
      <div className={"table-workspace " + (id ? "with-inspector" : "")}>
        <div className="panel data-table-panel">
          {query.isPending ? (
            <Loading />
          ) : query.error ? (
            <ErrorBox error={query.error} />
          ) : (
            <>
              <div className="virtual-scroll" ref={scroll}>
                <table className="virtual-table">
                  <thead>
                    {table.getHeaderGroups().map((hg) => (
                      <tr key={hg.id}>
                        {hg.headers.map((h) => (
                          <th
                            key={h.id}
                            style={{
                              width:
                                h.id === "select"
                                  ? 42
                                  : h.id === "gid"
                                    ? 220
                                    : h.id === "role"
                                      ? 170
                                      : 125,
                            }}
                            aria-sort={
                              params.get("sort") === h.id
                                ? params.get("desc") === "false"
                                  ? "ascending"
                                  : "descending"
                                : undefined
                            }
                          >
                            {h.id === "select" ? (
                              flexRender(
                                h.column.columnDef.header,
                                h.getContext(),
                              )
                            ) : (
                              <button
                                onClick={() => {
                                  setParams((p) => {
                                    const n = new URLSearchParams(p);
                                    n.set("sort", h.id);
                                    n.set(
                                      "desc",
                                      p.get("sort") === h.id &&
                                        p.get("desc") !== "false"
                                        ? "false"
                                        : "true",
                                    );
                                    return n;
                                  });
                                }}
                              >
                                {flexRender(
                                  h.column.columnDef.header,
                                  h.getContext(),
                                )}{" "}
                                ↕
                              </button>
                            )}
                          </th>
                        ))}
                      </tr>
                    ))}
                  </thead>
                  <tbody
                    style={{
                      height: virtual.getTotalSize(),
                      position: "relative",
                    }}
                  >
                    {virtual.getVirtualItems().map((v) => {
                      const row = rows[v.index];
                      return (
                        <tr
                          key={row.id}
                          className={id === row.original.gid ? "selected" : ""}
                          style={{
                            position: "absolute",
                            transform: `translateY(${v.start}px)`,
                            height: 48,
                            width: "100%",
                          }}
                          tabIndex={0}
                          aria-selected={selected.includes(row.original.gid)}
                          onKeyDown={(e) =>
                            e.key === "Enter" && patch("node", row.original.gid)
                          }
                          onClick={() => patch("node", row.original.gid)}
                          onDoubleClick={() =>
                            nav(
                              "/projects/" +
                                pid +
                                "/investigate?node=" +
                                encodeURIComponent(row.original.gid),
                            )
                          }
                        >
                          {row.getVisibleCells().map((c) => (
                            <td
                              key={c.id}
                              style={{
                                width:
                                  c.column.id === "select"
                                    ? 42
                                    : c.column.id === "gid"
                                      ? 220
                                      : c.column.id === "role"
                                        ? 170
                                        : 125,
                              }}
                            >
                              {flexRender(
                                c.column.columnDef.cell,
                                c.getContext(),
                              )}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="pagination">
                <span>
                  {t("page")} {page + 1} · {query.data?.total}
                </span>
                <button
                  disabled={!page}
                  onClick={() => patch("page", String(page - 1))}
                >
                  ←
                </button>
                <button
                  disabled={(page + 1) * limit >= (query.data?.total || 0)}
                  onClick={() => patch("page", String(page + 1))}
                >
                  →
                </button>
              </div>
            </>
          )}
        </div>
        {id && (
          <Inspector
            pid={pid}
            id={id}
            currency={summary.data?.currency}
            onSelect={(next) => patch("node", next)}
            onClose={() => patch("node", "")}
          />
        )}
      </div>
    </div>
  );
}
