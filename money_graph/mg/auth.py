"""Local accounts and opaque, revocable SQLite sessions.

Integrate with ``install_auth(app, ROOT / '.local')``. The returned AuthStore is
also available as app.state.auth_store; AuthStore(db_path) supports isolated
tests and local account administration. Generated passwords require a change.
"""

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

COOKIE_NAME = "mg_session"
SESSION_SECONDS = 8 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5
LOGIN_IP_MAX_ATTEMPTS = 30
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_PASSWORD_SLOTS = threading.BoundedSemaphore(4)
_USERNAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}\Z")


def _username(value):
    if not isinstance(value, str) or not _USERNAME.fullmatch(value):
        raise HTTPException(422, "Username must be 1-64 letters, digits, dots, underscores or hyphens")
    return value.lower()


def _password(value):
    if not isinstance(value, str) or not MIN_PASSWORD_LENGTH <= len(value) <= MAX_PASSWORD_LENGTH:
        raise HTTPException(422, f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise HTTPException(422, "Password must contain valid Unicode characters") from None
    return value


def _derive(password, salt):
    with _PASSWORD_SLOTS:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8,
                              p=1, dklen=32, maxmem=64 * 1024 * 1024)


def hash_password(password):
    salt = secrets.token_bytes(16)
    return f"scrypt$16384$8$1${salt.hex()}${_derive(_password(password), salt).hex()}"


def verify_password(password, encoded):
    if not isinstance(password, str) or not 1 <= len(password) <= MAX_PASSWORD_LENGTH:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1"):
            return False
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt) != 16 or len(expected) != 32:
            return False
        return hmac.compare_digest(_derive(password, salt), expected)
    except (AttributeError, ValueError, UnicodeError):
        return False


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_user(row):
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "must_change_password": bool(row["must_change_password"]),
            "disabled": bool(row["disabled"]), "created_at": row["created_at"]}


class AuthStore:
    """Short-lived connections; write transactions serialize account invariants.

    create_user(username, password, role='analyst', must_change_password=False)
    returns a safe user dict. bootstrap=True additionally requires an empty DB.
    No plaintext passwords or raw session tokens are persisted in the database.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create with private POSIX permissions before SQLite opens the file.
        # On Windows, access is governed by the enclosing directory's ACL.
        self.db_path.touch(mode=0o600, exist_ok=True)
        with self._db(write=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'analyst')),
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS login_limits (
                    key TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL,
                    expires_at REAL NOT NULL
                );
            """)
        # Unknown users still perform a password derivation, just like known ones.
        self._dummy_hash = hash_password(secrets.token_urlsafe(32))

    @contextmanager
    def _db(self, *, write=False):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_user(self, username, password, role="analyst", *,
                    must_change_password=False, bootstrap=False, actor_id=None):
        username = _username(username)
        if role not in ("admin", "analyst"):
            raise HTTPException(422, "Role must be admin or analyst")
        password_hash = hash_password(password)
        user_id = uuid.uuid4().hex
        try:
            with self._db(write=True) as db:
                if actor_id is not None:
                    self._require_admin(db, actor_id)
                if bootstrap and db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                    raise HTTPException(409, "Bootstrap is allowed only when no users exist")
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, 0, ?)",
                           (user_id, username, password_hash, role, int(must_change_password), time.time()))
                return _safe_user(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Username already exists") from exc

    @staticmethod
    def _require_admin(db, actor_id):
        row = db.execute("SELECT * FROM users WHERE id = ?", (actor_id,)).fetchone()
        if not row or row["disabled"] or row["role"] != "admin" or row["must_change_password"]:
            raise HTTPException(403, "Administrator access required")

    def list_users(self):
        with self._db() as db:
            return [_safe_user(row) for row in db.execute("SELECT * FROM users ORDER BY username")]

    def _limit_attempt(self, username, client_ip):
        now = time.time()
        keys = (("user:" + _digest(username), LOGIN_MAX_ATTEMPTS),
                ("ip:" + _digest(client_ip), LOGIN_IP_MAX_ATTEMPTS))
        with self._db(write=True) as db:
            db.execute("DELETE FROM login_limits WHERE expires_at <= ?", (now,))
            for key, maximum in keys:
                row = db.execute("SELECT * FROM login_limits WHERE key = ?", (key,)).fetchone()
                if row and row["attempts"] >= maximum:
                    raise HTTPException(429, "Too many attempts; try again later",
                                        headers={"Retry-After": str(max(1, int(row["expires_at"] - now) + 1))})
            for key, _ in keys:
                db.execute("""INSERT INTO login_limits VALUES (?, 1, ?)
                              ON CONFLICT(key) DO UPDATE SET attempts = attempts + 1""",
                           (key, now + LOGIN_WINDOW_SECONDS))

    @staticmethod
    def _new_session(db, user_id):
        token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                   (_digest(token), user_id, csrf_token, time.time() + SESSION_SECONDS))
        return token, csrf_token

    def login(self, username, password, client_ip):
        # Invalid names get the same generic login result, without leaking records.
        if not isinstance(username, str) or not _USERNAME.fullmatch(username):
            raise HTTPException(401, "Invalid username or password")
        username = username.lower()
        self._limit_attempt(username, client_ip)
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        matches = verify_password(password, row["password_hash"] if row else self._dummy_hash)
        if not matches or not row or row["disabled"]:
            raise HTTPException(401, "Invalid username or password")
        with self._db(write=True) as db:
            # A reset/disable racing a password check must not create a session.
            current = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            if not current or current["disabled"] or current["password_hash"] != row["password_hash"]:
                raise HTTPException(401, "Invalid username or password")
            token, csrf_token = self._new_session(db, row["id"])
            db.execute("DELETE FROM login_limits WHERE key = ?", ("user:" + _digest(username),))
            return {"user": _safe_user(current), "csrf_token": csrf_token}, token

    def session(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        with self._db() as db:
            row = db.execute("""SELECT users.*, sessions.csrf_token FROM sessions
                                JOIN users ON users.id = sessions.user_id
                                WHERE token_hash = ? AND expires_at > ? AND disabled = 0""",
                             (_digest(token), time.time())).fetchone()
            return {"user": _safe_user(row), "csrf_token": row["csrf_token"]} if row else None

    def logout(self, token):
        with self._db(write=True) as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))

    def change_password(self, token, current_password, new_password, client_ip):
        session = self.session(token)
        if not session:
            raise HTTPException(401, "Authentication required")
        user_id = session["user"]["id"]
        self._limit_attempt(session["user"]["username"], client_ip)
        with self._db() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(current_password, row["password_hash"]):
            raise HTTPException(400, "Current password is incorrect")
        _password(new_password)
        if current_password == new_password:
            raise HTTPException(422, "New password must differ from the current password")
        password_hash = hash_password(new_password)
        with self._db(write=True) as db:
            active = db.execute("""SELECT 1 FROM sessions JOIN users ON users.id = sessions.user_id
                                   WHERE token_hash = ? AND expires_at > ? AND disabled = 0
                                   AND password_hash = ?""",
                                (_digest(token), time.time(), row["password_hash"])).fetchone()
            if not active:
                raise HTTPException(401, "Authentication required")
            db.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                       (password_hash, user_id))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM login_limits WHERE key = ?", ("user:" + _digest(row["username"]),))

    def reset_password(self, username, new_password, *, must_change_password=True):
        username, encoded = _username(username), hash_password(new_password)
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if not row:
                raise HTTPException(404, "User not found")
            db.execute("UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
                       (encoded, int(must_change_password), row["id"]))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            db.execute("DELETE FROM login_limits WHERE key = ?", ("user:" + _digest(username),))
            return _safe_user(db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone())

    def disable_user(self, user_id, *, actor_id):
        with self._db(write=True) as db:
            self._require_admin(db, actor_id)
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, "User not found")
            if user_id == actor_id:
                raise HTTPException(409, "You cannot disable your own account")
            if row["role"] == "admin" and not row["disabled"]:
                admins = db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0").fetchone()[0]
                if admins <= 1:
                    raise HTTPException(409, "Cannot disable the last administrator")
            db.execute("UPDATE users SET disabled = 1 WHERE id = ?", (user_id,))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            return _safe_user(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def _origin_key(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def _check_origin(request):
    origins = request.headers.getlist("origin")
    if origins:
        expected = _origin_key(f"{request.url.scheme}://{request.url.netloc}")
        if len(origins) != 1 or _origin_key(origins[0]) is None or _origin_key(origins[0]) != expected:
            raise HTTPException(403, "Cross-origin request denied")
    if request.method not in SAFE_METHODS and request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-origin request denied")


async def _json_body(request, keys):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Content-Type must be application/json")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise HTTPException(413, "Request body is too large")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "Invalid JSON") from None
    if not isinstance(value, dict) or set(value) != set(keys) or any(not isinstance(value[k], str) for k in keys):
        raise HTTPException(422, "Invalid request fields")
    return value


def _with_cookie(request, result):
    payload, token = result
    response = JSONResponse(payload)
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/api")
    return response


def _clear_cookie(request, response):
    response.delete_cookie(COOKIE_NAME, path="/api", secure=request.url.scheme == "https",
                           httponly=True, samesite="strict")
    return response


def install_auth(app, root: Path):
    """Register the API gate and account routes; main disables OpenAPI itself.

    No Origin is allowed for non-browser clients; any supplied Origin must match
    scheme/host/port. Every authenticated unsafe API call needs x-csrf-token.
    Password changes revoke all sessions and clear the cookie, requiring login.
    """
    store = AuthStore(Path(root) / "auth.sqlite3")
    app.state.auth_store = store

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        path = request.url.path
        if path != "/api" and not path.startswith("/api/"):
            return await call_next(request)
        try:
            _check_origin(request)
            public = (path == "/api/health" and request.method in {"GET", "HEAD"}) or (
                path == "/api/auth/login" and request.method == "POST")
            if not public:
                session = await run_in_threadpool(store.session, request.cookies.get(COOKIE_NAME))
                if not session:
                    raise HTTPException(401, "Authentication required")
                request.state.user = session["user"]
                request.state.csrf_token = session["csrf_token"]
                if request.method not in SAFE_METHODS:
                    csrf = request.headers.getlist("x-csrf-token")
                    if len(csrf) != 1 or not hmac.compare_digest(csrf[0].encode(), session["csrf_token"].encode()):
                        raise HTTPException(403, "Invalid CSRF token")
                if session["user"]["must_change_password"] and path not in {
                        "/api/auth/me", "/api/auth/password", "/api/auth/logout"}:
                    response = JSONResponse({"detail": "Password change required", "code": "password_change_required"}, status_code=403)
                    response.headers["Cache-Control"] = "no-store"
                    return response
            response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        response.headers["Cache-Control"] = "no-store"
        return response

    def client_ip(request):
        # Never trust a client-supplied X-Forwarded-For header here.
        return request.client.host if request.client else "unknown"

    def require_admin(request):
        if request.state.user["role"] != "admin":
            raise HTTPException(403, "Administrator access required")

    @app.post("/api/auth/login")
    async def login(request: Request):
        data = await _json_body(request, ("username", "password"))
        result = await run_in_threadpool(store.login, data["username"], data["password"], client_ip(request))
        return _with_cookie(request, result)

    @app.get("/api/auth/me")
    def me(request: Request):
        return {"user": request.state.user, "csrf_token": request.state.csrf_token}

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        store.logout(request.cookies[COOKIE_NAME])
        return _clear_cookie(request, Response(status_code=204))

    @app.post("/api/auth/password")
    async def change_password(request: Request):
        data = await _json_body(request, ("current_password", "new_password"))
        await run_in_threadpool(store.change_password, request.cookies[COOKIE_NAME],
                                data["current_password"], data["new_password"], client_ip(request))
        return _clear_cookie(request, JSONResponse({"detail": "Password changed. Sign in again."}))

    @app.get("/api/admin/users")
    def list_users(request: Request):
        require_admin(request)
        return store.list_users()

    @app.post("/api/admin/users", status_code=201)
    async def create_user(request: Request):
        require_admin(request)
        data = await _json_body(request, ("username", "role"))
        temporary_password = secrets.token_urlsafe(24)
        user = await run_in_threadpool(store.create_user, data["username"], temporary_password,
                                      data["role"], must_change_password=True, actor_id=request.state.user["id"])
        return {"user": user, "temporary_password": temporary_password}

    @app.post("/api/admin/users/{user_id}/disable")
    def disable_user(user_id: str, request: Request):
        require_admin(request)
        return {"user": store.disable_user(user_id, actor_id=request.state.user["id"])}

    return store
