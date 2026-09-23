"""Local MVP: upload a case, calculate it, inspect graph and download exports."""

import asyncio
import json
import logging
import re
import shutil
import uuid
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mg.validation import InputError, validate_data
from mg.viewer import ROLE_COLORS, ROLE_RU
from run import analyze

ROOT = Path(__file__).resolve().parent
CASES = ROOT / ".local" / "cases"
EXPORTS = {"nodes_roles.csv", "clusters.csv", "top_nodes.csv", "requests.csv", "resilience.csv"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
ANALYSIS_SLOT = asyncio.Semaphore(1)
app = FastAPI(title="Граф денег", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
app.mount("/vendor", StaticFiles(directory=ROOT / "vendor"), name="vendor")


@app.middleware("http")
async def local_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def case_paths(case_id: str):
    if case_id == "demo":
        return ROOT / "data", ROOT / "out", "Данные HackAlem"
    if not re.fullmatch(r"[0-9a-f]{32}", case_id):
        raise HTTPException(404, "Кейс не найден")
    folder = CASES / case_id
    metadata = folder / "case.json"
    if not metadata.is_file():
        raise HTTPException(404, "Кейс не найден")
    try:
        label = json.loads(metadata.read_text(encoding="utf-8"))["label"]
    except (ValueError, KeyError):
        raise HTTPException(404, "Кейс повреждён")
    return folder / "data", folder / "out", label


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/favicon.svg")
def favicon():
    return FileResponse(ROOT / "web" / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/cases")
def list_cases():
    result = [{"id": "demo", "label": "Данные HackAlem", "summary": _summary(ROOT / "out")}]
    if CASES.is_dir():
        for folder in sorted(CASES.iterdir(), reverse=True):
            if (folder / "case.json").is_file() and (folder / "out" / "summary.json").is_file():
                meta = json.loads((folder / "case.json").read_text(encoding="utf-8"))
                result.append({"id": folder.name, "label": meta["label"], "summary": _summary(folder / "out")})
    return result


def _summary(out: Path):
    return json.loads((out / "summary.json").read_text(encoding="utf-8"))


async def save_upload(upload: UploadFile, target: Path):
    size = 0
    with target.open("wb") as dst:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise InputError(f"{target.name}: файл превышает 64 МБ")
            dst.write(chunk)
    if size == 0:
        raise InputError(f"{target.name}: пустой файл")


@app.post("/api/cases", status_code=201)
async def create_case(request: Request, nodes: UploadFile = File(...), edges: UploadFile = File(...),
                      transactions: UploadFile = File(...), label: str = Form("Новый кейс"),
                      min_tx_kzt: int = Form(5000), max_depth: int = Form(4)):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Загрузка разрешена только из локального интерфейса")
    if min_tx_kzt < 0 or min_tx_kzt > 1_000_000_000:
        raise HTTPException(422, "Некорректный порог суммы")
    if not 1 <= max_depth <= 4:
        raise HTTPException(422, "Граница обхода должна быть от 1 до 4 хопов")
    label = label.strip()[:80] or "Новый кейс"
    case_id = uuid.uuid4().hex
    folder = CASES / case_id
    if folder.resolve().parent != CASES.resolve():
        raise HTTPException(400, "Некорректный идентификатор кейса")
    data = folder / "data"
    data.mkdir(parents=True, exist_ok=False)
    try:
        for upload, name in ((nodes, "nodes.parquet"), (edges, "edges.parquet"),
                             (transactions, "transactions.parquet")):
            await save_upload(upload, data / name)
        info = await asyncio.to_thread(validate_data, data, min_tx_kzt, max_depth)
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        cfg["min_tx_kzt"] = min_tx_kzt
        cfg["max_depth"] = max_depth
        (folder / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        async with ANALYSIS_SLOT:
            summary = await asyncio.to_thread(analyze, data, folder / "out", cfg)
        (folder / "case.json").write_text(json.dumps({"label": label, "min_tx_kzt": min_tx_kzt}, ensure_ascii=False), encoding="utf-8")
        return {"id": case_id, "label": label, "input": info, "summary": summary}
    except InputError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logging.exception("Analysis failed for case %s", case_id)
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(500, "Не удалось завершить расчёт. Проверьте формат данных; подробности в журнале сервера.") from exc
    finally:
        for upload in (nodes, edges, transactions):
            await upload.close()


def csv_records(path: Path, gid_fields=()):
    dtype = {field: str for field in gid_fields}
    return json.loads(pd.read_csv(path, dtype=dtype).to_json(orient="records", force_ascii=False))


@app.get("/api/cases/{case_id}/graph")
def graph(case_id: str):
    data, out, label = case_paths(case_id)
    summary = _summary(out)
    nodes = csv_records(out / "nodes_roles.csv", ("gid",))
    edges = pd.read_parquet(data / "edges.parquet")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if case_id != "demo":
        if (out.parent / "config.json").is_file():
            config = json.loads((out.parent / "config.json").read_text(encoding="utf-8"))
        config["min_tx_kzt"] = json.loads((out.parent / "case.json").read_text(encoding="utf-8")).get("min_tx_kzt", 5000)
    return {
        "id": case_id, "label": label, "summary": summary,
        "nodes": nodes,
        "edges": [[str(row.src), str(row.dst), float(row.sum_kzt), int(row.n_tx)]
                  for row in edges.itertuples(index=False)],
        "clusters": csv_records(out / "clusters.csv"),
        "top": csv_records(out / "top_nodes.csv", ("gid",)),
        "requests": csv_records(out / "requests.csv", ("gid",)),
        "resilience": csv_records(out / "resilience.csv"),
        "colors": ROLE_COLORS,
        "role_names": {**ROLE_RU, "truncated": f"Обрезан на {summary.get('max_depth', 4)}-м хопе"},
        "rules": config["roles"],
    }


@app.get("/api/cases/{case_id}/transactions")
def transactions_for_link(case_id: str, src: str = Query(pattern=r"^-?\d{1,19}$"),
                          dst: str = Query(pattern=r"^-?\d{1,19}$"),
                          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    data, _, _ = case_paths(case_id)
    frame = pd.read_parquet(data / "transactions.parquet")
    selected = frame[(frame.src.astype(str) == src) & (frame.dst.astype(str) == dst)].copy()
    selected["date"] = pd.to_datetime(selected.date)
    selected = selected.sort_values("date", ascending=False, kind="stable")
    rows = selected.iloc[offset:offset + limit]
    return {"src": src, "dst": dst, "total": len(selected),
            "sum_kzt": float(selected.sum_kzt.sum()), "offset": offset, "limit": limit,
            "items": [{"date": row.date.isoformat(), "sum_kzt": float(row.sum_kzt)}
                      for row in rows.itertuples(index=False)]}


@app.get("/api/cases/{case_id}/exports/{filename}")
def export(case_id: str, filename: str):
    if filename not in EXPORTS:
        raise HTTPException(404, "Выгрузка не найдена")
    _, out, _ = case_paths(case_id)
    path = out / filename
    if not path.is_file():
        raise HTTPException(404, "Выгрузка не найдена")
    return FileResponse(path, media_type="text/csv", filename=filename)
