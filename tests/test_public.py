"""Judge mode (MULETRACE_PUBLIC_DEMO=1): roles, security headers, body cap, per-IP rate limit, demo reset."""
import glob, json, os
import pytest
from fastapi.testclient import TestClient

H = {"X-MuleTrace-Token": "test-token"}


@pytest.fixture()
def app(api_env, monkeypatch):
    import importlib, sys
    m = sys.modules.get("api.main") or importlib.import_module("api.main")
    m._buckets.clear(); m.last_reset[0] = 0.0
    yield m
    m._buckets.clear()


@pytest.fixture()
def public(app, monkeypatch):
    monkeypatch.setattr(app, "PUBLIC_DEMO", True)
    return TestClient(app.app)


def test_security_headers_everywhere(app):
    c = TestClient(app.app)
    for r in (c.get("/"), c.get("/health"), c.get("/alerts"), c.post("/score", content="x", headers={"Content-Type": "text/plain"})):
        assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"] and r.headers["X-Frame-Options"] == "DENY"
    script_src = c.get("/").headers["Content-Security-Policy"].split("script-src")[1].split(";")[0]
    assert "'sha256-" in script_src and "unsafe-inline" not in script_src and "unsafe-eval" not in script_src


def test_body_size_cap(app):
    c = TestClient(app.app)
    r = c.post("/score", content=json.dumps({"src": "a", "dst": "b", "amount": 1, "txn_id": "x" * 20000}),
               headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 413


def test_private_mode_has_no_public_role(app):
    c = TestClient(app.app)
    assert c.get("/alerts").status_code == 401 and c.post("/demo/reset", json={}, headers=H).status_code == 404
    assert c.get("/system").json()["public_demo"] is False


def test_public_role_permissions(public):
    assert public.get("/system").json()["public_demo"] is True
    for path in ("/alerts", "/recent", "/stats"):
        assert public.get(path).status_code == 200, path
    assert public.get("/alerts", headers={"X-MuleTrace-Token": "wrong"}).status_code == 401
    assert public.post("/score", json={"src": "a", "dst": "b", "amount": 5}).status_code == 403
    assert public.post("/replay/start", json={"n": 5, "speed": 200}).status_code == 403
    assert public.post("/replay/start", json={"n": 5, "speed": 100}).status_code in (200, 409)
    assert public.post("/replay/stop", json={}).status_code == 200
    assert public.post("/score", json={"src": "a", "dst": "b", "amount": 5}, headers=H).status_code in (200, 409, 422)


def test_public_rate_limit_spares_admin(public, app, monkeypatch):
    monkeypatch.setitem(app.LIMITS, "read", (0.001, 3))
    codes = [public.get("/health").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429
    assert public.get("/health").headers.get("Retry-After") == "2"
    assert all(public.get("/health", headers=H).status_code == 200 for _ in range(10))


def test_demo_reset_archives_db_and_is_throttled(public, app):
    db_path = app.DB_PATH
    before = set(glob.glob(db_path + ".*.bak"))
    r = public.post("/demo/reset", json={})
    assert r.status_code == 200 and r.json()["reset"] is True
    assert len(set(glob.glob(db_path + ".*.bak")) - before) == 1           # archived, not deleted (audit stays append-only)
    assert public.get("/alerts?status=all").json() == [] and public.get("/stats").json()["scored"] == 0
    assert public.post("/demo/reset", json={}).status_code == 429             # at most every 10 minutes for the public
    assert public.post("/demo/reset", json={}, headers=H).status_code == 200  # admin may reset any time
