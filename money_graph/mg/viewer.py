"""Собрать автономный HTML-экран из исходников ui/ и результатов пайплайна."""

import base64
import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ROLE_COLORS = {
    "coordinator": "#ad3f3c",
    "consolidator": "#a35c19",
    "distributor": "#7656a3",
    "transit": "#15658a",
    "terminal": "#28795a",
    "truncated": "#687884",
    "peripheral": "#617887",
}
ROLE_RU = {
    "coordinator": "Координатор",
    "consolidator": "Консолидатор",
    "distributor": "Распределитель",
    "transit": "Транзит",
    "terminal": "Конечный получатель",
    "truncated": "Обрезан на 4-м хопе",
    "peripheral": "Периферия",
}


def _num(value, digits=4):
    return None if pd.isna(value) else round(float(value), digits)


def _script_json(data):
    """Экранировать JSON при встраивании внутрь script в автономном HTML."""
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def _script_hash(source):
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def write_viewer(path, df, edges, clusters, top, res, summary, vis_js, requests, cfg):
    nodes = [{
        "id": str(gid), "role": row.role, "rs": _num(row.role_score, 2),
        "cl": int(row.cluster_id), "pr": _num(row.priority_score),
        "ev": row.evidence, "d": int(row.depth), "seed": bool(row.is_seed),
        "ind": int(row.in_deg), "outd": int(row.out_deg),
        "ink": _num(row.in_kzt, 0), "outk": _num(row.out_kzt, 0),
        "pt": _num(row.pass_through, 3), "ts": _num(row.taint_share, 3),
        "ti": _num(row.tainted_in_kzt, 0), "bi": _num(row.block_impact, 4),
        "po": _num(row.p_onward, 3), "fs": _num(row.fast_share, 2),
        "sources": int(row.seed_sources),
    } for gid, row in df.iterrows()]
    graph_edges = [[str(row.src), str(row.dst), float(row.sum_kzt), int(row.n_tx)]
                   for row in edges.itertuples(index=False)]
    requests_data = [
        {"gid": str(row.gid), "request_type": row.request_type,
         "weight": float(row.weight), "reason": row.reason}
        for row in requests.itertuples(index=False)
    ]
    data = {
        "nodes": nodes,
        "edges": graph_edges,
        "clusters": json.loads(clusters.to_json(orient="records", force_ascii=False)),
        "top": json.loads(top.assign(gid=top.gid.astype(str)).to_json(
            orient="records", force_ascii=False)),
        "res": json.loads(res.to_json(orient="records")),
        "requests": requests_data,
        "summary": summary,
        "rules": cfg["roles"],
        "weights": cfg["priority_weights"],
        "colors": ROLE_COLORS,
        "roleRu": ROLE_RU,
    }
    ui = ROOT / "ui"
    html = (ui / "index.html").read_text(encoding="utf-8")
    vendor_script = Path(vis_js).read_text(encoding="utf-8")
    data_script = "const D=" + _script_json(data) + ";"
    app_script = (ui / "app.js").read_text(encoding="utf-8")
    policy = (
        "default-src 'none'; script-src " +
        " ".join(_script_hash(source) for source in (vendor_script, data_script, app_script)) +
        "; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; "
        "font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    )
    html = html.replace("/*CSP*/", policy)
    html = html.replace("/*STYLES*/", (ui / "styles.css").read_text(encoding="utf-8"))
    html = html.replace("/*VIS*/", vendor_script)
    html = html.replace("const D=/*DATA*/;", data_script)
    html = html.replace("/*APP*/", app_script)
    Path(path).write_text(html, encoding="utf-8")
