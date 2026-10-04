"""Single-process local admin authentication; independent of Telegram identity."""
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import hmac
import ipaddress
import os
from pathlib import Path
import secrets
import time

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

COOKIE = "mqb_admin_session"
SAFE = {"GET", "HEAD", "OPTIONS"}


@dataclass
class AdminSession:
    csrf: str
    created: float
    last_seen: float


class AdminAuth:
    def __init__(self, access_token=None, *, hosts=None, clock=time.monotonic):
        token = os.getenv("ADMIN_ACCESS_TOKEN", "") if access_token is None else access_token
        # Fail closed when unconfigured. A separate random key, never BOT_TOKEN.
        self.token_digest = sha256(token.encode()).digest() if 32 <= len(token) <= 512 else None
        self.hosts = set(hosts or os.getenv("ADMIN_ALLOWED_HOSTS", "localhost,127.0.0.1,::1").lower().split(","))
        self.hosts = {host.strip().strip("[]") for host in self.hosts if host.strip()}
        if "*" in self.hosts or any("/" in host or "*" in host for host in self.hosts):
            raise ValueError("ADMIN_ALLOWED_HOSTS must contain explicit host names, not wildcards")
        self.clock = clock
        self.sessions = {}
        self.failures = {}
        self.attempts = deque()

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


class AdminAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, auth):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request, call_next):
        auth = self.auth
        if request.url.hostname not in auth.hosts:
            return JSONResponse({"detail": "Недопустимый адрес админки"}, status_code=400)
        try:
            loopback = ipaddress.ip_address(request.client.host).is_loopback
        except (ValueError, AttributeError):
            loopback = False
        container_proxy = (os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
                           and request.url.hostname in {"localhost", "127.0.0.1", "::1"})
        if request.url.scheme != "https" and not ((loopback or container_proxy)
                                                   and request.url.hostname in {"localhost", "127.0.0.1", "::1"}):
            return JSONResponse({"detail": "Вне loopback админка требует HTTPS"}, status_code=403)
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        if (origin and origin != expected_origin) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Межсайтовые запросы запрещены"}, status_code=403)

        path = request.url.path
        public = path in {"/login", "/auth/login"} or path.startswith("/static/")
        session = auth.get_session(request)
        if not public:
            if auth.token_digest is None:
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
        if os.getenv("STORAGE_BACKEND", "json").strip().lower() == "postgres":
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

    @app.post("/auth/login", include_in_schema=False)
    async def login(request: Request):
        if auth.token_digest is None:
            return JSONResponse({"detail": "Вход не настроен: задайте отдельный ADMIN_ACCESS_TOKEN (32–512 символов)"}, status_code=503)
        if auth.rate_limited(request.client.host):
            return JSONResponse({"detail": "Слишком много попыток. Подождите минуту."}, status_code=429, headers={"Retry-After": "60"})
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return JSONResponse({"detail": "Ожидается JSON"}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2048:
                return JSONResponse({"detail": "Запрос слишком большой"}, status_code=413)
        import json
        try:
            data = json.loads(body)
            token = data.get("token") if isinstance(data, dict) else None
            valid = isinstance(token, str) and hmac.compare_digest(sha256(token.encode()).digest(), auth.token_digest)
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            return JSONResponse({"detail": "Неверный ключ доступа"}, status_code=401)
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
                "storage_backend": os.getenv("STORAGE_BACKEND", "json").strip().lower()}

    @app.post("/auth/logout", include_in_schema=False)
    async def logout(request: Request):
        auth.forget(request)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=request.url.scheme == "https")
        return response
