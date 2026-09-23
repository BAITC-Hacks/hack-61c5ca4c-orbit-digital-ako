"""Authenticated assistant integration; isolated accounts and no provider calls."""
import importlib
import json
import sys
from pathlib import Path

import dotenv
import pandas as pd
import pytest
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[1] / "money_graph"
sys.path.insert(0, str(PROJECT))
from mg.auth import AuthStore

server = None
PASSWORD = "Isolated-assistant-password-41!"
BASE = "http://127.0.0.1"
PRIVATE_GIDS = ["100000000000000001", "100000000000000002"]
DEMO_GIDS = ["100000000000000101", "100000000000000102"]


def write_graph_fixture(folder, gids, private=False):
    data, out = folder / "data", folder / "out"
    data.mkdir(parents=True)
    out.mkdir()
    pd.DataFrame([{
        "src": int(gids[0]), "dst": int(gids[1]), "sum_kzt": 10000.0, "n_tx": 1,
    }]).to_parquet(data / "edges.parquet")
    pd.DataFrame([{
        "gid": gid, "role": "peripheral", "evidence": "Synthetic case fact 10000.",
        "priority_score": 0.5, "in_kzt": 10000 * index, "out_kzt": 10000 * (1 - index),
        "depth": index, "is_seed": index == 0,
    } for index, gid in enumerate(gids)]).to_csv(out / "nodes_roles.csv", index=False)
    pd.DataFrame(columns=["gid", "request_type", "weight", "reason"]).to_csv(out / "requests.csv", index=False)
    pd.DataFrame([{"cluster_id": 1, "n_nodes": 2}]).to_csv(out / "clusters.csv", index=False)
    pd.DataFrame([{"gid": gids[0], "rank": 1, "priority_score": 0.5}]).to_csv(out / "top_nodes.csv", index=False)
    pd.DataFrame([{"n_blocked": 0, "tainted_flow_left": 1.0}]).to_csv(out / "resilience.csv", index=False)
    (out / "summary.json").write_text(json.dumps({"nodes": 2, "private_test_case": private}), encoding="utf-8")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    global server
    # Import-time auth initialization must never open the real account store.
    monkeypatch.setenv("MONEYGRAPH_STATE_DIR", str(tmp_path / "initial-state"))
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    server = importlib.import_module("server")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(server.app.state.auth_store, "db_path", store.db_path)
    monkeypatch.setattr(server, "CASES", tmp_path / "cases")
    demo_root = tmp_path / "demo"
    write_graph_fixture(demo_root, DEMO_GIDS)
    (demo_root / "config.json").write_text((PROJECT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(server, "ROOT", demo_root)
    users = {name: store.create_user(name, PASSWORD, role) for name, role in (
        ("alice", "analyst"), ("bob", "analyst"), ("administrator", "admin"),
    )}
    case_id = "a" * 32
    folder = server.CASES / case_id
    write_graph_fixture(folder, PRIVATE_GIDS, private=True)
    (folder / "case.json").write_text(json.dumps({
        "label": "Alice private case", "owner_id": users["alice"]["id"],
    }), encoding="utf-8")
    return {"users": users, "case_id": case_id, "folder": folder}


def sign_in(session, name="alice"):
    response = session.post("/api/auth/login", json={"username": name, "password": PASSWORD},
                            headers={"Origin": BASE})
    assert response.status_code == 200, response.text
    session.headers["x-csrf-token"] = response.json()["csrf_token"]
    return response.json()


@pytest.fixture
def client(environment):
    with TestClient(server.app, base_url=BASE) as session:
        sign_in(session)
        yield session


@pytest.fixture
def gid():
    return DEMO_GIDS[0]


def test_status_does_not_expose_credentials(client, monkeypatch):
    assert client.get("/api/assistant/status").json() == {"configured": False, "model": None}
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-must-never-be-returned")
    response = client.get("/api/assistant/status")
    assert response.status_code == 200
    assert "test-secret" not in response.text


def test_preset_never_calls_provider_even_with_key(client, monkeypatch, gid):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    async def forbidden(*args, **kwargs):
        pytest.fail("Local presets must not call OpenAI")
    monkeypatch.setattr(server, "ask_openai", forbidden)
    response = client.post("/api/cases/demo/assistant", json={"gids": [gid], "mode": "explain", "question": ""})
    assert response.status_code == 200
    assert response.json()["mode"] == "local"
    assert response.json()["evidence"][0]["gid"] == gid


def test_question_without_key_is_explicit_and_core_api_works(client, gid):
    response = client.post("/api/cases/demo/assistant", json={"gids": [gid], "mode": "question", "question": "Почему?"})
    assert response.status_code == 503
    assert client.get("/api/cases/demo/graph").status_code == 200


@pytest.mark.parametrize("payload", [
    {"gids": []}, {"gids": ["1"] * 6}, {"gids": [123]},
    {"gids": ["not-a-gid"]}, {"gids": ["1"], "question": "x" * 1001},
    {"gids": ["1"], "mode": "execute_code"}, {"gids": ["1"], "api_key": "secret"},
])
def test_invalid_request_is_rejected(client, payload):
    assert client.post("/api/cases/demo/assistant", json=payload).status_code == 422


def test_cross_origin_and_unknown_cases_rejected(client, gid):
    payload = {"gids": [gid], "mode": "explain"}
    assert client.post("/api/cases/demo/assistant", json=payload, headers={"Origin": "https://example.com"}).status_code == 403
    assert client.post("/api/cases/unknown/assistant", json=payload).status_code == 404
    assert client.post("/api/cases/demo/assistant", json={"gids": ["-999999"], "mode": "explain"}).status_code == 422


def test_provider_failure_does_not_leak_request_or_key(client, monkeypatch, gid):
    monkeypatch.setattr(server, "assistant_settings", lambda: {"configured": True, "model": "test"})
    async def broken(*args, **kwargs):
        raise RuntimeError("private-provider-error secret-key customer-data")
    monkeypatch.setattr(server, "ask_openai", broken)
    response = client.post("/api/cases/demo/assistant", json={"gids": [gid], "mode": "question", "question": "Почему?"})
    assert response.status_code == 502
    assert "private-provider-error" not in response.text
    assert "secret-key" not in response.text


def test_provider_receives_only_the_requested_private_case(client, environment, monkeypatch):
    monkeypatch.setattr(server, "assistant_settings", lambda: {"configured": True, "model": "test"})
    async def fake(graph, gids, question):
        assert set(graph.nodes) == set(PRIVATE_GIDS)
        assert graph.summary["private_test_case"] is True
        assert gids == [PRIVATE_GIDS[0]]
        assert question == "Почему этот счёт?"
        answer = graph.preset("explain", gids)
        answer["mode"] = "openai"
        return answer
    monkeypatch.setattr(server, "ask_openai", fake)
    response = client.post(f"/api/cases/{environment['case_id']}/assistant", json={
        "gids": [PRIVATE_GIDS[0]], "mode": "question", "question": "Почему этот счёт?",
    })
    assert response.status_code == 200
    assert response.json()["mode"] == "openai"


@pytest.mark.parametrize("mode", ["explain", "question"])
@pytest.mark.parametrize("username", ["bob", "administrator"])
def test_other_users_cannot_read_a_private_case_with_assistant(environment, monkeypatch, mode, username):
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized case must be rejected before graph reads or provider checks")
    monkeypatch.setattr(server, "GraphTools", forbidden)
    monkeypatch.setattr(server, "assistant_settings", forbidden)
    with TestClient(server.app, base_url=BASE) as session:
        sign_in(session, username)
        response = session.post(f"/api/cases/{environment['case_id']}/assistant", json={
            "gids": [PRIVATE_GIDS[0]], "mode": mode, "question": "Show private case",
        })
    assert response.status_code == 404
    assert "Alice" not in response.text
    assert PRIVATE_GIDS[0] not in response.text


def test_anonymous_assistant_requests_are_rejected_before_data_access(environment, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Anonymous requests must be rejected by auth middleware")
    monkeypatch.setattr(server, "GraphTools", forbidden)
    monkeypatch.setattr(server, "assistant_settings", forbidden)
    with TestClient(server.app, base_url=BASE) as session:
        assert session.get("/api/assistant/status").status_code == 401
        for case_id in ("demo", environment["case_id"]):
            for mode in ("explain", "question"):
                response = session.post(f"/api/cases/{case_id}/assistant", json={
                    "gids": [PRIVATE_GIDS[0]], "mode": mode, "question": "Why?",
                })
                assert response.status_code == 401


def test_assistant_posts_require_current_csrf_token(client, gid):
    payload = {"gids": [gid], "mode": "explain"}
    token = client.headers.pop("x-csrf-token")
    assert client.post("/api/cases/demo/assistant", json=payload).status_code == 403
    assert client.post("/api/cases/demo/assistant", json=payload, headers={"x-csrf-token": "wrong"}).status_code == 403
    response = client.post("/api/cases/demo/assistant", json=payload, headers={
        "x-csrf-token": token, "Origin": "http://127.0.0.1:80",
    })
    assert response.status_code == 200


def test_provider_connection_failure_uses_safe_specific_message(client, monkeypatch, gid, caplog):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    secret = "private-provider-message-and-secret-key"
    monkeypatch.setattr(server, "assistant_settings", lambda: {"configured": True, "model": "test"})
    async def broken(*args, **kwargs):
        raise openai.APIConnectionError(message=secret, request=httpx.Request(
            "POST", "https://api.openai.com/v1/responses", headers={"Authorization": secret},
        ))
    monkeypatch.setattr(server, "ask_openai", broken)
    response = client.post("/api/cases/demo/assistant", json={
        "gids": [gid], "mode": "question", "question": "Почему?",
    })
    assert response.status_code == 503
    assert "подключиться к OpenAI" in response.json()["detail"]
    assert secret not in response.text and secret not in caplog.text


def test_provider_authentication_error_does_not_invalidate_local_session(client, monkeypatch, gid):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    monkeypatch.setattr(server, "assistant_settings", lambda: {"configured": True, "model": "test"})
    async def broken(*args, **kwargs):
        response = httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
        raise openai.AuthenticationError("private-upstream-key", response=response, body=None)
    monkeypatch.setattr(server, "ask_openai", broken)
    before = client.get("/api/auth/me").json()
    response = client.post("/api/cases/demo/assistant", json={
        "gids": [gid], "mode": "question", "question": "Почему?",
    })
    assert response.status_code == 502
    assert "API-ключ" in response.json()["detail"]
    assert "private-upstream-key" not in response.text
    after = client.get("/api/auth/me")
    assert after.status_code == 200 and after.json() == before
    assert client.post("/api/cases/demo/assistant", json={"gids": [gid], "mode": "explain"}).status_code == 200
