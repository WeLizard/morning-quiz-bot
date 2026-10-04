import asyncio

import httpx
import pytest
from fastapi import FastAPI

from web.admin_auth import AdminAuth, COOKIE, install_admin_auth

TOKEN = "local-tests-only-admin-key-0000012345"


def application(auth=None):
    app = FastAPI()
    app.state.writes = 0
    @app.get("/")
    @app.get("/api/private")
    async def read():
        return {"private": True}
    @app.post("/api/private")
    async def write():
        app.state.writes += 1
        return {"saved": True}
    install_admin_auth(app, auth=auth or AdminAuth(TOKEN))
    return app


async def login(client):
    response = await client.post("/auth/login", json={"token": TOKEN})
    assert response.status_code == 200, response.text
    info = await client.get("/auth/session")
    return info.json()["csrf_token"]


def test_all_private_routes_require_cookie_session_and_mutations_require_csrf():
    async def run():
        app = application()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            assert (await client.get("/")).status_code == 303
            for path in ("/api/private", "/docs", "/openapi.json", "/auth/session"):
                assert (await client.get(path)).status_code == 401
            assert (await client.get("/api/private", headers={"Authorization": f"Bearer {TOKEN}"})).status_code == 401
            assert (await client.get("/login")).status_code == 200
            csrf = await login(client)
            assert (await client.get("/api/private")).status_code == 200
            assert (await client.post("/api/private")).status_code == 403
            assert (await client.post("/api/private", headers={"X-CSRF-Token": "fake"})).status_code == 403
            assert app.state.writes == 0
            response = await client.post("/api/private", headers={"X-CSRF-Token": csrf})
            assert response.status_code == 200 and app.state.writes == 1
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-frame-options"] == "DENY"
            old_cookie = client.cookies.get(COOKIE)
            assert (await client.post("/auth/logout", headers={"X-CSRF-Token": csrf})).status_code == 200
            assert (await client.get("/api/private")).status_code == 401
            assert (await client.get("/api/private", headers={"Cookie": f"{COOKIE}={old_cookie}"})).status_code == 401
    asyncio.run(run())


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"},
    {"Origin": "http://127.0.0.1:9000"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}])
def test_cross_site_and_rebinding_requests_are_rejected(headers):
    async def run():
        app = application()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            csrf = await login(client)
            result = await client.post("/api/private", headers={"X-CSRF-Token": csrf, **headers})
            assert result.status_code in {400, 403}
            assert app.state.writes == 0
            assert (await client.post("/auth/login", json={"token": TOKEN}, headers=headers)).status_code in {400, 403}
    asyncio.run(run())


def test_login_limits_and_missing_configuration_fail_closed():
    async def run():
        now = [0]
        app = application(AdminAuth(TOKEN, clock=lambda: now[0]))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            for _ in range(5):
                assert (await client.post("/auth/login", json={"token": "wrong"})).status_code == 401
            assert (await client.post("/auth/login", json={"token": TOKEN})).status_code == 429
            now[0] = 61
            await login(client)
        for value in ("", "too-short"):
            app = application(AdminAuth(value))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
                assert (await client.get("/api/private")).status_code == 503
                assert (await client.post("/auth/login", json={"token": value})).status_code == 503
    asyncio.run(run())


def test_expiration_rotation_restart_and_cookie_flags():
    async def run():
        now = [0]
        auth = AdminAuth(TOKEN, clock=lambda: now[0])
        app = application(auth)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://127.0.0.1") as client:
            response = await client.post("/auth/login", json={"token": TOKEN})
            cookie = response.headers["set-cookie"].lower()
            assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
            old_cookie = client.cookies.get(COOKIE)
            csrf = await login(client)
            assert client.cookies.get(COOKIE) != old_cookie
            assert (await client.get("/api/private", headers={"Cookie": f"{COOKIE}={old_cookie}"})).status_code == 401
            now[0] = 1800
            assert (await client.get("/api/private")).status_code == 401
            await login(client)
            for _ in range(16):
                now[0] += 1700
                assert (await client.get("/api/private")).status_code == 200
            now[0] += 1600
            assert (await client.get("/api/private")).status_code == 401
            await login(client)
            auth.sessions.clear()  # A process restart cannot reuse old session IDs.
            assert (await client.get("/api/private")).status_code == 401
    asyncio.run(run())


def test_remote_http_is_rejected_and_request_size_and_content_type_are_bounded():
    async def run():
        app = application(AdminAuth(TOKEN, hosts=["admin.lan", "127.0.0.1"]))
        transport = httpx.ASGITransport(app, client=("192.0.2.1", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://admin.lan") as client:
            assert (await client.get("/login")).status_code == 403
        async with httpx.AsyncClient(transport=transport, base_url="https://admin.lan") as client:
            assert (await client.get("/login")).status_code == 200
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
            assert (await client.post("/auth/login", data={"token": TOKEN})).status_code == 415
            assert (await client.post("/auth/login", content="{", headers={"Content-Type": "application/json"})).status_code == 401
            assert (await client.post("/auth/login", json={"token": "x" * 2100})).status_code == 413
    asyncio.run(run())
