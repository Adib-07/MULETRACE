"""MuleTrace live API: scores payments in real time on IBM LinuxONE and serves the investigator console.

Every decision is a recommendation. No payment is actually held, released or reported: those actions are simulated,
and every analyst decision is written to an append-only audit log.
"""
import hmac, json, logging, os, platform, re, sqlite3, sys, threading, time
from collections import deque
from datetime import datetime
from typing import Literal
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
import xgboost as xgb
from xgboost import XGBClassifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from features import FlowState, ALL_FEATURES, FORMATS, CURRENCIES, reasons, explain

def _path(env, default):
    return os.environ.get(env) or os.path.join(ROOT, default)

MODELS, DATA, EVAL, WEB = (_path("MULETRACE_MODELS", "models"), _path("MULETRACE_DATA", "data"),
                           _path("MULETRACE_EVAL", "eval"), _path("MULETRACE_WEB", "web"))
DB_PATH = _path("MULETRACE_DB", "alerts.db")
TOKEN = os.environ.get("MULETRACE_TOKEN", "")
CORS = [o.strip() for o in os.environ.get("MULETRACE_CORS", "").split(",") if o.strip()]
AHEAD_MIN = 60                      # reject payments more than this many minutes ahead of the stream

logging.basicConfig(level=os.environ.get("MULETRACE_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("muletrace")

app = FastAPI(title="MuleTrace", version="1.1.0",
              description="Real-time money-mule ring detection on IBM LinuxONE. Decisions are recommendations; "
                          "all financial actions are simulated.")
if CORS:                            # same-origin only unless explicitly configured
    app.add_middleware(CORSMiddleware, allow_origins=CORS, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-MuleTrace-Token"])

@app.middleware("http")
async def json_only_posts(request: Request, call_next):
    # A cross-site page can only send text/plain or form bodies without a CORS preflight.
    # Requiring JSON forces the preflight, which fails unless MULETRACE_CORS allows that origin.
    if request.method == "POST":
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return JSONResponse({"detail": "Content-Type must be application/json"}, status_code=415)
    return await call_next(request)

@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    # FastAPI's default 422 echoes the raw input, which fails to serialise for NaN/Infinity (-> 500).
    return JSONResponse({"detail": [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]},
                        status_code=422)

@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "internal server error (see server log)"}, status_code=500)

def require_token(x_muletrace_token: str = Header(default="")):
    if TOKEN and not hmac.compare_digest(x_muletrace_token.encode(), TOKEN.encode()):
        raise HTTPException(401, "missing or wrong X-MuleTrace-Token header")

# ---------- model + thresholds ----------
meta = json.load(open(os.path.join(MODELS, "meta.json")))
FEATS = meta.get("features", ALL_FEATURES)
def pick(word):
    for k, v in meta.items():
        if word in k.lower().replace("threshold", "") and isinstance(v, (int, float)):
            return float(v)
    raise SystemExit("meta.json has no " + word + " threshold: " + str(list(meta)))
FLAG, HOLD = pick("flag"), pick("hold")

model = XGBClassifier()
model.load_model(os.path.join(MODELS, "model_c.json"))
booster = model.get_booster()
state = FlowState()
lock = threading.Lock()             # guards state, last_t, scored_ids and model inference
db_lock = threading.Lock()          # guards the single SQLite connection
stats_lock = threading.Lock()
START = time.time()
stats = {"scored": 0, "pass": 0, "flag": 0, "hold": 0, "ms_total": 0.0}
last_t = [0]                        # latest payment time seen (minutes)
scored_ids = set()                  # txn_ids already scored, so a replay cannot count a payment twice
recent = deque(maxlen=300)          # last decisions, for the live feed
ticks = deque(maxlen=5000)          # timestamps of decisions, for payments/second
lat_ms = deque(maxlen=2000)         # recent server-side decision times, for p50/p95

LEGACY = {"ALLOW": "PASS", "REVIEW": "FLAG"}
RECOMMENDATION = {
    "PASS": "PASS — no action; payment proceeds (simulated)",
    "FLAG": "FLAG — payment proceeds; queued for human review (simulated)",
    "HOLD": "HOLD — payment paused pending human review (simulated)",
}

# ---------- alert store + audit log ----------
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")
db.execute("""CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, txn_id TEXT,
  ts INTEGER, src TEXT, dst TEXT, amount REAL, score REAL, decision TEXT,
  reasons TEXT, status TEXT DEFAULT 'open', truth INTEGER)""")
have = {r[1] for r in db.execute("PRAGMA table_info(alerts)")}
for col, typ in (("currency", "TEXT"), ("fmt", "TEXT"), ("note", "TEXT"), ("acted_at", "REAL"), ("created_at", "REAL"), ("explanations", "TEXT")):
    if col not in have:
        db.execute(f"ALTER TABLE alerts ADD COLUMN {col} {typ}")
for old, new in LEGACY.items():
    n = db.execute("UPDATE alerts SET decision=? WHERE decision=?", (new, old)).rowcount
    if n:
        log.info("migrated %d alerts from decision %s to %s", n, old, new)
db.execute("CREATE INDEX IF NOT EXISTS alerts_txn ON alerts(txn_id)")
db.execute("""CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY,
  alert_id INTEGER NOT NULL REFERENCES alerts(id), action TEXT NOT NULL, from_status TEXT,
  to_status TEXT NOT NULL, analyst TEXT NOT NULL, note TEXT, created_at REAL NOT NULL)""")
db.execute("CREATE INDEX IF NOT EXISTS audit_alert ON audit_log(alert_id)")
for op in ("UPDATE", "DELETE"):
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS audit_log_no_{op.lower()} BEFORE {op} ON audit_log
      BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""")
db.commit()

def tmin(ts):
    return int(pd.Timestamp(ts).value // 60_000_000_000)

def fmt_min(t):
    return str(pd.Timestamp(t, unit="m"))

def warm_up():
    t0 = time.time()
    for name in ["train", "valid"]:
        df = pd.read_pickle(os.path.join(DATA, name + ".pkl"))
        ts = df["ts"].values.astype("datetime64[m]").astype("int64")
        for t, s, d, a in zip(ts, df["src"].values, df["dst"].values, df["amount"].values):
            state.update(int(t), s, d, float(a))
        last_t[0] = max(last_t[0], int(ts.max()))
    log.info("warm-up done (past history loaded) in %d s; stream time %s", round(time.time() - t0), fmt_min(last_t[0]))
warm_up()

def extra_reasons(f, p):
    out = []
    if f.get("self_txn"): out.append("Sender and receiver are the same account")
    if f.get("cross_cur"): out.append("Currency changes during the payment")
    if f.get("src_out_count", 0) >= 5: out.append("Sender made " + str(int(f["src_out_count"])) + " payments in the last hour")
    out.append("AI risk score " + str(round(p * 100)) + "/100, similar to known laundering")
    return out[:3]

# ---------- scoring ----------
class Rejected(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail

def score_payment(x: dict):
    t0 = time.perf_counter()
    amount = float(x["amount"])
    txn_id = x.get("txn_id") or ""
    with lock:
        if x.get("ts"):
            t = tmin(x["ts"])
        elif last_t[0]:
            t = last_t[0]           # no time given: use the current stream time
        else:
            raise Rejected(422, "ts is required until the first payment has been scored")
        if txn_id and txn_id in scored_ids:
            raise Rejected(409, f"payment {txn_id} was already scored")
        if last_t[0] and t < last_t[0]:
            raise Rejected(409, f"payment time {fmt_min(t)} is earlier than the latest scored payment "
                                f"({fmt_min(last_t[0])}); payments must arrive in time order")
        if last_t[0] and t > last_t[0] + AHEAD_MIN:
            raise Rejected(422, f"payment time {fmt_min(t)} is more than {AHEAD_MIN} minutes ahead of the "
                                f"stream ({fmt_min(last_t[0])})")
        f = state.features(t, x["src"], x["dst"], amount, x["currency"], x["cur_recv"], x["fmt"])
        state.update(t, x["src"], x["dst"], amount)
        last_t[0] = t
        if txn_id:
            scored_ids.add(txn_id)
        row = pd.DataFrame([[f[k] for k in FEATS]], columns=FEATS, dtype="float32")
        p = float(model.predict_proba(row)[0, 1])
    decision = "HOLD" if p >= HOLD else "FLAG" if p >= FLAG else "PASS"
    why, expl = [], []
    if decision != "PASS":
        # Per-decision attribution: XGBoost SHAP-style contributions (log-odds); the last column is the bias.
        contribs = booster.predict(xgb.DMatrix(row), pred_contribs=True)[0][:-1]
        expl = explain(f, contribs, FEATS)
        rule = reasons(f)                       # ring patterns first, then the model's top signals
        why = rule + [e["text"] for e in expl if e["direction"] == "raises risk" and e["text"] not in rule]
        if not why:
            why = extra_reasons(f, p)
    ms = (time.perf_counter() - t0) * 1000
    now = time.time()
    with stats_lock:
        stats["scored"] += 1; stats["ms_total"] += ms; stats[decision.lower()] += 1
        ticks.append(now)
        lat_ms.append(ms)
    alert_id = None
    if decision != "PASS":
        with db_lock:
            old = db.execute("SELECT id FROM alerts WHERE txn_id=? AND txn_id<>''", (txn_id,)).fetchone()
            if old:                 # same payment replayed after a restart: keep the original case and its audit trail
                alert_id = old[0]
            else:
                with db:
                    cur = db.execute("INSERT INTO alerts(txn_id,ts,src,dst,amount,score,decision,reasons,truth,currency,fmt,created_at,explanations) "
                                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (txn_id, t, x["src"], x["dst"], amount, p, decision, json.dumps(why),
                                      x.get("label"), x["currency"], x["fmt"], now, json.dumps(expl)))
                    alert_id = cur.lastrowid
                    db.execute("INSERT INTO audit_log(alert_id,action,from_status,to_status,analyst,note,created_at) "
                               "VALUES(?,?,?,?,?,?,?)", (alert_id, "created", None, "open", "system", decision, now))
    out = {"txn_id": txn_id, "ts": fmt_min(t), "src": x["src"], "dst": x["dst"], "amount": amount,
           "currency": x["currency"], "fmt": x["fmt"], "score": round(p, 4), "decision": decision,
           "reasons": why, "explanations": expl, "latency_ms": round(ms, 3), "alert_id": alert_id,
           "simulated": True, "recommendation": RECOMMENDATION[decision]}
    recent.appendleft(out)
    log.info(json.dumps({"event": "decision", "txn_id": txn_id, "decision": decision, "score": round(p, 4),
                         "latency_ms": round(ms, 3), "alert_id": alert_id}))
    return out

ACCOUNT = r"^[A-Za-z0-9_\-]{1,64}$"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")

class Txn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    txn_id: str = Field("", max_length=64, pattern=r"^[A-Za-z0-9_.\-]*$")
    ts: str | None = Field(None, description="YYYY-MM-DD HH:MM[:SS]. Omit to use the current stream time.")
    src: str = Field(pattern=ACCOUNT)
    dst: str = Field(pattern=ACCOUNT)
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: str = "US Dollar"
    cur_recv: str = "US Dollar"
    fmt: str = "ACH"
    label: int | None = Field(None, ge=0, le=1, description="Ground truth, stored for evaluation only. Never used for scoring.")

    @field_validator("ts")
    @classmethod
    def _ts(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not TS_RE.match(v):
            raise ValueError("must look like 2022-09-02 15:19 (YYYY-MM-DD HH:MM[:SS])")
        datetime.fromisoformat(v.replace(" ", "T"))     # rejects impossible dates such as month 13
        return v

    @field_validator("currency", "cur_recv")
    @classmethod
    def _cur(cls, v):
        if v not in CURRENCIES:
            raise ValueError("must be one of: " + ", ".join(CURRENCIES))
        return v

    @field_validator("fmt")
    @classmethod
    def _fmt(cls, v):
        if v not in FORMATS:
            raise ValueError("must be one of: " + ", ".join(FORMATS))
        return v

# ---------- live replay (simulates a bank's payment stream) ----------
replay = {"running": False, "pos": 0, "total": 0, "speed": 0, "sent": 0, "rejected": 0, "error": None}
replay_lock = threading.Lock()
_replay_thread = None
_test = None
_stop = threading.Event()

def _replay_loop(n, speed):
    try:
        end = min(replay["pos"] + n, len(_test))
        gap = 1.0 / speed
        nxt = time.perf_counter()
        while replay["pos"] < end and not _stop.is_set():
            r = _test.iloc[replay["pos"]]
            try:
                score_payment({"txn_id": str(r.txn_id), "ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": float(r.amount),
                               "currency": r.currency, "cur_recv": r.cur_recv, "fmt": r.fmt, "label": int(r.label)})
                replay["sent"] += 1
            except Rejected as e:
                replay["rejected"] += 1
                log.warning("replay row %d rejected: %s", replay["pos"], e.detail)
            replay["pos"] += 1
            nxt += gap
            wait = nxt - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            else:
                nxt = time.perf_counter()   # running behind: go as fast as the machine allows
    except Exception:
        log.exception("replay stopped by an error")
        replay["error"] = "replay stopped by an internal error (see server log)"
    finally:
        replay["running"] = False

class ReplayReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = Field(5000, ge=1, le=10_000_000)
    speed: float = Field(50, gt=0, le=500)

# ---------- endpoints ----------
@app.get("/", include_in_schema=False)
def console():
    path = os.path.join(WEB, "index.html")
    if not os.path.exists(path):
        raise HTTPException(404, "web/index.html not found")
    return FileResponse(path)

if os.path.isdir(os.path.join(WEB, "vendor")):
    app.mount("/vendor", StaticFiles(directory=os.path.join(WEB, "vendor")), name="vendor")

@app.get("/health")
def health():
    return {"status": "ok", "uptime_s": round(time.time() - START)}

def egress_basis():
    path = os.path.join(EVAL, "egress.json")
    if not os.path.exists(path):
        return "declared: the API makes no outbound network calls (not measured)"
    e = json.load(open(path))
    return (f"measured {e['measured_at']}: {len(e['non_loopback_connections'])} non-loopback connections of the API process "
            f"in {e['samples']} socket samples while scoring {e['payments_scored_during_check']} payments (eval/egress.json)")

@app.get("/system")
def system():
    cpu = open("/proc/cpuinfo").read() if os.path.exists("/proc/cpuinfo") else ""
    typ = ""
    if os.path.exists("/proc/sysinfo"):
        typ = next((l.split(":")[1].strip() for l in open("/proc/sysinfo") if l.startswith("Type:")), "")
    return {"arch": platform.machine(), "byteorder": sys.byteorder, "python": platform.python_version(),
            "nnpa": "nnpa" in cpu, "machine_type": typ, "cpus": os.cpu_count(), "data_egress": "none",
            "data_egress_basis": egress_basis(),
            "inference": "CPU (XGBoost). NNPA is not used by this model.",
            "model": "XGBoost (MuleTrace network model C)", "features": len(FEATS),
            "flag_threshold": round(FLAG, 4), "hold_threshold": round(HOLD, 4),
            "stream_time": fmt_min(last_t[0]) if last_t[0] else None,
            "auth": "token" if TOKEN else "none (bind to 127.0.0.1 and use an SSH tunnel)",
            "simulated": True}

@app.post("/score", dependencies=[Depends(require_token)])
def score(x: Txn):
    try:
        return score_payment(x.model_dump())
    except Rejected as e:
        raise HTTPException(e.status, e.detail)

@app.get("/recent", dependencies=[Depends(require_token)])
def get_recent(limit: int = 50):
    return list(recent)[:max(1, min(limit, 300))]

ALERT_COLS = "id,txn_id,ts,src,dst,amount,score,decision,reasons,explanations,status,currency,fmt,note,acted_at,created_at"

def _rows(cur):
    cols = [c[0] for c in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    for a in out:
        a["reasons"] = json.loads(a["reasons"] or "[]")
        a["explanations"] = json.loads(a["explanations"] or "[]")
        a["decision"] = LEGACY.get(a["decision"], a["decision"])
        a["simulated"] = True
        a["recommendation"] = RECOMMENDATION.get(a["decision"], "")
    return out

@app.get("/alerts", dependencies=[Depends(require_token)])
def alerts(limit: int = 50, status: str = "open", decision: str = "all", sort: Literal["risk", "time"] = "risk"):
    q, args = "SELECT " + ALERT_COLS + " FROM alerts WHERE 1=1", []
    if status != "all":
        q += " AND status=?"; args.append(status)
    decision = LEGACY.get(decision, decision)
    if decision in ("HOLD", "FLAG"):
        q += " AND decision IN (?,?)"; args += [decision, {"FLAG": "REVIEW"}.get(decision, decision)]
    q += (" ORDER BY score DESC, id DESC" if sort == "risk" else " ORDER BY ts DESC, id DESC") + " LIMIT ?"
    args.append(max(1, min(limit, 500)))
    with db_lock:
        return _rows(db.execute(q, args))

@app.get("/alerts/{alert_id}", dependencies=[Depends(require_token)])
def alert(alert_id: int):
    with db_lock:
        rows = _rows(db.execute("SELECT " + ALERT_COLS + " FROM alerts WHERE id=?", (alert_id,)))
    if not rows:
        raise HTTPException(404, "alert not found")
    return rows[0]

class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["confirm", "dismiss", "escalate", "open"]
    note: str = Field("", max_length=500)
    analyst: str = Field("analyst", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9 _.\-]+$")

@app.post("/alerts/{alert_id}/action", dependencies=[Depends(require_token)])
def action(alert_id: int, a: Action):
    now = time.time()
    with db_lock, db:               # status change and audit row commit together or not at all
        row = db.execute("SELECT status FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if not row:
            raise HTTPException(404, "alert not found")
        db.execute("UPDATE alerts SET status=?, note=?, acted_at=? WHERE id=?", (a.action, a.note, now, alert_id))
        cur = db.execute("INSERT INTO audit_log(alert_id,action,from_status,to_status,analyst,note,created_at) "
                         "VALUES(?,?,?,?,?,?,?)", (alert_id, a.action, row[0], a.action, a.analyst, a.note, now))
    log.info(json.dumps({"event": "analyst_action", "alert_id": alert_id, "action": a.action,
                         "from": row[0], "analyst": a.analyst, "audit_id": cur.lastrowid}))
    return {"id": alert_id, "status": a.action, "from_status": row[0], "analyst": a.analyst,
            "audit_id": cur.lastrowid, "simulated": True,
            "detail": "Decision recorded in the audit log. No payment was actually held, released or reported."}

@app.get("/alerts/{alert_id}/audit", dependencies=[Depends(require_token)])
def audit(alert_id: int):
    with db_lock:
        if not db.execute("SELECT 1 FROM alerts WHERE id=?", (alert_id,)).fetchone():
            raise HTTPException(404, "alert not found")
        cur = db.execute("SELECT id,alert_id,action,from_status,to_status,analyst,note,created_at "
                         "FROM audit_log WHERE alert_id=? ORDER BY id", (alert_id,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

@app.get("/graph/{account}", dependencies=[Depends(require_token)])
def graph(account: str, limit: int = 25):
    with lock:
        since = last_t[0] - state.win      # only the last hour
        inn = [e for e in state.inn.get(account, []) if e[0] >= since]
        out = [e for e in state.out.get(account, []) if e[0] >= since]
    def top(items):   # merge repeat payments, keep the biggest flows
        agg = {}
        for t, other, amt in items:
            e = agg.setdefault(other, {"amount": 0.0, "count": 0, "t": t})
            e["amount"] += amt; e["count"] += 1; e["t"] = max(e["t"], t)
        return sorted(agg.items(), key=lambda kv: -kv[1]["amount"])[:limit], len(agg)
    tin, n_in = top(inn)
    tout, n_out = top(out)
    nodes = {account: {"id": account, "role": "focus"}}
    edges = []
    for other, e in tin:
        nodes.setdefault(other, {"id": other, "role": "sender"})
        edges.append({"from": other, "to": account, **e})
    for other, e in tout:
        nodes.setdefault(other, {"id": other, "role": "receiver"})
        edges.append({"from": account, "to": other, **e})
    return {"account": account, "nodes": list(nodes.values()), "edges": edges,
            "senders_total": n_in, "receivers_total": n_out,
            "in_amount": round(sum(e[2] for e in inn), 2), "in_count": len(inn),
            "out_amount": round(sum(e[2] for e in out), 2), "out_count": len(out)}

@app.get("/stats")
def get_stats():
    with stats_lock:
        s = dict(stats)
        now = time.time()
        s["per_sec"] = round(sum(1 for t in ticks if t >= now - 10) / 10, 1)
        recent_ms = sorted(lat_ms)
    s["avg_ms"] = round(s["ms_total"] / s["scored"], 3) if s["scored"] else 0
    s["p50_ms"] = round(recent_ms[len(recent_ms) // 2], 3) if recent_ms else None
    s["p95_ms"] = round(recent_ms[int(len(recent_ms) * 0.95)], 3) if recent_ms else None
    with db_lock:
        s["by_status"] = dict(db.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall())
    s["replay"] = dict(replay)
    s["stream_time"] = fmt_min(last_t[0]) if last_t[0] else None
    s["accounts_tracked"] = len(state.seen)         # distinct accounts the flow memory has seen
    s["uptime_s"] = round(now - START)
    return s

@app.get("/metrics")
def metrics():
    try:
        return json.load(open(os.path.join(EVAL, "metrics.json")))
    except FileNotFoundError:
        raise HTTPException(404, "eval/metrics.json not found - run model/train.py")

EVIDENCE_FILES = {"metrics": "metrics.json", "report": "report.json", "metrics_shuf": "metrics_shuf.json",
                  "report_shuf": "report_shuf.json",
                  "latency": "latency.json", "environment": "environment.json"}

@app.get("/evidence")
def evidence():
    """Result files from eval/ as written by train.py and bench/latency.py; null when a file does not exist."""
    out = {}
    for key, name in EVIDENCE_FILES.items():
        path = os.path.join(EVAL, name)
        out[key] = json.load(open(path)) if os.path.exists(path) else None
    if out["environment"]:
        out["environment"].pop("pip_freeze", None)
    return out

@app.post("/replay/start", dependencies=[Depends(require_token)])
def replay_start(r: ReplayReq):
    global _replay_thread, _test
    with replay_lock:               # at most one active stream
        if _replay_thread is not None and _replay_thread.is_alive():
            if _stop.is_set():
                _replay_thread.join(timeout=2)      # a stop is in progress: let it finish
            if _replay_thread.is_alive():
                raise HTTPException(409, "a payment stream is already running; stop it first")
        if _test is None:
            _test = pd.read_pickle(os.path.join(DATA, "test.pkl"))
            replay["total"] = len(_test)
        if replay["pos"] >= len(_test):
            raise HTTPException(409, "all test payments have been replayed; restart the server to replay again")
        _stop.clear()
        replay.update(running=True, speed=r.speed, error=None)
        _replay_thread = threading.Thread(target=_replay_loop, args=(r.n, r.speed), daemon=True)
        _replay_thread.start()
        return dict(replay)

@app.post("/replay/stop", dependencies=[Depends(require_token)])
def replay_stop():
    _stop.set()
    t = _replay_thread
    if t is not None:
        t.join(timeout=2)
    return dict(replay)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("MULETRACE_HOST", "127.0.0.1"), port=int(os.environ.get("MULETRACE_PORT", "8000")))
