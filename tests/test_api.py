"""API tests on the fixture model. Tests share one app instance and run in file order (stream time only moves forward)."""
import time
import pandas as pd
import pytest
from fastapi.testclient import TestClient

H = {"X-MuleTrace-Token": "test-token"}


@pytest.fixture(scope="module")
def app(api_env):
    import importlib, sys
    sys.modules.pop("api.main", None)
    return importlib.import_module("api.main")


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app.app)


def pay(**kw):
    return {"src": "100_A", "dst": "200_B", "amount": 250.0, **kw}


def test_replay_start_stop_one_stream(client, app):
    r = client.post("/replay/start", json={"n": 40, "speed": 500}, headers=H)
    assert r.status_code == 200 and r.json()["running"]
    assert client.post("/replay/start", json={"n": 5, "speed": 50}, headers=H).status_code == 409
    for _ in range(100):
        if not client.get("/stats").json()["replay"]["running"]:
            break
        time.sleep(0.05)
    s = client.post("/replay/stop", json={}, headers=H).json()
    assert not s["running"] and s["sent"] + s["rejected"] == 40 and s["rejected"] == 0


def test_score_alert_action_audit(client):
    r = client.post("/score", json=pay(txn_id="t-1"), headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "FLAG" and body["simulated"] is True
    assert body["recommendation"].startswith("FLAG") and "simulated" in body["recommendation"]
    ex = body["explanations"]
    up = [e for e in ex if e["direction"] == "raises risk"]
    assert 1 <= len(up) <= 3 and len(ex) - len(up) <= 2 and ex[:len(up)] == up         # raising signals first
    assert all({"feature", "value", "contribution", "text", "direction", "group"} <= set(e) for e in ex)
    assert all((e["contribution"] > 0) == (e["direction"] == "raises risk") for e in ex)
    assert [e["contribution"] for e in up] == sorted((e["contribution"] for e in up), reverse=True)
    net = {"dst_in_senders", "dst_in_count", "dst_burst_10m", "dst_in_amt_log", "src_out_receivers", "src_out_count",
           "src_in_amt_log", "fwd_ratio", "fwd_lag", "cycle2", "cycle3"}
    assert all(e["group"] == ("network" if e["feature"] in net else "payment") for e in ex)
    assert body["reasons"] and not any(x.startswith("AI risk score") for x in body["reasons"])
    aid = body["alert_id"]
    alert = client.get(f"/alerts/{aid}", headers=H).json()
    assert alert["status"] == "open" and alert["explanations"] == body["explanations"] and "truth" not in alert
    r = client.post(f"/alerts/{aid}/action", json={"action": "confirm", "analyst": "Asha", "note": "ring"}, headers=H)
    assert r.status_code == 200 and r.json()["simulated"] is True
    audit = client.get(f"/alerts/{aid}/audit", headers=H).json()
    assert [a["action"] for a in audit] == ["created", "confirm"]
    want = {"from_status": "open", "to_status": "confirm", "analyst": "Asha", "note": "ring"}
    assert {k: audit[1][k] for k in want} == want
    assert client.get(f"/alerts/{aid}", headers=H).json()["status"] == "confirm"


def test_audit_log_is_append_only(app):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        app.db.execute("DELETE FROM audit_log")


@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": -5}, {"src": "x" * 65}, {"src": "bad id!"}, {"fmt": "Gold"},
    {"currency": "Dogecoin"}, {"ts": "now"}, {"ts": "2022-13-01 10:00"}, {"label": 3}, {"extra": 1},
])
def test_validation_errors(client, bad):
    assert client.post("/score", json=pay(**bad), headers=H).status_code == 422


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_amounts_rejected(client, raw):
    r = client.post("/score", content='{"src":"a","dst":"b","amount":%s}' % raw,
                    headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 422


def test_time_order_and_duplicates(client, app):
    now = pd.Timestamp(app.last_t[0], unit="m")
    past = (now - pd.Timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")
    ahead = (now + pd.Timedelta(minutes=61)).strftime("%Y-%m-%d %H:%M")
    assert client.post("/score", json=pay(ts=past), headers=H).status_code == 409
    assert client.post("/score", json=pay(ts=ahead), headers=H).status_code == 422
    assert client.post("/score", json=pay(txn_id="t-1"), headers=H).status_code == 409


def test_write_endpoints_need_token_and_json(client):
    assert client.post("/score", json=pay()).status_code == 401
    assert client.post("/alerts/1/action", json={"action": "dismiss"}, headers={"X-MuleTrace-Token": "x"}).status_code == 401
    assert client.post("/score", content="{}", headers={**H, "Content-Type": "text/plain"}).status_code == 415
    assert client.get("/stats").status_code == 200


def test_bad_action_and_missing_alert(client):
    assert client.post("/alerts/1/action", json={"action": "delete"}, headers=H).status_code == 422
    assert client.post("/alerts/999999/action", json={"action": "dismiss"}, headers=H).status_code == 404
    assert client.get("/alerts/999999/audit", headers=H).status_code == 404


def test_graph_shows_only_last_hour(client, app):
    now = pd.Timestamp(app.last_t[0], unit="m")
    at = lambda m: (now + pd.Timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M")
    assert client.post("/score", json=pay(src="G_OLD", dst="G_HUB", ts=at(1)), headers=H).status_code == 200
    assert client.post("/score", json=pay(src="X1", dst="X2", ts=at(50)), headers=H).status_code == 200
    assert client.post("/score", json=pay(src="G_NEW", dst="G_HUB", ts=at(100)), headers=H).status_code == 200
    senders = {e["from"] for e in client.get("/graph/G_HUB", headers=H).json()["edges"]}
    assert senders == {"G_NEW"}


def test_legacy_decisions_are_read_as_new_vocabulary(client, app):
    with app.db_lock, app.db:
        app.db.execute("INSERT INTO alerts(txn_id,ts,src,dst,amount,score,decision,reasons,status) "
                       "VALUES('old',0,'a','b',1,0.5,'REVIEW','[]','open')")
    rows = client.get("/alerts?status=all&decision=FLAG&limit=500", headers=H).json()
    assert any(r["txn_id"] == "old" and r["decision"] == "FLAG" for r in rows)


def test_evidence_reads_eval_files_and_marks_missing(client):
    ev = client.get("/evidence").json()
    assert ev["metrics"] and ev["report"] and "C: MuleTrace network model" in ev["report"]["models"]
    assert ev["latency"] is None                    # not measured in the fixture run -> null, never invented
    assert ev["detection_delay"] is None and ev["egress"] is None and ev["nnpa"] is None


def test_alert_sort_and_latency_percentiles(client):
    by_time = client.get("/alerts?status=all&sort=time&limit=500", headers=H).json()
    assert [a["ts"] for a in by_time] == sorted((a["ts"] for a in by_time), reverse=True)
    by_risk = client.get("/alerts?status=all&sort=risk&limit=500", headers=H).json()
    assert [a["score"] for a in by_risk] == sorted((a["score"] for a in by_risk), reverse=True)
    assert client.get("/alerts?sort=bogus", headers=H).status_code == 422
    s = client.get("/stats").json()
    assert s["p50_ms"] is not None and s["p50_ms"] <= s["p95_ms"]


def test_stats_accounts_and_graph_totals(client, app):
    s = client.get("/stats").json()
    assert s["accounts_tracked"] == len(app.state.seen) > 0
    acc = next(iter(app.state.out))
    g = client.get(f"/graph/{acc}?limit=1", headers=H).json()
    assert {"in_amount", "in_count", "out_amount", "out_count"} <= set(g)
    assert g["out_count"] >= len([e for e in g["edges"] if e["from"] == acc]) and g["out_amount"] >= 0


@pytest.mark.parametrize("path", ["/alerts", "/alerts/1", "/alerts/1/audit", "/graph/100_A", "/recent"])
def test_account_data_reads_need_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-MuleTrace-Token": "wrong"}).status_code == 401
    assert client.get(path, headers=H).status_code in (200, 404)


@pytest.mark.parametrize("path", ["/health", "/system", "/stats", "/evidence"])
def test_public_endpoints_expose_no_account_ids(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "100_A" not in r.text and "200_B" not in r.text and "G_HUB" not in r.text


def test_system_cites_egress_measurement(client, app, tmp_path, monkeypatch):
    assert "not measured" in client.get("/system").json()["data_egress_basis"]      # fixture eval/ has no egress.json
    e = {"measured_at": "2026-10-18 00:00:00 UTC", "non_loopback_connections": [], "samples": 12, "payments_scored_during_check": 2000}
    (tmp_path / "egress.json").write_text(__import__("json").dumps(e))
    monkeypatch.setattr(app, "EVAL", str(tmp_path))
    basis = client.get("/system").json()["data_egress_basis"]
    assert basis.startswith("measured") and "0 non-loopback" in basis and "2000 payments" in basis


def test_default_scorer_is_model_c_on_cpu(client):
    s = client.get("/system").json()
    assert s["scorer"] == "c" and s["inference"].startswith("CPU") and "XGBoost" in s["model"]
