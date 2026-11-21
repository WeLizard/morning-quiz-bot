"""Single-process local admin authentication; independent of Telegram identity."""
from collections import deque
import asyncio
from dataclasses import dataclass
from hashlib import pbkdf2_hmac, sha256
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import tempfile
import time

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

COOKIE = "mqb_admin_session"
SAFE = {"GET", "HEAD", "OPTIONS"}
PASSWORD_ITERATIONS = 600000


@dataclass
class AdminSession:
    csrf: str
    created: float
    last_seen: float


class AdminAuth:
    def __init__(self, access_token=None, *, hosts=None, clock=time.monotonic, credentials_file=None):
        token = os.getenv("ADMIN_ACCESS_TOKEN", "") if access_token is None else access_token
        # Fail closed when unconfigured. A separate random key, never BOT_TOKEN.
        self.token_digest = sha256(token.encode()).digest() if 32 <= len(token) <= 512 else None
        configured_path = credentials_file if credentials_file is not None else os.getenv("ADMIN_CREDENTIALS_FILE")
        self.credentials_file = None
        self.credentials = None
        if configured_path:
            path = Path(configured_path).expanduser()
            if not path.is_absolute():
                raise ValueError("ADMIN_CREDENTIALS_FILE must be an absolute path outside the repository")
            path = path.resolve()
            if path.is_relative_to(Path(__file__).resolve().parent.parent):
                raise ValueError("ADMIN_CREDENTIALS_FILE must be outside the repository")
            self.credentials_file = path
            try:
                self.credentials = self._read_credentials(path)
            except FileNotFoundError:
                pass
        self.hosts = set(hosts or os.getenv("ADMIN_ALLOWED_HOSTS", "localhost,127.0.0.1,::1").lower().split(","))
        self.hosts = {host.strip().strip("[]") for host in self.hosts if host.strip()}
        if "*" in self.hosts or any("/" in host or "*" in host for host in self.hosts):
            raise ValueError("ADMIN_ALLOWED_HOSTS must contain explicit host names, not wildcards")
        self.clock = clock
        self.sessions = {}
        self.failures = {}
        self.attempts = deque()
        self.credentials_lock = asyncio.Lock()

    @staticmethod
    def _read_credentials(path):
        try:
            if path.stat().st_size > 4096:
                raise ValueError("Credential file is too large")
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or data.get("algorithm") != "pbkdf2-sha256"
                    or type(data.get("iterations")) is not int
                    or not PASSWORD_ITERATIONS <= data["iterations"] <= 2000000
                    or not isinstance(data.get("username"), str)
                    or not 3 <= len(data["username"]) <= 64
                    or len(bytes.fromhex(data["salt"])) != 32
                    or len(bytes.fromhex(data["password_hash"])) != 32):
                raise ValueError("Invalid credential file")
            data["username"].encode()
            return data
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("ADMIN_CREDENTIALS_FILE is invalid; refusing token fallback") from exc

    @property
    def configured(self):
        return self.credentials is not None or self.token_digest is not None

    def verify_credentials(self, data):
        if not isinstance(data, dict):
            return False
        credentials = self.credentials
        if credentials is None:
            token = data.get("token")
            try:
                return (self.token_digest is not None and isinstance(token, str)
                        and hmac.compare_digest(sha256(token.encode()).digest(), self.token_digest))
            except UnicodeError:
                return False
        username, password = data.get("username"), data.get("password")
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 256:
            return False
        try:
            username_bytes, password_bytes = username.encode(), password.encode()
        except UnicodeError:
            return False
        candidate = pbkdf2_hmac("sha256", password_bytes, bytes.fromhex(credentials["salt"]), credentials["iterations"])
        return (hmac.compare_digest(candidate, bytes.fromhex(credentials["password_hash"]))
                and hmac.compare_digest(username_bytes, credentials["username"].encode())
                and self.credentials is credentials)

    @staticmethod
    def password_record(username, password):
        salt = secrets.token_bytes(32)
        return {"version": 1, "algorithm": "pbkdf2-sha256", "iterations": PASSWORD_ITERATIONS,
                "username": username, "salt": salt.hex(),
                "password_hash": pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS).hex()}

    def save_credentials(self, data):
        path = self.credentials_file
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = None
                json.dump(data, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return data
        finally:
            if fd is not None:
                os.close(fd)
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get_session(self, request):
        now = self.clock()
        self.sessions = {key: value for key, value in self.sessions.items()
                         if now - value.created < 28800 and now - value.last_seen < 1800}
        key = sha256(request.cookies.get(COOKIE, "").encode()).digest()
        return self.sessions.get(key)

    def forget(self, request):
        self.sessions.pop(sha256(request.cookies.get(COOKIE, "").encode()).digest(), None)

    def rate_limited(self, client):
        now = self.clock()
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        self.failures = {key: values for key, values in self.failures.items() if values[-1] > now - 60}
        recent = [when for when in self.failures.get(client, []) if when > now - 60]
        if len(self.attempts) >= 40 or len(recent) >= 5:
            return True
        self.attempts.append(now)
        self.failures[client] = recent + [now]
        return False


LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def in_dev_container():
    return os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()


def plain_http_allowed(request):
    """Plain HTTP reaches the admin only on a local hostname: from loopback, or through the
    loopback port mapping of the local dev container (its peer is the Docker bridge)."""
    if request.url.hostname not in LOCAL_HOSTNAMES:
        return False
    try:
        if ipaddress.ip_address(request.client.host).is_loopback:
            return True
    except (ValueError, AttributeError):
        pass
    return in_dev_container()


class AdminAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, auth):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request, call_next):
        auth = self.auth
        if request.url.hostname not in auth.hosts:
            return JSONResponse({"detail": "Недопустимый адрес админки"}, status_code=400)
        if request.url.scheme != "https" and not plain_http_allowed(request):
            return JSONResponse({"detail": "Вне loopback админка требует HTTPS"}, status_code=403)
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        if request.method not in SAFE and ((origin and origin != expected_origin)
                                           or request.headers.get("sec-fetch-site") == "cross-site"):
            return JSONResponse({"detail": "Межсайтовые запросы запрещены"}, status_code=403)

        path = request.url.path
        public = path in {"/login", "/auth/login", "/auth/method"} or path.startswith("/static/")
        session = auth.get_session(request)
        if not public:
            if not auth.configured:
                return JSONResponse({"detail": "Задайте отдельный ADMIN_ACCESS_TOKEN (32–512 символов)"}, status_code=503)
            if session is None:
                if path == "/":
                    return RedirectResponse("/login", status_code=303)
                return JSONResponse({"detail": "Требуется вход в админку"}, status_code=401)
            if request.method not in SAFE and not hmac.compare_digest(
                    request.headers.get("x-csrf-token", "").encode(), session.csrf.encode()):
                return JSONResponse({"detail": "Недействительный CSRF-токен"}, status_code=403)
            session.last_seen = auth.clock()
        request.state.admin_session = session
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        policy = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        if os.getenv("STORAGE_BACKEND", "postgres").strip().lower() == "postgres":
            policy += "; default-src 'self'; script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; frame-src 'none'"
        response.headers["Content-Security-Policy"] = policy
        return response


def install_admin_auth(app, *, auth=None):
    auth = auth or AdminAuth()
    app.state.admin_auth = auth
    app.add_middleware(AdminAuthMiddleware, auth=auth)

    @app.get("/login", include_in_schema=False)
    async def login_page():
        return FileResponse(Path(__file__).parent / "templates" / "login.html")

    async def read_json(request, *, invalid_status=400):
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return None, JSONResponse({"detail": "Ожидается JSON"}, status_code=415)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                return None, JSONResponse({"detail": "Некорректная длина запроса"}, status_code=400)
            if declared_size < 0:
                return None, JSONResponse({"detail": "Некорректная длина запроса"}, status_code=400)
            if declared_size > 2048:
                return None, JSONResponse({"detail": "Запрос слишком большой"}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 2048:
                return None, JSONResponse({"detail": "Запрос слишком большой"}, status_code=413)
            body.extend(chunk)
        try:
            return json.loads(body), None
        except (ValueError, UnicodeError, RecursionError):
            return None, JSONResponse({"detail": "Некорректный JSON"}, status_code=invalid_status)

    @app.get("/auth/method", include_in_schema=False)
    async def auth_method():
        return {"method": "password" if auth.credentials is not None else "token", "configured": auth.configured}

    @app.post("/auth/login", include_in_schema=False)
    async def login(request: Request):
        if not auth.configured:
            return JSONResponse({"detail": "Вход не настроен: задайте отдельный ADMIN_ACCESS_TOKEN (32–512 символов)"}, status_code=503)
        if auth.rate_limited(request.client.host):
            return JSONResponse({"detail": "Слишком много попыток. Подождите минуту."}, status_code=429, headers={"Retry-After": "60"})
        data, error = await read_json(request, invalid_status=401)
        if error is not None:
            return error
        credentials_before = auth.credentials
        valid = await asyncio.to_thread(auth.verify_credentials, data)
        valid = valid and auth.credentials is credentials_before
        if not valid:
            return JSONResponse({"detail": "Неверные данные для входа"}, status_code=401)
        auth.get_session(request)  # prune expired sessions
        if len(auth.sessions) >= 256:
            return JSONResponse({"detail": "Достигнут лимит сессий"}, status_code=503)
        auth.forget(request)
        token = secrets.token_urlsafe(32)
        session = AdminSession(secrets.token_urlsafe(32), auth.clock(), auth.clock())
        auth.sessions[sha256(token.encode()).digest()] = session
        response = JSONResponse({"authenticated": True})
        response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=28800, path="/")
        return response

    @app.get("/auth/session", include_in_schema=False)
    async def session_info(request: Request):
        return {"authenticated": True, "csrf_token": request.state.admin_session.csrf,
                "credentials_configured": auth.credentials is not None,
                "storage_backend": os.getenv("STORAGE_BACKEND", "postgres").strip().lower()}

    @app.get("/auth/credentials", include_in_schema=False)
    async def credentials_page():
        return FileResponse(Path(__file__).parent / "templates" / "admin_credentials.html")

    @app.post("/auth/credentials", include_in_schema=False)
    async def set_credentials(request: Request):
        if auth.credentials_file is None:
            return JSONResponse({"detail": "Для сохранения входа задайте ADMIN_CREDENTIALS_FILE вне репозитория"}, status_code=503)
        if auth.rate_limited(request.client.host):
            return JSONResponse({"detail": "Слишком много попыток. Подождите минуту."}, status_code=429, headers={"Retry-After": "60"})
        data, error = await read_json(request)
        if error is not None:
            return error
        username = data.get("username") if isinstance(data, dict) else None
        password = data.get("password") if isinstance(data, dict) else None
        if (not isinstance(username, str) or not 3 <= len(username) <= 64
                or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in username)):
            return JSONResponse({"detail": "Логин: от 3 до 64 символов без пробелов и управляющих знаков"}, status_code=400)
        if not isinstance(password, str) or not 11 <= len(password) <= 256:
            return JSONResponse({"detail": "Пароль: от 11 до 256 символов"}, status_code=400)
        try:
            username.encode()
            password.encode()
        except UnicodeError:
            return JSONResponse({"detail": "Логин и пароль должны содержать корректные символы Unicode"}, status_code=400)
        async with auth.credentials_lock:
            if auth.get_session(request) is not request.state.admin_session:
                return JSONResponse({"detail": "Требуется повторный вход в админку"}, status_code=401)
            saved = await asyncio.to_thread(auth.password_record, username, password)
            if auth.get_session(request) is not request.state.admin_session:
                return JSONResponse({"detail": "Требуется повторный вход в админку"}, status_code=401)
            try:
                # Commit the file and in-process state without an await between them.
                # A cancelled hashing request cannot leave token fallback active.
                auth.save_credentials(saved)
            except OSError:
                return JSONResponse({"detail": "Не удалось сохранить данные входа"}, status_code=503)
            auth.credentials = saved
            # A credential change revokes every other browser session.
            key = sha256(request.cookies.get(COOKIE, "").encode()).digest()
            auth.sessions = {key: request.state.admin_session}
        return {"authenticated": True, "credentials_configured": True}

    @app.post("/auth/logout", include_in_schema=False)
    async def logout(request: Request):
        auth.forget(request)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=request.url.scheme == "https")
        return response
