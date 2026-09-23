"""Private, local case evidence. The host owns authentication, CSRF and case access."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import os
import re
import tempfile
import threading
import unicodedata
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_DOCUMENTS = 50
MAX_DOCUMENT_TOTAL = 20 * 1024 * 1024
MAX_REPORTS = 100
MAX_NODES = 30
MAX_NEIGHBOURS = 5
MAX_LINKS = 1000
MAX_DRAWN_LINKS = 120
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_ROWS = 100_000
MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024
MAX_SOURCES = 8
METHOD = "Лексический поиск без учёта регистра; для точного GID сначала why из списка приоритетов; один лучший фрагмент на источник."
KEY_METRICS = (("priority_score", "Приоритет проверки"), ("in_kzt", "Входящие, KZT"),
               ("out_kzt", "Исходящие, KZT"), ("in_deg", "Отправителей"), ("out_deg", "Получателей"))
DISCLAIMER = (
    "Основания и метрики скопированы из локальных таблиц анализа. Роли и приоритеты — "
    "гипотезы для ручной проверки, не вывод о вине. Неполная выгрузка ограничивает выводы; "
    "отсутствие связи не доказывает отсутствие перевода. При создании этого отчёта внешние AI-запросы не выполняются."
)
_SAFE_CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_OBJECT_ID = re.compile(r"[0-9a-f]{32}\Z")
_GID = re.compile(r"-?\d{1,19}\Z", re.ASCII)
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = set("и в во на с со к по из от до для о об а но или что как кто где почему какой какая какие это ли мне покажи найди основания пожалуйста".split())
# A process lock plus an OS file lock protects read/modify/replace across workers.
_LOCK = threading.RLock()


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _error(status, message):
    raise HTTPException(status, message)


def _title(value, fallback="Документ"):
    value = unicodedata.normalize("NFC", value)
    value = "".join(c for c in value if not unicodedata.category(c).startswith("C"))
    value = re.sub(r"[<>\"'`/\\:|?*]", " ", value)
    return " ".join(value.split())[:120].strip(" .") or fallback


def _comparison_path(path: Path):
    resolved = path.resolve()
    if os.name == "nt":
        value = str(resolved)
        # On Windows realpath can retain \\?\ when a directory is created
        # between its filesystem probes. Normalize only ordinary DOS/UNC
        # aliases for comparison, AFTER resolving links; retain other namespaces.
        if value[:8].upper() == "\\\\?\\UNC\\":
            return Path("\\\\" + value[8:])
        if value.startswith("\\\\?\\") and re.match(r"[A-Za-z]:\\", value[4:]):
            return Path(value[4:])
    return resolved


def _inside(root: Path, *parts):
    target = root.joinpath(*parts)
    # Refuse symlinks/junctions, even if they point to another valid user's folder.
    current = root
    for part in parts:
        current /= part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            _error(404, "Ресурс не найден")
    if not _comparison_path(target).is_relative_to(_comparison_path(root)):
        _error(404, "Ресурс не найден")
    return target


def _context(request, case_id, resolve_case, root):
    # This MUST be the first operation of EVERY endpoint, including error paths.
    data, out, label = resolve_case(request, case_id)
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict):
        _error(401, "Требуется вход")
    try:
        user_id = str(uuid.UUID(str(user["id"])))
    except (KeyError, ValueError, TypeError, AttributeError):
        _error(401, "Некорректный пользователь")
    if not _SAFE_CASE.fullmatch(case_id) or case_id.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}:
        _error(404, "Кейс не найден")
    folder = _inside(root, user_id, case_id)
    return {
        "data": Path(data), "out": Path(out), "label": str(label), "case_id": case_id,
        "folder": folder, "root": root, "role": user.get("role"),
        "author": {"id": user_id, "username": str(user.get("username", ""))[:120]},
    }


@contextmanager
def _state(context):
    folder, root = context["folder"], context["root"]
    with _LOCK:
        _inside(root, *folder.relative_to(root).parts)
        folder.mkdir(parents=True, exist_ok=True)
        lock_path = _inside(root, *folder.relative_to(root).parts, ".lock")
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                except OSError:
                    _error(503, "Рабочая область занята; повторите запрос")
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                path = _inside(root, *folder.relative_to(root).parts, "state.json")
                state = {"schema_version": 1, "documents": [], "reports": [], "audit": []}
                if path.exists():
                    try:
                        if path.stat().st_size > MAX_STATE_BYTES:
                            _error(503, "Рабочая область превышает допустимый размер")
                        state = json.loads(path.read_text(encoding="utf-8"))
                        if state["schema_version"] != 1 or any(not isinstance(state[k], list) for k in ("documents", "reports", "audit")):
                            raise ValueError("schema")
                    except (OSError, ValueError, KeyError, TypeError):
                        _error(503, "Не удалось прочитать рабочую область")
                yield state, path
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _save(path, state):
    content = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(content) > MAX_STATE_BYTES:
        _error(409, "Рабочая область заполнена")
    fd, temporary = tempfile.mkstemp(prefix=".workspace-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _audit(state, context, action, item, version=None):
    if len(state["audit"]) >= 5000:
        _error(409, "Достигнут лимит истории рабочей области")
    state["audit"].append({
        "id": uuid.uuid4().hex, "sequence": len(state["audit"]) + 1, "action": action,
        "created_at": _utc(), "author": context["author"], "resource_id": item["id"],
        "title": item["title"], "version": version,
    })


def _find(items, identifier):
    if not _OBJECT_ID.fullmatch(identifier):
        _error(404, "Ресурс не найден")
    for item in items:
        if item["id"] == identifier:
            return item
    _error(404, "Ресурс не найден")


def _document_meta(doc):
    return {key: doc[key] for key in ("id", "title", "created_at")}


def _report_meta(report):
    return {key: report[key] for key in ("id", "title", "version", "created_at", "selected_gids")}


async def _body(request, limit):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            _error(413, "Превышен допустимый размер запроса")
        chunks.append(chunk)
    return b"".join(chunks)


async def _json_body(request, fields):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        _error(415, "Ожидается application/json")
    try:
        value = json.loads((await _body(request, MAX_JSON_BYTES)).decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        _error(422, "Некорректный JSON в UTF-8")
    if not isinstance(value, dict) or set(value) - fields:
        _error(422, "Некорректные поля запроса")
    return value


def _text_field(body, key, limit, default=None):
    value = body.get(key, default)
    if not isinstance(value, str) or len(value) > limit or any(unicodedata.category(c) == "Cs" for c in value) or "\x00" in value:
        _error(422, f"Поле {key}: требуется строка длиной до {limit} символов")
    return value


def _source_file(path):
    if path.stat().st_size > MAX_SOURCE_BYTES:
        _error(413, "Таблица кейса слишком велика для локальной рабочей области")


def _csv_rows(path, required=False):
    if not path.is_file():
        if required:
            _error(409, "Таблицы анализа ещё не готовы")
        return []
    _source_file(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(reader.fieldnames) > 128:
                raise ValueError("columns")
            result = []
            for row in reader:
                if len(result) >= MAX_SOURCE_ROWS:
                    _error(413, "Превышен лимит строк таблицы")
                if None in row or any(v is None or len(v) > 8192 for v in row.values()):
                    raise ValueError("row")
                result.append(row)
            return result
    except (ValueError, UnicodeError, csv.Error):
        _error(409, "Некорректная таблица анализа")


def _node_tables(out):
    nodes = _csv_rows(out / "nodes_roles.csv", required=True)
    top = _csv_rows(out / "top_nodes.csv")
    for rows in (nodes, top):
        if any(not _GID.fullmatch(row.get("gid", "")) for row in rows) or len({row["gid"] for row in rows}) != len(rows):
            _error(409, "Некорректные GID в таблице анализа")
    return {row["gid"]: row for row in nodes}, {row["gid"]: row for row in top}


def _edges(data):
    # CSV is useful for small local fixtures; production analysis uses parquet.
    if (data / "edges.parquet").is_file():
        import pyarrow.parquet as pq
        path = data / "edges.parquet"
        _source_file(path)
        try:
            table = pq.ParquetFile(path)
            if table.metadata.num_rows > MAX_SOURCE_ROWS:
                _error(413, "Превышен лимит связей кейса")
            if not {"src", "dst", "sum_kzt", "n_tx"}.issubset(table.schema.names):
                raise ValueError("columns")
            rows = [{k: str(v) for k, v in row.items()} for batch in table.iter_batches(columns=["src", "dst", "sum_kzt", "n_tx"]) for row in batch.to_pylist()]
        except (ValueError, OSError):
            _error(409, "Некорректная таблица связей")
        source = "edges.parquet"
    elif (data / "edges.csv").is_file():
        rows, source = _csv_rows(data / "edges.csv"), "edges.csv"
    else:
        return [], None
    if any(not {"src", "dst", "sum_kzt", "n_tx"}.issubset(row) or not _GID.fullmatch(row["src"]) or not _GID.fullmatch(row["dst"]) for row in rows):
        _error(409, "Некорректные GID в таблице связей")
    return rows, source


def _amount(row):
    try:
        value = Decimal(row.get("sum_kzt", "0"))
        return value if value.is_finite() else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _role_description(row):
    role = row.get("role_detail") or row.get("role", "")
    truncated = str(row.get("is_truncated", "")).strip().lower() in {"true", "1"}
    if role == "truncated" or truncated:
        return "Обрезан на границе выгрузки: дальнейшее движение средств неизвестно"
    return {"consolidator": "Консолидатор", "transit": "Транзитный узел", "distributor": "Распределитель",
            "terminal": "Конечный получатель в наблюдаемой выгрузке", "coordinator": "Координатор",
            "peripheral": "Периферийный узел"}.get(role, role or "Роль не указана")


def _snapshot(context, title, selected, notes):
    nodes, top = _node_tables(context["out"])
    if any(gid not in nodes for gid in selected):
        _error(422, "Выбранный GID отсутствует в текущем кейсе")
    edges, edge_source = _edges(context["data"])
    chosen = set(selected)
    adjacent = [row for row in edges if row["src"] in chosen or row["dst"] in chosen]
    adjacent.sort(key=lambda row: (not (row["src"] in chosen and row["dst"] in chosen), -_amount(row), row["src"], row["dst"]))
    neighbours = []
    for row in adjacent:
        for gid in (row["src"], row["dst"]):
            if gid in nodes and gid not in chosen and gid not in neighbours and len(neighbours) < min(MAX_NEIGHBOURS, MAX_NODES - len(selected)):
                neighbours.append(gid)
    included = selected + neighbours
    included_set = set(included)
    relevant = [row for row in adjacent if row["src"] in included_set and row["dst"] in included_set]
    links = relevant[:MAX_LINKS]
    warnings = []
    if edge_source is None:
        warnings.append("Таблица связей отсутствует; связи не восстановлены и не выдуманы.")
    if len(adjacent) > len(links):
        warnings.append("Показана ограниченная часть связей выбранных узлов; остальные связи не включены.")
    if len(links) > MAX_DRAWN_LINKS:
        warnings.append("На схеме показаны первые 120 связей; полный список включённых связей приведён в таблице.")
    return {
        "schema_version": 1, "id": uuid.uuid4().hex, "title": title, "version": 0,
        "case_id": context["case_id"], "label": context["label"], "created_at": _utc(),
        "author": context["author"], "selected_gids": selected, "notes": notes,
        "method": {"name": "Снимок локальных оснований", "disclaimer": DISCLAIMER, "llm_connected": False},
        "nodes": [{"gid": gid, "selected": gid in chosen, "role_description": _role_description(nodes[gid]), "metrics": nodes[gid], "top": top.get(gid)} for gid in included],
        "network": {"nodes": included, "links": links, "source": edge_source,
                    "adjacent_links_total": len(adjacent), "included_links": len(links),
                    "omitted_links": len(adjacent) - len(links), "drawn_links": min(len(links), MAX_DRAWN_LINKS)},
        "sources": ["nodes_roles.csv", *(["top_nodes.csv"] if top else []), *([edge_source] if edge_source else [])],
        "warnings": warnings,
    }


def _svg(report):
    nodes = report["nodes"]
    positions = {}
    for i, node in enumerate(nodes):
        angle = 2 * math.pi * i / len(nodes) - math.pi / 2
        positions[node["gid"]] = (480 + 340 * math.cos(angle), 420 + 335 * math.sin(angle))
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 840" role="img" aria-label="Направленные связи узлов"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#68788a"/></marker></defs>']
    for link in report["network"]["links"][:MAX_DRAWN_LINKS]:
        x1, y1 = positions[link["src"]]
        x2, y2 = positions[link["dst"]]
        evidence = html.escape(f'{link["src"]} → {link["dst"]}: {link["sum_kzt"]} KZT; операций: {link["n_tx"]}')
        if link["src"] == link["dst"]:
            parts.append(f'<path d="M {x1-9:.1f},{y1-8:.1f} C {x1-65:.1f},{y1-80:.1f} {x1+65:.1f},{y1-80:.1f} {x1+9:.1f},{y1-8:.1f}" fill="none" stroke="#68788a" marker-end="url(#arrow)"><title>{evidence}</title></path>')
        else:
            length = math.hypot(x2 - x1, y2 - y1)
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            # A slight bend separates reciprocal directed links.
            cx, cy = (x1 + x2) / 2 - uy * 15, (y1 + y2) / 2 + ux * 15
            parts.append(f'<path d="M {x1+ux*25:.1f},{y1+uy*25:.1f} Q {cx:.1f},{cy:.1f} {x2-ux*28:.1f},{y2-uy*28:.1f}" fill="none" stroke="#68788a" stroke-width="2" stroke-opacity=".8" marker-end="url(#arrow)"><title>{evidence}</title></path>')
    for number, node in enumerate(nodes, 1):
        x, y = positions[node["gid"]]
        color = "#135c99" if node["selected"] else "#697887"
        gid = html.escape(node["gid"])
        parts.append(f'<g><title>GID {gid}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="25" fill="{color}"/><text x="{x:.1f}" y="{y+7:.1f}" text-anchor="middle" fill="white" font-size="22">{number}</text><text x="{x:.1f}" y="{y+49:.1f}" text-anchor="middle" font-size="19">{gid}</text></g>')
    return "".join(parts) + "</svg>"


def _html_report(report):
    esc = lambda value: html.escape(str(value), quote=True)
    selected, neighbours = [], []
    for number, node in enumerate(report["nodes"], 1):
        metrics, top = node["metrics"], node["top"] or {}
        role = node.get("role_description", _role_description(metrics))
        why = top.get("why") or metrics.get("evidence") or "Основания в таблице не указаны."
        if node["selected"]:
            headers = "".join(f"<th>{esc(label)}</th>" for _, label in KEY_METRICS)
            values = "".join(f'<td>{esc(metrics.get(key) or top.get(key) or "нет данных")}</td>' for key, _ in KEY_METRICS)
            observation = metrics.get("evidence", "")
            observation_html = f'<p><strong>Наблюдения:</strong> {esc(observation)}</p>' if observation and observation != why else ""
            selected.append(f'<section class="client"><h2>{number}. Выбранный клиент · GID {esc(node["gid"])}</h2><p class="role">{esc(role)}</p><p><strong>Основания для проверки:</strong> {esc(why)}</p>{observation_html}<table class="metrics"><thead><tr>{headers}</tr></thead><tbody><tr>{values}</tr></tbody></table></section>')
        else:
            excerpt = why[:240] + ("…" if len(why) > 240 else "")
            neighbours.append(f'<tr><td>{number}. {esc(node["gid"])}</td><td>{esc(role)}</td><td>{esc(metrics.get("priority_score", "нет данных"))}</td><td>{esc(excerpt)}</td></tr>')
    neighbour_html = ('<h2>Ближайшее окружение</h2><table class="neighbours"><thead><tr><th>GID</th><th>Роль / граница данных</th><th>Приоритет</th><th>Краткое основание</th></tr></thead><tbody>' + "".join(neighbours) + "</tbody></table>") if neighbours else ""
    links = "".join(f'<tr><td>{esc(link["src"])}</td><td>{esc(link["dst"])}</td><td>{esc(link["sum_kzt"])}</td><td>{esc(link["n_tx"])}</td></tr>' for link in report["network"]["links"])
    warnings = "".join(f"<p>{esc(warning)}</p>" for warning in report["warnings"])
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>{esc(report["title"])}</title><style>
body{{font:14px/1.45 system-ui,sans-serif;color:#172b3b;max-width:1100px;margin:28px auto;padding:0 24px}}h1,h2{{line-height:1.25}}h2{{font-size:19px;margin-top:24px}}p{{margin:8px 0}}table{{border-collapse:collapse;width:100%;margin:12px 0;table-layout:fixed}}th,td{{border:1px solid #bbc6cf;padding:6px;text-align:left;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}}th{{background:#f2f6f9}}.metrics th{{font-size:12px}}svg{{display:block;width:100%;max-height:440px}}.notes{{white-space:pre-wrap;overflow-wrap:anywhere}}.notice{{background:#eef4f8;padding:10px;font-size:12px}}.meta,.footnote{{font-size:12px;color:#506070}}.role{{color:#135c99}}.neighbours th:nth-child(3){{width:12%}}.neighbours th:nth-child(4){{width:36%}}@media print{{body{{margin:0;padding:0;font-size:9pt}}h1{{font-size:19pt}}h2{{font-size:12pt;break-after:avoid;margin-top:16px}}p{{orphans:3;widows:3}}tr{{break-inside:avoid}}svg{{max-height:95mm;break-inside:avoid}}.print-help{{display:none}}.notice,.meta,.footnote,.metrics th{{font-size:8pt}}}}@page{{size:A4;margin:14mm}}
</style></head><body><h1>{esc(report["title"])}</h1><p>Кейс: {esc(report["label"])} · Версия {report["version"]} · UTC {esc(report["created_at"])}</p><p class="meta">Автор: {esc(report["author"]["username"])} ({esc(report["author"]["id"])}) · Отчёт {esc(report["id"])}</p><p class="notice">{esc(report["method"]["disclaimer"])}</p><h2>Заметки аналитика</h2><div class="notes">{esc(report["notes"])}</div>{"".join(selected)}{neighbour_html}<h2>Направленная схема</h2>{warnings}{_svg(report)}<p class="footnote">Синие узлы выбраны; серые — окружение. Номера соответствуют клиентам и таблице соседей.</p><h2>Основания связей — {esc(report["network"]["source"] or "источник отсутствует")}</h2><table><thead><tr><th>Отправитель GID</th><th>Получатель GID</th><th>Сумма KZT</th><th>Операций</th></tr></thead><tbody>{links}</tbody></table><p class="footnote">Основания: nodes_roles.csv / top_nodes.csv. Полные исходные поля и метрики сохранены в JSON-снимке этого отчёта. Суммы приведены без округления.</p><p class="print-help">Печать или сохранение в PDF: Ctrl+P в браузере.</p></body></html>'''


def _md_escape(value):
    value = html.escape(str(value), quote=True)
    value = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)
    return value.replace("\r", " ").replace("\n", " ")


def _markdown_report(report):
    esc = _md_escape
    lines = [f'# {esc(report["title"])}', "", f'Кейс: {esc(report["label"])}', f'Версия: {report["version"]}; UTC: {esc(report["created_at"])}', f'Автор: {esc(report["author"]["username"])} ({esc(report["author"]["id"])})', "", esc(report["method"]["disclaimer"]), "", "## Заметки аналитика", "", esc(report["notes"]), "", "## Связи", "", "| Отправитель GID | Получатель GID | Сумма KZT | Операций |", "| --- | --- | --- | --- |"]
    for link in report["network"]["links"]:
        lines.append("| " + " | ".join(esc(link[key]) for key in ("src", "dst", "sum_kzt", "n_tx")) + " |")
    for warning in report["warnings"]:
        lines.extend(["", esc(warning)])
    for node in report["nodes"]:
        lines.extend(["", f'## GID {esc(node["gid"])} — {"выбран" if node["selected"] else "сосед"}', "", esc(node.get("role_description", _role_description(node["metrics"])))])
        for source, row in (("nodes_roles.csv", node["metrics"]), ("top_nodes.csv", node["top"] or {})):
            lines.extend(["", f"### {source}", "", "| Поле | Значение |", "| --- | --- |"])
            lines.extend(f"| {esc(key)} | {esc(value)} |" for key, value in row.items())
    return "\n".join(lines) + "\n"


def _tokens(text):
    return _WORDS.findall(unicodedata.normalize("NFC", text).casefold().replace("ё", "е"))


def _evidence_text(gid, row):
    lines = [f"GID: {gid}", f"Роль: {_role_description(row)}",
             f'Приоритет проверки: {row.get("priority_score", "не указан")}',
             f'Основания: {row.get("why") or row.get("evidence") or "не указаны"}']
    lines.extend(f"{label}: {row[key]}" for key, label in KEY_METRICS if key != "priority_score" and row.get(key))
    return "\n".join(lines)


def _retrieve(context, question):
    nodes, top = _node_tables(context["out"])
    with _state(context) as (state, _):
        documents = list(state["documents"])
    terms = sorted(set(_tokens(question)) - _STOP)[:32]
    exact_gids = set(re.findall(r"(?<!\w)-?\d{1,19}(?!\w)", question))
    scored = []
    chunks_searched = matches = 0

    def add(identifier, title, text, kind, gid=None):
        nonlocal chunks_searched, matches
        # Bounded, overlapping windows keep excerpts literal and deterministic.
        best = None
        for index, start in enumerate(range(0, max(1, len(text)), 600)):
            source = {"id": f"{identifier}:{index + 1}", "title": title,
                      "excerpt": text[start:start + 800], "kind": kind}
            chunks_searched += 1
            words = Counter(_tokens(title + " " + source["excerpt"]))
            frequencies = [words[term] for term in terms]
            matched = sum(count > 0 for count in frequencies)
            if matched:
                score = matched * 100 + sum(min(count, 10) for count in frequencies)
                if best is None or score > best[0]:
                    best = (score, source)
            if start + 800 >= len(text):
                break
        if best:
            matches += 1
            exact_priority = (2 if kind == "top_nodes" else 1) if gid in exact_gids else 0
            scored.append((exact_priority, *best))
            scored.sort(key=lambda item: (-item[0], -item[1], item[2]["id"]))
            del scored[MAX_SOURCES:]

    for gid, row in top.items():
        add(f"top:{gid}", f"Приоритетная проверка · GID {gid}", _evidence_text(gid, row), "top_nodes", gid)
    for gid, row in nodes.items():
        add(f"node:{gid}", f"Наблюдения по клиенту · GID {gid}", _evidence_text(gid, row), "node", gid)
    for doc in sorted(documents, key=lambda item: item["id"]):
        add(f'document:{doc["id"]}', doc["title"], doc["text"], "document")
    sources = [item for _, _, item in scored]
    preamble = "Локальный поиск по документам и метрикам. Ответ НЕ сгенерирован LLM."
    if "rag" in terms or "раг" in terms:
        preamble += " Этот поиск возвращает фрагменты источников без обращения к ИИ."
    if sources:
        answer = preamble + f"\nНайденные основания: {len(sources)} из {matches} источников. Фрагменты приведены ниже."
    else:
        answer = preamble + "\n\nСовпадений в доступных таблицах текущего кейса и ваших документах не найдено. Это не доказывает отсутствие факта. Уточните GID или слова из источника."
    return {"answer": answer, "mode": "local-evidence", "sources": sources,
            "diagnostics": {"method": METHOD, "llm_connected": False, "external_requests": False,
                            "query_terms": terms, "documents_searched": len(documents),
                            "nodes_searched": len(nodes), "top_rows_searched": len(top),
                            "chunks_searched": chunks_searched, "matches": matches, "returned": len(sources),
                            "max_sources": MAX_SOURCES, "truncated": matches > MAX_SOURCES}}


def _report_response(report, format_, disposition="attachment"):
    if format_ not in {"html", "md", "json"}:
        _error(422, "Формат должен быть html, md или json")
    if format_ == "html":
        content, media = _html_report(report), "text/html"
    elif format_ == "md":
        content, media = _markdown_report(report), "text/markdown"
    else:
        content, media = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2), "application/json"
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'{disposition}; filename="report-{report["id"]}-v{report["version"]}.{format_}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    })


def install_workspace_routes(app, resolve_case, storage_root: Path):
    """Register private routes; resolve_case(request, case_id) is called first.

    The resolver is synchronous and returns (data_path, out_path, label), or raises
    HTTPException. Authentication/CSRF are deliberately supplied by the host app.
    """
    root = Path(storage_root).resolve()
    prefix = "/api/cases/{case_id}"

    @app.get(prefix + "/documents")
    def list_documents(request: Request, case_id: str):
        context = _context(request, case_id, resolve_case, root)
        with _state(context) as (state, _):
            return [_document_meta(doc) for doc in state["documents"]]

    @app.post(prefix + "/documents", status_code=201)
    async def upload_document(request: Request, case_id: str):
        context = _context(request, case_id, resolve_case, root)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
            _error(415, "Ожидается multipart/form-data")
        # Bound the complete body BEFORE the multipart parser can spool a file.
        body = await _body(request, MAX_DOCUMENT_BYTES + 64 * 1024)

        async def stream():
            yield body

        try:
            form = await MultiPartParser(request.headers, stream(), max_files=1, max_fields=1).parse()
        except (MultiPartException, ValueError, UnicodeError):
            _error(422, "Некорректная форма загрузки")
        try:
            if set(form) - {"file", "title"} or len(form.getlist("file")) != 1:
                _error(422, "Требуется один файл в поле file и необязательный title")
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                _error(422, "Требуется текстовый файл")
            basename = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
            suffix = Path(basename).suffix.lower()
            if suffix not in {".txt", ".md"}:
                _error(422, "Поддерживаются только UTF-8 файлы .txt и .md")
            raw = await upload.read(MAX_DOCUMENT_BYTES + 1)
            if len(raw) > MAX_DOCUMENT_BYTES:
                _error(413, "Файл превышает 2 МБ")
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                _error(422, "Файл должен быть в UTF-8")
            if not content.strip() or any(unicodedata.category(c) == "Cc" and c not in "\t\r\n" for c in content):
                _error(422, "Файл пуст или содержит двоичные данные")
            title = _title(_text_field({"title": form.get("title", Path(basename).stem)}, "title", 240))
            doc = {"id": uuid.uuid4().hex, "title": title, "kind": "document", "format": suffix[1:],
                   "size_bytes": len(raw), "created_at": _utc(), "author": context["author"],
                   "sha256": hashlib.sha256(raw).hexdigest(), "text": content}

            def persist():
                with _state(context) as (state, path):
                    if len(state["documents"]) >= MAX_DOCUMENTS or sum(item["size_bytes"] for item in state["documents"]) + len(raw) > MAX_DOCUMENT_TOTAL:
                        _error(409, "Достигнут лимит документов рабочей области")
                    state["documents"].append(doc)
                    _audit(state, context, "document.created", doc)
                    _save(path, state)
                return _document_meta(doc)

            return await run_in_threadpool(persist)
        finally:
            await form.close()

    @app.delete(prefix + "/documents/{doc_id}")
    def delete_document(request: Request, case_id: str, doc_id: str):
        context = _context(request, case_id, resolve_case, root)
        with _state(context) as (state, path):
            doc = _find(state["documents"], doc_id)
            state["documents"].remove(doc)
            _audit(state, context, "document.deleted", doc)
            _save(path, state)
        return {"id": doc_id, "deleted": True}

    @app.get(prefix + "/reports")
    def list_reports(request: Request, case_id: str):
        context = _context(request, case_id, resolve_case, root)
        with _state(context) as (state, _):
            return [_report_meta(report) for report in state["reports"]]

    @app.post(prefix + "/reports", status_code=201)
    async def create_report(request: Request, case_id: str):
        context = _context(request, case_id, resolve_case, root)
        body = await _json_body(request, {"title", "selected_gids", "notes"})
        title = _text_field(body, "title", 120)
        if not title.strip():
            _error(422, "Введите название отчёта")
        notes = _text_field(body, "notes", 5000, "")
        selected = body.get("selected_gids")
        if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_NODES or any(not isinstance(gid, str) or not _GID.fullmatch(gid) for gid in selected):
            _error(422, "selected_gids: требуется от 1 до 30 строковых GID")
        if len(set(selected)) != len(selected):
            _error(422, "GID не должны повторяться")

        def persist():
            report = _snapshot(context, _title(title, "Отчёт"), selected, notes)
            with _state(context) as (state, path):
                if len(state["reports"]) >= MAX_REPORTS:
                    _error(409, "Достигнут лимит отчётов рабочей области")
                report["version"] = len(state["reports"]) + 1
                state["reports"].append(report)
                _audit(state, context, "report.created", report, report["version"])
                _save(path, state)
            return _report_meta(report)

        return await run_in_threadpool(persist)

    @app.get(prefix + "/reports/{report_id}/download")
    def download_report(request: Request, case_id: str, report_id: str):
        context = _context(request, case_id, resolve_case, root)
        with _state(context) as (state, _):
            report = _find(state["reports"], report_id)
        return _report_response(report, request.query_params.get("format", "html"))

    @app.get(prefix + "/reports/{report_id}/view")
    def view_report(request: Request, case_id: str, report_id: str):
        context = _context(request, case_id, resolve_case, root)
        with _state(context) as (state, _):
            report = _find(state["reports"], report_id)
        return _report_response(report, "html", disposition="inline")

    @app.get(prefix + "/audit")
    def audit(request: Request, case_id: str):
        context = _context(request, case_id, resolve_case, root)
        with _state(context) as (state, _):
            return list(state["audit"])

    @app.post(prefix + "/ask")
    async def ask(request: Request, case_id: str):
        context = _context(request, case_id, resolve_case, root)
        body = await _json_body(request, {"question"})
        question = _text_field(body, "question", 2000)
        if not question.strip():
            _error(422, "Введите вопрос или слова для поиска")
        return await run_in_threadpool(_retrieve, context, question)

    @app.get(prefix + "/developer")
    def developer(request: Request, case_id: str):
        context = _context(request, case_id, resolve_case, root)
        if context["role"] != "admin":
            _error(403, "Раздел доступен только администратору")
        return {"mode": "local-evidence", "method": METHOD, "llm_connected": False, "external_requests": False,
                "sources": ["top_nodes.csv", "nodes_roles.csv", "Личные документы текущего кейса"],
                "limits": {"document_bytes": MAX_DOCUMENT_BYTES, "documents": MAX_DOCUMENTS,
                           "document_total_bytes": MAX_DOCUMENT_TOTAL, "reports": MAX_REPORTS,
                           "report_nodes": MAX_NODES, "neighbours": MAX_NEIGHBOURS,
                           "report_links": MAX_LINKS, "drawn_links": MAX_DRAWN_LINKS, "retrieval_sources": MAX_SOURCES},
                "disclaimer": DISCLAIMER}
