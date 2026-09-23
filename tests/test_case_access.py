"""Integration: an unguessable case ID never replaces ownership authorization."""
import importlib
import json
import shutil
import sys
from pathlib import Path

import dotenv
import pytest
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[1] / "money_graph"
sys.path.insert(0, str(PROJECT))
from mg.auth import AuthStore

server = None
PASSWORD = "Isolated-test-password-41!"
EXPORT_NAMES = ("nodes_roles.csv", "clusters.csv", "top_nodes.csv", "requests.csv", "resilience.csv", "taint_edges.csv")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    global server
    monkeypatch.setenv("MONEYGRAPH_STATE_DIR", str(tmp_path / "initial-state"))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    server = importlib.import_module("server")
    store = AuthStore(tmp_path / "auth.sqlite3")
    # The middleware closes over the same store object; change only its DB path.
    monkeypatch.setattr(server.app.state.auth_store, "db_path", store.db_path)
    monkeypatch.setattr(server, "CASES", tmp_path / "cases")
    users = {name: store.create_user(name, PASSWORD, role) for name, role in
             (("alice", "analyst"), ("bob", "analyst"), ("administrator", "admin"))}
    case_id = "a" * 32
    folder = server.CASES / case_id
    shutil.copytree(PROJECT / "data", folder / "data")
    (folder / "out").mkdir()
    for name in [*server.EXPORTS, "summary.json"]:
        shutil.copy2(PROJECT / "out" / name, folder / "out" / name)
    (folder / "case.json").write_text(json.dumps({"label": "Alice private case", "owner_id": users["alice"]["id"]}))
    return users, case_id, folder


def client_for(name=None):
    client = TestClient(server.app, base_url="http://localhost")
    if name:
        response = client.post("/api/auth/login", json={"username": name, "password": PASSWORD})
        assert response.status_code == 200
        client.headers["x-csrf-token"] = response.json()["csrf_token"]
    return client


@pytest.mark.parametrize("suffix", ["graph", "transactions?src=101&dst=202",
    *["exports/" + name for name in EXPORT_NAMES],
    "documents", "reports", "audit", "developer"])
def test_case_id_does_not_grant_access(environment, suffix):
    _, case_id, _ = environment
    for name in ("bob", "administrator"):
        with client_for(name) as client:
            response = client.get(f"/api/cases/{case_id}/{suffix}")
            assert response.status_code == 404
            assert "Alice" not in response.text


def test_owner_sees_graph_exports_transactions(environment):
    _, case_id, _ = environment
    with client_for("alice") as client:
        assert client.get(f"/api/cases/{case_id}/graph").status_code == 200
        for name in server.EXPORTS:
            assert client.get(f"/api/cases/{case_id}/exports/{name}").status_code == 200
        assert client.get(f"/api/cases/{case_id}/transactions?src=101&dst=202").status_code == 200
        assert client.get(f"/api/cases/{case_id}/exports/case.json").status_code == 404


def test_case_lists_do_not_disclose_other_users_cases(environment):
    _, case_id, _ = environment
    with client_for("alice") as client:
        assert {case["id"] for case in client.get("/api/cases").json()} == {"demo", case_id}
    with client_for("bob") as client:
        response = client.get("/api/cases")
        assert [case["id"] for case in response.json()] == ["demo"]
        assert "Alice" not in response.text
        assert client.get("/api/cases/demo/graph").status_code == 200


def test_anonymous_and_forged_sessions_cannot_read_even_demo(environment):
    with client_for() as client:
        for path in ("/api/cases", "/api/cases/demo/graph", "/api/cases/demo/exports/top_nodes.csv"):
            assert client.get(path).status_code == 401
        assert client.post("/api/cases").status_code == 401
        client.cookies.set("mg_session", "forged" + "a" * 37, path="/api")
        assert client.get("/api/cases/demo/graph").status_code == 401
        assert client.get("/openapi.json").status_code == 404


def test_unowned_legacy_case_is_not_claimed_by_arbitrary_user(environment):
    _, case_id, folder = environment
    (folder / "case.json").write_text(json.dumps({"label": "Legacy private"}))
    with client_for("administrator") as client:
        assert client.get(f"/api/cases/{case_id}/graph").status_code == 404
        assert [case["id"] for case in client.get("/api/cases").json()] == ["demo"]


def test_invalid_ids_and_oversize_body_are_rejected(environment):
    with client_for("alice") as client:
        for case_id in ("not-an-id", "0" * 32):
            assert client.get(f"/api/cases/{case_id}/graph").status_code == 404
        response = client.post("/api/cases", content=b"x", headers={"content-length": str(200 * 1024 * 1024)})
        assert response.status_code == 413


def test_upload_owner_cannot_be_overridden(environment):
    users, _, _ = environment
    files = {key: (key + ".parquet", (PROJECT / "data" / (key + ".parquet")).read_bytes(), "application/octet-stream")
             for key in ("nodes", "edges", "transactions")}
    with client_for("alice") as client:
        response = client.post("/api/cases", data={"label": "Bound to session", "owner_id": users["bob"]["id"]}, files=files)
        assert response.status_code == 201, response.text
        case_id = response.json()["id"]
    metadata = json.loads((server.CASES / case_id / "case.json").read_text(encoding="utf-8"))
    assert metadata["owner_id"] == users["alice"]["id"]
    with client_for("bob") as client:
        assert client.get(f"/api/cases/{case_id}/graph").status_code == 404
