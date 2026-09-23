import { useEffect, useRef, useState } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import { EdgeArrowProgram } from "sigma/rendering";
import { createNodeImageProgram } from "@sigma/node-image";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import { useTranslation } from "react-i18next";
import {
  Download,
  Expand,
  Maximize,
  Minus,
  Plus,
  RefreshCw,
} from "lucide-react";
import type { GraphData, Role } from "./types";
import { roleColors } from "./components";

function nodeImage(role: Role, mode: string, seed: boolean) {
  const c = roleColors[role] || roleColors.peripheral;
  const shape: Record<Role, string> = {
    coordinator: '<path d="M32 6 57 32 32 58 7 32Z"/>',
    consolidator: '<rect x="10" y="10" width="44" height="44" rx="6"/>',
    distributor: '<path d="M32 6 58 55H6Z"/>',
    transit: '<circle cx="32" cy="32" r="23"/>',
    terminal: '<path d="M19 8H45L58 32 45 56H19L6 32Z"/>',
    truncated:
      '<path d="M32 7 57 32 32 57 7 32Z" fill="white" stroke-width="7"/>',
    peripheral: '<circle cx="32" cy="32" r="20"/>',
  };
  const icon: Record<Role, string> = {
    coordinator: '<path d="M18 40V23H46V40M23 23V16H41V23M25 29V34M39 29V34"/>',
    consolidator: '<path d="M15 20 32 35 49 20M32 35V49M20 43H44"/>',
    distributor:
      '<path d="M32 14V30M15 46 32 30 49 46M15 35V46H26M38 46H49V35"/>',
    transit: '<path d="M16 23H47L39 15M48 41H17L25 49"/>',
    terminal: '<path d="M16 47H48M20 47V28H44V47M16 27 32 14 48 27Z"/>',
    truncated: '<path d="M16 32H27M37 32H48M35 14 29 50"/>',
    peripheral:
      '<circle cx="32" cy="23" r="7"/><path d="M18 48C18 32 46 32 46 48"/>',
  };
  const body =
    mode === "icons"
      ? `<circle cx="32" cy="32" r="25" fill="${c}"/><g fill="none" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${icon[role]}</g>`
      : mode === "circles"
        ? '<circle cx="32" cy="32" r="24"/>'
        : shape[role];
  return (
    "data:image/svg+xml;charset=utf-8," +
    encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">${seed ? '<circle cx="32" cy="32" r="31" fill="none" stroke="#152e3b" stroke-width="2"/>' : ""}<g fill="${c}" stroke="${c}" stroke-width="2">${body}</g></svg>`,
    )
  );
}
type Props = {
  data: GraphData;
  selected?: string;
  onSelect: (id: string) => void;
  onFocus: (id: string) => void;
  onEdge?: (src: string, dst: string) => void;
  hidden: string[];
  pinned: string[];
  highlight?: string[];
  storageKey: string;
};
export function GraphCanvas({
  data,
  selected,
  onSelect,
  onFocus,
  onEdge,
  hidden,
  pinned,
  highlight = [],
  storageKey,
}: Props) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const renderer = useRef<Sigma | null>(null);
  const layout = useRef<FA2Layout | null>(null);
  const [mode, setMode] = useState(
    localStorage.getItem("graph-style") || "shapes",
  );
  const [error, setError] = useState("");
  const [full, setFull] = useState(false);
  const [map, setMap] = useState<
    { id: string; x: number; y: number; c: string }[]
  >([]);
  const callbacks = useRef({ onSelect, onFocus, onEdge });
  callbacks.current = { onSelect, onFocus, onEdge };
  const pinRef = useRef(pinned);
  pinRef.current = pinned;
  useEffect(() => {
    if (!container.current) return;
    setError("");
    const g = new Graph({ type: "directed", allowSelfLoops: true });
    const positions = JSON.parse(
      localStorage.getItem(storageKey) || "{}",
    ) as Record<string, { x: number; y: number }>;
    data.nodes.forEach((n, i) => {
      const a = i * 2.399963229728653,
        r = Math.sqrt(i + 1);
      g.addNode(n.gid, {
        x: positions[n.gid]?.x ?? Math.cos(a) * r,
        y: positions[n.gid]?.y ?? Math.sin(a) * r,
        size: data.overview ? 14 : 7 + 9 * (n.priority_score || 0),
        label: n.label || n.gid,
        color: roleColors[n.role] || "#687580",
        type: "image",
        backgroundColor: "rgba(0,0,0,0)",
        image: nodeImage(n.role || "peripheral", mode, n.is_seed),
        fixed: pinRef.current.includes(n.gid),
      });
    });
    data.edges.forEach((e, i) => {
      if (g.hasNode(e.src) && g.hasNode(e.dst) && !g.hasEdge(e.src, e.dst))
        g.addDirectedEdgeWithKey(String(i), e.src, e.dst, {
          size: Math.max(0.5, Math.log10(e.amount + 1) / 3),
          color: "#a9b9c4",
          type: "arrow",
        });
    });
    let timer: ReturnType<typeof setTimeout>;
    let mapTimer: ReturnType<typeof setTimeout>;
    let sigma: Sigma;
    try {
      sigma = new Sigma(g, container.current, {
        nodeProgramClasses: {
          image: createNodeImageProgram({
            keepWithinCircle: false,
            padding: 0,
            colorAttribute: "backgroundColor",
          }),
        },
        edgeProgramClasses: { arrow: EdgeArrowProgram },
        defaultEdgeType: "arrow",
        labelFont: "Inter, sans-serif",
        labelColor: {
          color:
            document.documentElement.dataset.theme === "dark"
              ? "#d4e4ea"
              : "#2a4555",
        },
        labelSize: 11,
        labelDensity: 0.1,
        labelRenderedSizeThreshold: 17,
        renderEdgeLabels: false,
        allowInvalidContainer: true,
        enableEdgeEvents: true,
      });
      renderer.current = sigma;
      let dragged: string | null = null;
      sigma.on("clickEdge", ({ edge }) =>
        callbacks.current.onEdge?.(g.source(edge), g.target(edge)),
      );
      sigma.on("clickNode", ({ node }) => callbacks.current.onSelect(node));
      sigma.on("doubleClickNode", ({ node, event }) => {
        event.preventSigmaDefault();
        callbacks.current.onFocus(node);
      });
      sigma.on("rightClickNode", ({ node, event }) => {
        event.original.preventDefault();
        callbacks.current.onSelect(node);
      });
      sigma.on("downNode", (e) => {
        if (pinRef.current.includes(e.node)) return;
        dragged = e.node;
        layout.current?.stop();
        sigma.getCamera().disable();
        if (!sigma.getCustomBBox()) sigma.setCustomBBox(sigma.getBBox());
      });
      sigma.getMouseCaptor().on("mousemovebody", (e) => {
        if (!dragged) return;
        const pos = sigma.viewportToGraph(e);
        g.mergeNodeAttributes(dragged, pos);
        e.preventSigmaDefault();
        e.original.preventDefault();
        e.original.stopPropagation();
      });
      sigma.getMouseCaptor().on("mouseup", () => {
        if (dragged) {
          positions[dragged] = {
            x: g.getNodeAttribute(dragged, "x"),
            y: g.getNodeAttribute(dragged, "y"),
          };
          localStorage.setItem(storageKey, JSON.stringify(positions));
        }
        dragged = null;
        sigma.getCamera().enable();
      });
      layout.current = new FA2Layout(g, {
        settings: {
          barnesHutOptimize: true,
          gravity: 1,
          scalingRatio: 8,
          slowDown: 5,
        },
        getEdgeWeight: () => 1,
      });
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
        layout.current.start();
        timer = setTimeout(
          () => layout.current?.stop(),
          data.nodes.length > 1000 ? 3500 : 1800,
        );
      }
      const updateMap = () => {
        const coords = g.nodes().map((id) => ({
          id,
          x: g.getNodeAttribute(id, "x") as number,
          y: g.getNodeAttribute(id, "y") as number,
          c: g.getNodeAttribute(id, "color") as string,
        }));
        setMap(coords);
      };
      mapTimer = setTimeout(updateMap, 2000);
      updateMap();
    } catch (e) {
      setError(String(e));
    }
    return () => {
      clearTimeout(timer);
      clearTimeout(mapTimer);
      layout.current?.kill();
      renderer.current?.kill();
      renderer.current = null;
    };
  }, [data, mode, storageKey]);
  useEffect(() => {
    const sigma = renderer.current;
    if (!sigma) return;
    const h = new Set(highlight);
    sigma.setSetting("nodeReducer", (id, a) => ({
      ...a,
      hidden: hidden.includes(id),
      highlighted: id === selected || h.has(id),
      zIndex: id === selected ? 3 : 1,
      size: id === selected ? a.size * 1.35 : a.size,
      forceLabel: id === selected || h.has(id),
    }));
    sigma.setSetting("edgeReducer", (_, a) => a);
    sigma
      .getGraph()
      .forEachNode((id) =>
        sigma.getGraph().setNodeAttribute(id, "fixed", pinned.includes(id)),
      );
  }, [selected, hidden, pinned, highlight]);
  useEffect(() => {
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") setFull(false);
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  function png() {
    const s = renderer.current;
    if (!s) return;
    s.refresh();
    const canvases = s.getCanvases();
    const base = document.createElement("canvas");
    const first = Object.values(canvases)[0];
    base.width = first.width;
    base.height = first.height;
    const ctx = base.getContext("2d")!;
    ctx.fillStyle = "#f4f7f8";
    ctx.fillRect(0, 0, base.width, base.height);
    Object.values(canvases).forEach((canvas) => ctx.drawImage(canvas, 0, 0));
    const link = document.createElement("a");
    link.download = "money-graph.png";
    link.href = base.toDataURL();
    link.click();
  }
  const range = (key: "x" | "y") => {
    const values = map.map((n) => n[key]);
    return { min: Math.min(...values), max: Math.max(...values) };
  };
  const xr = range("x"),
    yr = range("y");
  return (
    <section
      className={"graph-shell " + (full ? "graph-full" : "")}
      aria-label={t("investigate")}
    >
      <div className="graph-toolbar">
        <select
          aria-label={t("shapes")}
          value={mode}
          onChange={(e) => {
            setMode(e.target.value);
            localStorage.setItem("graph-style", e.target.value);
          }}
        >
          {["shapes", "icons", "circles"].map((x) => (
            <option key={x} value={x}>
              {t(x)}
            </option>
          ))}
        </select>
        <span className="graph-count">
          {t("graphLimit", {
            shown:
              data.nodes.length -
              hidden.filter((id) => data.nodes.some((n) => n.gid === id))
                .length,
            total: data.available,
          })}
        </span>
        <button
          className="icon-button"
          title={t("layout")}
          aria-label={t("layout")}
          onClick={() => {
            layout.current?.start();
            setTimeout(() => layout.current?.stop(), 2000);
          }}
        >
          <RefreshCw size={16} />
        </button>
        <button
          className="icon-button"
          title={t("exportPng")}
          aria-label={t("exportPng")}
          onClick={png}
        >
          <Download size={16} />
        </button>
        <button
          className="icon-button"
          aria-label={t("fit")}
          onClick={() => renderer.current?.getCamera().animatedReset()}
        >
          <Maximize size={16} />
        </button>
        <button
          className="icon-button"
          aria-label="Fullscreen"
          onClick={() => setFull(!full)}
        >
          <Expand size={16} />
        </button>
      </div>
      <div
        ref={container}
        className="graph-canvas"
        role="img"
        aria-label={t("investigate")}
      />
      {error && <div className="notice danger">{error}</div>}
      <div className="graph-zoom">
        <button
          aria-label="Zoom in"
          onClick={() => renderer.current?.getCamera().animatedZoom()}
        >
          <Plus size={17} />
        </button>
        <button
          aria-label="Zoom out"
          onClick={() => renderer.current?.getCamera().animatedUnzoom()}
        >
          <Minus size={17} />
        </button>
      </div>
      <svg className="minimap" viewBox="0 0 130 85" aria-hidden>
        {map.map((n) => (
          <circle
            key={n.id}
            cx={8 + ((n.x - xr.min) / (xr.max - xr.min || 1)) * 114}
            cy={8 + ((n.y - yr.min) / (yr.max - yr.min || 1)) * 69}
            r={n.id === selected ? 3 : 1.3}
            fill={n.c}
          />
        ))}
      </svg>
      <div className="graph-legend">
        {Object.keys(roleColors).map((r) => (
          <span key={r}>
            <i style={{ background: roleColors[r as Role] }} />
            {t(r)}
          </span>
        ))}
      </div>
    </section>
  );
}
