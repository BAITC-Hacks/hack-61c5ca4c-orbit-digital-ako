"""Local MVP: upload a case, calculate it, inspect graph and download exports."""

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from mg.auth import install_auth
from mg.validation import InputError, validate_data
from mg.assistant import AssistantUnavailable, GraphTools, ask_openai, settings as assistant_settings
from mg.provider_errors import provider_error_details
from mg.viewer import ROLE_COLORS, ROLE_RU
from run import analyze
from workspace_api import install_workspace_routes

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
STATE_ROOT = Path(os.environ.get("MONEYGRAPH_STATE_DIR", str(ROOT / ".local"))).resolve()
CASES = STATE_ROOT / "cases"
EXPORTS = {"nodes_roles.csv", "clusters.csv", "top_nodes.csv", "requests.csv", "resilience.csv", "taint_edges.csv"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
ANALYSIS_SLOT = asyncio.Semaphore(1)
ASSISTANT_SLOT = asyncio.Semaphore(1)
app = FastAPI(title="Граф денег", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.add_middleware(RequestBodyLimitMiddleware, max_body_size=3 * MAX_UPLOAD_BYTES + 1024 * 1024)
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
app.mount("/vendor", StaticFiles(directory=ROOT / "vendor"), name="vendor")


@app.middleware("http")
async def local_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    user = getattr(request.state, "user", None)
    if user:
        response.headers["X-Account-Id"] = user["id"]
    return response


def case_paths(case_id: str, user_id: str):
    # Demo is the explicitly shared hackathon dataset, never an uploaded case.
    if case_id == "demo":
        return ROOT / "data", ROOT / "out", "Данные HackAlem"
    if not re.fullmatch(r"[0-9a-f]{32}", case_id):
        raise HTTPException(404, "Кейс не найден")
    folder = CASES / case_id
    metadata = folder / "case.json"
    if not metadata.is_file():
        raise HTTPException(404, "Кейс не найден")
    try:
        meta = json.loads(metadata.read_text(encoding="utf-8"))
        # Fail closed for legacy cases with no owner, even for administrators.
        if meta.get("owner_id") != user_id:
            raise HTTPException(404, "Кейс не найден")
        label = meta["label"]
    except (ValueError, KeyError):
        raise HTTPException(404, "Кейс повреждён")
    return folder / "data", folder / "out", label


def resolve_case(request: Request, case_id: str):
    return case_paths(case_id, request.state.user["id"])


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/favicon.svg")
def favicon():
    return FileResponse(ROOT / "web" / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/health")
def health():
    return {"status": "ok"}


class AssistantQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(default="", max_length=1000)
    gids: list[Annotated[str, StringConstraints(pattern=r"^-?\d{1,19}$", strict=True)]] = Field(min_length=1, max_length=5)
    mode: Literal["explain", "common_recipients", "paths", "missing_data", "question"] = "explain"


@app.get("/api/assistant/status")
def assistant_status():
    return assistant_settings()


@app.post("/api/cases/{case_id}/assistant")
async def assistant_query(case_id: str, body: AssistantQuery, request: Request):
    # Auth middleware enforces session, same-origin and CSRF before this route.
    # Resolve ownership before reading files or checking provider availability.
    data, out, _ = resolve_case(request, case_id)
    if body.mode == "question" and not assistant_settings()["configured"]:
        raise HTTPException(503, "Вопросы к ИИ пока не подключены. Локальные кнопки работают без ключа.")
    try:
        graph_tools = await asyncio.to_thread(GraphTools, data, out)
        graph_tools.validate_gids(body.gids)
        if body.mode != "question":
            return await asyncio.to_thread(graph_tools.preset, body.mode, body.gids)
        if not body.question.strip():
            raise ValueError("Введите вопрос о выбранных счетах.")
        try:
            await asyncio.wait_for(ASSISTANT_SLOT.acquire(), timeout=0.1)
        except TimeoutError:
            raise HTTPException(429, "Помощник уже отвечает на вопрос. Дождитесь завершения.")
        try:
            return await asyncio.wait_for(ask_openai(graph_tools, body.gids, body.question), timeout=60)
        finally:
            ASSISTANT_SLOT.release()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except AssistantUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, "ИИ не успел ответить. Локальные кнопки по-прежнему доступны.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        # Do not log provider exceptions: they can contain request data or credentials.
        logging.warning("Assistant failed: %s", type(exc).__name__)
        provider_error = provider_error_details(exc)
        if provider_error is not None:
            code, message = provider_error
            raise HTTPException(code, message) from exc
        raise HTTPException(502, "Не удалось получить ответ. Проверьте подключение и настройки API; локальные кнопки доступны.") from exc


@app.get("/api/cases")
def list_cases(request: Request):
    result = [{"id": "demo", "label": "Данные HackAlem", "summary": _summary(ROOT / "out")}]
    if CASES.is_dir():
        for folder in sorted(CASES.iterdir(), reverse=True):
            if (folder / "case.json").is_file() and (folder / "out" / "summary.json").is_file():
                try:
                    meta = json.loads((folder / "case.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(meta, dict) or not isinstance(meta.get("label"), str):
                    continue
                if meta.get("owner_id") != request.state.user["id"]:
                    continue
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
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        cfg["min_tx_kzt"] = min_tx_kzt
        cfg["max_depth"] = max_depth
        (folder / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        async with ANALYSIS_SLOT:
            info = await asyncio.to_thread(validate_data, data, min_tx_kzt, max_depth)
            summary = await asyncio.to_thread(analyze, data, folder / "out", cfg)
        (folder / "case.json").write_text(json.dumps({"label": label, "min_tx_kzt": min_tx_kzt,
            "owner_id": request.state.user["id"]}, ensure_ascii=False), encoding="utf-8")
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
def graph(request: Request, case_id: str):
    data, out, label = resolve_case(request, case_id)
    summary = _summary(out)
    nodes = csv_records(out / "nodes_roles.csv", ("gid",))
    for node in nodes:
        node["role"] = node.get("role_detail") or node["role"]
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
def transactions_for_link(request: Request, case_id: str, src: str = Query(pattern=r"^-?\d{1,19}$"),
                          dst: str = Query(pattern=r"^-?\d{1,19}$"),
                          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    data, _, _ = resolve_case(request, case_id)
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
def export(request: Request, case_id: str, filename: str):
    if filename not in EXPORTS:
        raise HTTPException(404, "Выгрузка не найдена")
    _, out, _ = resolve_case(request, case_id)
    path = out / filename
    if not path.is_file():
        raise HTTPException(404, "Выгрузка не найдена")
    return FileResponse(path, media_type="text/csv", filename=filename)


install_workspace_routes(app, resolve_case, STATE_ROOT / "workspaces")
install_auth(app, STATE_ROOT)
