"""Isolated security regressions; never open the application's real account DB."""

import hashlib
import re
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[1] / "money_graph"
sys.path.insert(0, str(PROJECT))

import mg.auth as auth
import manage_users

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a different strong password"
BASE = "http://testserver"


@pytest.fixture
def setup(tmp_path):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    store = auth.install_auth(app, tmp_path)
    admin = store.create_user("Admin", PASSWORD, "admin")
    analyst = store.create_user("Analyst", PASSWORD)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.api_route("/api/private", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def private(request: Request):
        return {"user": request.state.user}

    @app.get("/public")
    def public():
        return {"public": True}

    with TestClient(app) as client:
        yield client, store, admin, analyst


def login(client, username="admin", password=PASSWORD):
    response = client.post("/api/auth/login", json={"username": username, "password": password},
                           headers={"Origin": BASE})
    assert response.status_code == 200, response.text
    return response.json()


def csrf_headers(session):
    return {"x-csrf-token": session["csrf_token"], "Origin": BASE}


def test_gate_covers_every_api_and_sets_safe_identity(setup):
    client, store, admin, _ = setup
    assert client.get("/api/health").status_code == 200
    assert client.get("/public").status_code == 200
    for path in ("/api", "/api/private", "/api/unknown", "/api/auth/me", "/api/admin/users",
                 "/api/auth/bootstrap", "/api/auth/signup", "/api/auth/login/"):
        assert client.get(path).status_code == 401
    session = login(client, "ADMIN")
    assert session["user"] == admin
    assert re.fullmatch(r"[0-9a-f]{32}", admin["id"])
    assert client.app.state.auth_store is store
    assert client.get("/api/auth/me").json() == session
    assert client.get("/api/private").json()["user"] == admin
    assert client.get("/api/private").headers["cache-control"] == "no-store"
    assert client.get("/api/unknown").status_code == 404


def test_hashes_and_cookie_storage_are_private(setup):
    client, store, _, _ = setup
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/api" in cookie and f"Max-Age={auth.SESSION_SECONDS}" in cookie
    raw = client.cookies.get(auth.COOKIE_NAME)
    with sqlite3.connect(store.db_path) as db:
        hashes = [row[0] for row in db.execute("SELECT password_hash FROM users")]
        saved_token = db.execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert len(set(hashes)) == 2
    assert all(value.startswith("scrypt$16384$8$1$") for value in hashes)
    assert all(PASSWORD not in value and auth.verify_password(PASSWORD, value) for value in hashes)
    assert saved_token == hashlib.sha256(raw.encode()).hexdigest()
    assert saved_token != raw
    assert raw.encode() not in store.db_path.read_bytes()
    assert PASSWORD.encode() not in store.db_path.read_bytes()
    assert "password" not in response.text.replace("must_change_password", "")


def test_https_cookie_is_secure(setup):
    client, _, _, _ = setup
    with TestClient(client.app, base_url="https://testserver") as secure:
        response = secure.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                               headers={"Origin": "https://testserver"})
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        assert secure.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_csrf_on_all_unsafe_authenticated_routes(setup, method):
    client, _, _, _ = setup
    session = login(client)
    assert client.request(method, "/api/private").status_code == 403
    assert client.request(method, "/api/private", headers={"x-csrf-token": "wrong"}).status_code == 403
    assert client.request(method, "/api/private", headers=csrf_headers(session)).status_code == 200


@pytest.mark.parametrize("origin", ["https://evil.example", "http://testserver.evil.example", "null",
                                   "https://testserver", "http://testserver:81", "http://testserver/",
                                   "http://testserver@evil.example", "http://testserver:bad"])
def test_login_and_authenticated_writes_reject_cross_origins(setup, origin):
    client, store, _, _ = setup
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                           headers={"Origin": origin})
    assert response.status_code == 403
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    session = login(client)
    assert client.post("/api/private", headers={"Origin": origin, "x-csrf-token": session["csrf_token"]}).status_code == 403


def test_origin_default_port_and_fetch_metadata(setup):
    client, _, _, _ = setup
    assert client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                       headers={"Origin": "http://testserver:80"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                       headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                       headers=[("Origin", BASE), ("Origin", "http://evil.example")]).status_code == 403


def test_logout_revokes_replay_and_requires_csrf(setup):
    client, store, _, _ = setup
    session = login(client)
    token = client.cookies.get(auth.COOKIE_NAME)
    assert client.post("/api/auth/logout").status_code == 403
    response = client.post("/api/auth/logout", headers=csrf_headers(session))
    assert response.status_code == 204 and response.content == b""
    assert client.cookies.get(auth.COOKIE_NAME) is None
    assert store.session(token) is None
    client.cookies.set(auth.COOKIE_NAME, token)
    assert client.get("/api/auth/me").status_code == 401


def test_expired_and_forged_sessions_are_rejected(setup):
    client, store, _, _ = setup
    login(client)
    with sqlite3.connect(store.db_path) as db:
        db.execute("UPDATE sessions SET expires_at = 0")
    assert client.get("/api/private").status_code == 401
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, "x" * 43)
    assert client.get("/api/private").status_code == 401
    assert store.session("malformed") is None


def test_password_change_revokes_all_previous_sessions(setup):
    client, store, _, _ = setup
    session = login(client)
    first = client.cookies.get(auth.COOKIE_NAME)
    _, second = store.login("admin", PASSWORD, "second-client")
    assert client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}).status_code == 403
    assert client.post("/api/auth/password", json={"current_password": "wrong", "new_password": NEW_PASSWORD},
                       headers=csrf_headers(session)).status_code == 400
    response = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                           headers=csrf_headers(session))
    assert response.status_code == 200
    assert response.json() == {"detail": "Password changed. Sign in again."}
    assert store.session(first) is None and store.session(second) is None
    assert client.cookies.get(auth.COOKIE_NAME) is None
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 401
    changed = login(client, password=NEW_PASSWORD)
    assert changed["user"]["must_change_password"] is False
    assert changed["csrf_token"] != session["csrf_token"]


def test_admin_create_requires_role_and_password_change(setup):
    client, store, _, _ = setup
    session = login(client)
    response = client.post("/api/admin/users", json={"username": "New.Analyst", "role": "analyst"},
                           headers=csrf_headers(session))
    assert response.status_code == 201
    created = response.json()
    assert created["user"]["must_change_password"] is True
    assert created["user"]["username"] == "new.analyst"
    records = client.get("/api/admin/users").json()
    assert len(records) == 3
    assert all(set(record) == {"id", "username", "role", "must_change_password", "disabled", "created_at"} for record in records)
    assert client.post("/api/admin/users", json={"username": "new.analyst", "role": "admin"},
                       headers=csrf_headers(session)).status_code == 409
    for data in ({"username": "bad", "role": "owner"}, {"username": "../bad", "role": "admin"},
                 {"username": "bad", "role": "admin", "must_change_password": "false"}):
        assert client.post("/api/admin/users", json=data, headers=csrf_headers(session)).status_code == 422
    session = login(client, "new.analyst", created["temporary_password"])
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/private").json()["code"] == "password_change_required"
    assert client.get("/api/admin/users").status_code == 403
    response = client.post("/api/auth/password", json={"current_password": created["temporary_password"], "new_password": NEW_PASSWORD},
                           headers=csrf_headers(session))
    assert response.status_code == 200
    assert client.get("/api/private").status_code == 401
    changed = login(client, "new.analyst", NEW_PASSWORD)
    assert changed["user"]["must_change_password"] is False
    assert client.get("/api/private").status_code == 200
    assert client.get("/api/admin/users").status_code == 403
    assert store.session(client.cookies.get(auth.COOKIE_NAME))["user"]["role"] == "analyst"


def test_analyst_cannot_manage_accounts(setup):
    client, _, admin, analyst = setup
    session = login(client, "analyst")
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users", json={"username": "intruder", "role": "admin"},
                       headers=csrf_headers(session)).status_code == 403
    for user in (admin, analyst):
        assert client.post(f"/api/admin/users/{user['id']}/disable", headers=csrf_headers(session)).status_code == 403


def test_disable_revokes_sessions_and_cannot_disable_self_or_last_admin(setup):
    client, store, admin, analyst = setup
    _, token = store.login("analyst", PASSWORD, "other-client")
    session = login(client)
    assert client.post(f"/api/admin/users/{analyst['id']}/disable").status_code == 403
    response = client.post(f"/api/admin/users/{analyst['id']}/disable", headers=csrf_headers(session))
    assert response.status_code == 200 and response.json()["user"]["disabled"] is True
    assert store.session(token) is None
    assert client.post("/api/auth/login", json={"username": "analyst", "password": PASSWORD}).status_code == 401
    assert client.post(f"/api/admin/users/{admin['id']}/disable", headers=csrf_headers(session)).status_code == 409
    assert not next(user for user in store.list_users() if user["id"] == admin["id"])["disabled"]
    assert client.post("/api/admin/users/missing/disable", headers=csrf_headers(session)).status_code == 404


def test_login_attempts_are_bounded_persistent_and_expire(setup):
    client, store, _, _ = setup
    for _ in range(auth.LOGIN_MAX_ATTEMPTS):
        assert client.post("/api/auth/login", json={"username": "ADMIN", "password": "wrong"}).status_code == 401
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    reloaded = auth.AuthStore(store.db_path)
    with pytest.raises(HTTPException) as error:
        reloaded.login("admin", PASSWORD, "different-address")
    assert error.value.status_code == 429
    with sqlite3.connect(store.db_path) as db:
        db.execute("UPDATE login_limits SET expires_at = 0")
    login(client)


def test_ip_limits_block_username_rotation_and_ignore_forwarded_headers(setup, monkeypatch):
    client, _, _, _ = setup
    monkeypatch.setattr(auth, "LOGIN_IP_MAX_ATTEMPTS", 3)
    for index in range(3):
        response = client.post("/api/auth/login", json={"username": f"unknown{index}", "password": "wrong"},
                               headers={"X-Forwarded-For": f"192.0.2.{index}"})
        assert response.status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                       headers={"X-Forwarded-For": "192.0.2.100"}).status_code == 429


def test_invalid_credentials_and_json_do_not_echo_secrets(setup, caplog):
    client, _, _, _ = setup
    secret = "secret-value-must-not-appear"
    for data in ({"username": "unknown", "password": secret}, {"username": "admin", "password": secret}):
        response = client.post("/api/auth/login", json=data)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid username or password"}
    for data in ({"username": "admin", "password": {"secret": secret}}, [secret], {"password": secret}):
        response = client.post("/api/auth/login", json=data)
        assert response.status_code == 422 and secret not in response.text
    assert client.post("/api/auth/login", content="{broken", headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post("/api/auth/login", json={"username": "admin", "password": "x" * 9000}).status_code == 413
    assert client.post("/api/auth/login", data={"username": "admin", "password": secret}).status_code == 415
    assert secret not in caplog.text


def test_store_reset_revokes_sessions_and_enforces_policy(setup):
    client, store, _, _ = setup
    login(client)
    token = client.cookies.get(auth.COOKIE_NAME)
    with pytest.raises(HTTPException):
        store.reset_password("admin", "short")
    assert store.session(token) is not None
    store.reset_password("admin", NEW_PASSWORD)
    assert store.session(token) is None
    assert login(client, password=NEW_PASSWORD)["user"]["must_change_password"] is True
    assert auth.verify_password(PASSWORD, "bad hash") is False


def test_bootstrap_transaction_and_case_insensitive_uniqueness(tmp_path):
    store = auth.AuthStore(tmp_path / "auth.sqlite3")

    def bootstrap(name):
        try:
            return store.create_user(name, PASSWORD, "admin", bootstrap=True)
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(bootstrap, ["one", "two"]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results
    name = store.list_users()[0]["username"]
    with pytest.raises(HTTPException) as error:
        store.create_user(name.upper(), PASSWORD)
    assert error.value.status_code == 409


def test_independent_install_roots_do_not_share_accounts(tmp_path):
    first = auth.install_auth(FastAPI(), tmp_path / "first")
    second = auth.install_auth(FastAPI(), tmp_path / "second")
    first.create_user("admin", PASSWORD, "admin")
    assert second.list_users() == []


def test_cli_bootstrap_keeps_password_off_stdout_and_refuses_repeat(tmp_path):
    command = [sys.executable, str(PROJECT / "manage_users.py"), "--root", str(tmp_path), "bootstrap", "--username", "admin"]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    onboarding = tmp_path / "admin-onboarding.txt"
    password = next(line.split(": ", 1)[1] for line in onboarding.read_text().splitlines() if line.startswith("Temporary password:"))
    assert password not in first.stdout + first.stderr
    assert "LOCAL PERMISSIONS WARNING" in first.stderr and "ACL" in first.stderr
    store = auth.AuthStore(tmp_path / "auth.sqlite3")
    assert store.login("admin", password, "cli-test")[0]["user"]["must_change_password"] is True
    before = onboarding.read_bytes()
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode == 1
    assert onboarding.read_bytes() == before
    assert len(store.list_users()) == 1


def test_cli_create_reset_use_getpass(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(manage_users.getpass, "getpass", lambda prompt: PASSWORD)
    assert manage_users.main(["--root", str(tmp_path), "create", "--username", "analyst"]) == 0
    store = auth.AuthStore(tmp_path / "auth.sqlite3")
    _, token = store.login("analyst", PASSWORD, "cli")
    monkeypatch.setattr(manage_users.getpass, "getpass", lambda prompt: NEW_PASSWORD)
    assert manage_users.main(["--root", str(tmp_path), "reset", "--username", "analyst"]) == 0
    assert store.session(token) is None
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err and NEW_PASSWORD not in output.out + output.err


def test_malformed_unicode_credentials_fail_without_server_errors(setup):
    client, _, _, _ = setup
    # JSON can carry unpaired Unicode surrogates, which cannot be UTF-8 encoded.
    response = client.post("/api/auth/login", content=r'{"username":"\ud800","password":"some password"}',
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 401
    session = login(client)
    response = client.post("/api/auth/password", content=(
        r'{"current_password":"correct horse battery staple","new_password":"new password \ud800"}'),
        headers={**csrf_headers(session), "Content-Type": "application/json"})
    assert response.status_code == 422
    assert client.get("/api/private").status_code == 200


def test_password_guessing_is_rate_limited(setup):
    client, _, _, _ = setup
    session = login(client)
    for _ in range(auth.LOGIN_MAX_ATTEMPTS):
        assert client.post("/api/auth/password", json={"current_password": "wrong", "new_password": NEW_PASSWORD},
                           headers=csrf_headers(session)).status_code == 400
    assert client.post("/api/auth/password", json={"current_password": "wrong", "new_password": NEW_PASSWORD},
                       headers=csrf_headers(session)).status_code == 429


def test_sessions_survive_store_reload_but_never_account_reset(setup):
    client, store, _, _ = setup
    session = login(client)
    token = client.cookies.get(auth.COOKIE_NAME)
    reloaded = auth.AuthStore(store.db_path)
    assert reloaded.session(token) == session
    reloaded.reset_password("admin", NEW_PASSWORD)
    assert store.session(token) is None


def test_disabling_during_password_verification_cannot_issue_session(setup, monkeypatch):
    _, store, admin, analyst = setup
    original_verify = auth.verify_password

    def disable_then_verify(password, encoded):
        store.disable_user(analyst["id"], actor_id=admin["id"])
        return original_verify(password, encoded)

    monkeypatch.setattr(auth, "verify_password", disable_then_verify)
    with pytest.raises(HTTPException) as error:
        store.login("analyst", PASSWORD, "racing-client")
    assert error.value.status_code == 401
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_concurrent_admin_disables_preserve_one_active_admin(setup):
    _, store, first, _ = setup
    second = store.create_user("secondadmin", PASSWORD, "admin")

    def disable(pair):
        actor, target = pair
        try:
            return store.disable_user(target["id"], actor_id=actor["id"])
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(disable, [(first, second), (second, first)]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert len([user for user in store.list_users() if user["role"] == "admin" and not user["disabled"]]) == 1
