"""MuleTrace live API: scores payments in real time on IBM LinuxONE and serves the investigator console."""
import json, os, platform, sqlite3, sys, threading, time
from collections import deque
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from xgboost import XGBClassifier
sys.path.insert(0, "model")
from features import FlowState, ALL_FEATURES, FORMATS, reasons

app = FastAPI(title="MuleTrace", version="1.0.0",
              description="Real-time money-mule ring detection on IBM LinuxONE")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- model + thresholds ----------
meta = json.load(open("models/meta.json"))
FEATS = meta.get("features", ALL_FEATURES)
def pick(word):
    for k, v in meta.items():
        if word in k.lower().replace("threshold", "") and isinstance(v, (int, float)):
            return float(v)
    raise SystemExit("meta.json has no " + word + " threshold: " + str(list(meta)))
FLAG, HOLD = pick("flag"), pick("hold")

model = XGBClassifier()
model.load_model("models/model_c.json")
state = FlowState()
lock = threading.Lock()
db_lock = threading.Lock()
START = time.time()
stats = {"scored": 0, "allow": 0, "review": 0, "hold": 0, "ms_total": 0.0}
last_t = [0]                        # latest payment time seen (minutes)
recent = deque(maxlen=300)          # last decisions, for the live feed
ticks = deque(maxlen=5000)          # timestamps of decisions, for payments/second

# ---------- alert store ----------
db = sqlite3.connect("alerts.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, txn_id TEXT,
  ts INTEGER, src TEXT, dst TEXT, amount REAL, score REAL, decision TEXT,
  reasons TEXT, status TEXT DEFAULT 'open', truth INTEGER)""")
for col in ("currency TEXT", "fmt TEXT", "note TEXT", "acted_at REAL", "created_at REAL"):
    try:
        db.execute("ALTER TABLE alerts ADD COLUMN " + col)
    except sqlite3.OperationalError:
        pass
db.commit()

def tmin(ts):
    return int(pd.Timestamp(ts).value // 60_000_000_000)

def warm_up():
    t0 = time.time()
    for name in ["train", "valid"]:
        df = pd.read_pickle("data/" + name + ".pkl")
        ts = df["ts"].values.astype("datetime64[m]").astype("int64")
        for t, s, d, a in zip(ts, df["src"].values, df["dst"].values, df["amount"].values):
            state.update(int(t), s, d, float(a))
        last_t[0] = max(last_t[0], int(ts.max()))
    print("Warm-up done (past history loaded) in", round(time.time() - t0), "s", flush=True)
warm_up()

def extra_reasons(f, p, fmt):
    out = []
    if f.get("self_txn"): out.append("Sender and receiver are the same account")
    if f.get("cross_cur"): out.append("Currency changes during the payment")
    if f.get("src_out_count", 0) >= 5: out.append("Sender made " + str(int(f["src_out_count"])) + " payments in the last hour")
    if fmt == "ACH": out.append("Paid by ACH, the payment type most used in known laundering cases")
    out.append("AI risk score " + str(round(p * 100)) + "/100, similar to known laundering")
    return out[:3]

# ---------- scoring ----------
def score_payment(x: dict):
    t0 = time.perf_counter()
    t = tmin(x["ts"])
    amount = float(x["amount"])
    with lock:
        f = state.features(t, x["src"], x["dst"], amount, x["currency"], x["cur_recv"], x["fmt"])
        state.update(t, x["src"], x["dst"], amount)
        last_t[0] = max(last_t[0], t)
        row = pd.DataFrame([[f[k] for k in FEATS]], columns=FEATS, dtype="float32")
        p = float(model.predict_proba(row)[0, 1])
    decision = "HOLD" if p >= HOLD else "REVIEW" if p >= FLAG else "ALLOW"
    why = (reasons(f) or extra_reasons(f, p, x["fmt"])) if decision != "ALLOW" else []
    ms = (time.perf_counter() - t0) * 1000
    now = time.time()
    stats["scored"] += 1; stats["ms_total"] += ms; stats[decision.lower()] += 1
    ticks.append(now)
    alert_id = None
    if decision != "ALLOW":
        with db_lock:
            cur = db.execute("INSERT INTO alerts(txn_id,ts,src,dst,amount,score,decision,reasons,truth,currency,fmt,created_at) "
                             "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                             (x.get("txn_id", ""), t, x["src"], x["dst"], amount, p, decision, json.dumps(why),
                              x.get("label"), x["currency"], x["fmt"], now))
            db.commit()
            alert_id = cur.lastrowid
    out = {"txn_id": x.get("txn_id", ""), "ts": str(x["ts"]), "src": x["src"], "dst": x["dst"], "amount": amount,
           "currency": x["currency"], "fmt": x["fmt"], "score": round(p, 4), "decision": decision,
           "reasons": why, "latency_ms": round(ms, 2), "alert_id": alert_id}
    recent.appendleft(out)
    return out

class Txn(BaseModel):
    txn_id: str = ""
    ts: str
    src: str
    dst: str
    amount: float
    currency: str = "US Dollar"
    cur_recv: str = "US Dollar"
    fmt: str = "ACH"
    label: int | None = None

# ---------- live replay (simulates a bank's payment stream) ----------
replay = {"running": False, "pos": 0, "total": 0, "speed": 0, "sent": 0}
_test = None
_stop = threading.Event()

def _replay_loop(n, speed):
    global _test
    if _test is None:
        _test = pd.read_pickle("data/test.pkl")
    replay["total"] = len(_test)
    end = min(replay["pos"] + n, len(_test))
    gap = 1.0 / speed
    nxt = time.perf_counter()
    while replay["pos"] < end and not _stop.is_set():
        r = _test.iloc[replay["pos"]]
        score_payment({"txn_id": str(r.txn_id), "ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": float(r.amount),
                       "currency": r.currency, "cur_recv": r.cur_recv, "fmt": r.fmt, "label": int(r.label)})
        replay["pos"] += 1; replay["sent"] += 1
        nxt += gap
        wait = nxt - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        else:
            nxt = time.perf_counter()   # running behind: go as fast as the machine allows
    replay["running"] = False

class ReplayReq(BaseModel):
    n: int = 5000
    speed: float = 50

# ---------- endpoints ----------
@app.get("/", include_in_schema=False)
def console():
    path = os.path.join("web", "index.html")
    if not os.path.exists(path):
        raise HTTPException(404, "web/index.html not found")
    return FileResponse(path)

@app.get("/health")
def health():
    return {"status": "ok", "uptime_s": round(time.time() - START)}

@app.get("/system")
def system():
    cpu = open("/proc/cpuinfo").read()
    typ = ""
    if os.path.exists("/proc/sysinfo"):
        typ = next((l.split(":")[1].strip() for l in open("/proc/sysinfo") if l.startswith("Type:")), "")
    return {"arch": platform.machine(), "byteorder": sys.byteorder, "python": platform.python_version(),
            "nnpa": "nnpa" in cpu, "machine_type": typ, "cpus": os.cpu_count(), "data_egress": "none",
            "model": "XGBoost (MuleTrace network model C)", "features": len(FEATS),
            "review_threshold": round(FLAG, 4), "hold_threshold": round(HOLD, 4)}

@app.post("/score")
def score(x: Txn):
    if x.amount <= 0:
        raise HTTPException(400, "amount must be greater than 0")
    if x.fmt not in FORMATS:
        raise HTTPException(400, "fmt must be one of " + ", ".join(FORMATS))
    try:
        tmin(x.ts)
    except Exception:
        raise HTTPException(400, "ts must be a date-time like 2022-09-03 10:15")
    return score_payment(x.model_dump())

@app.get("/recent")
def get_recent(limit: int = 50):
    return list(recent)[:max(1, min(limit, 300))]

ALERT_COLS = "id,txn_id,ts,src,dst,amount,score,decision,reasons,status,currency,fmt,note,acted_at,created_at"

def _rows(cur):
    cols = [c[0] for c in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    for a in out:
        a["reasons"] = json.loads(a["reasons"] or "[]")
    return out

@app.get("/alerts")
def alerts(limit: int = 50, status: str = "open", decision: str = "all"):
    q, args = "SELECT " + ALERT_COLS + " FROM alerts WHERE 1=1", []
    if status != "all":
        q += " AND status=?"; args.append(status)
    if decision in ("HOLD", "REVIEW"):
        q += " AND decision=?"; args.append(decision)
    q += " ORDER BY score DESC, id DESC LIMIT ?"; args.append(max(1, min(limit, 500)))
    with db_lock:
        return _rows(db.execute(q, args))

@app.get("/alerts/{alert_id}")
def alert(alert_id: int):
    with db_lock:
        rows = _rows(db.execute("SELECT " + ALERT_COLS + " FROM alerts WHERE id=?", (alert_id,)))
    if not rows:
        raise HTTPException(404, "alert not found")
    return rows[0]

class Action(BaseModel):
    action: str
    note: str = ""

@app.post("/alerts/{alert_id}/action")
def action(alert_id: int, a: Action):
    if a.action not in ("confirm", "dismiss", "escalate", "open"):
        raise HTTPException(400, "action must be confirm, dismiss, escalate or open")
    with db_lock:
        n = db.execute("UPDATE alerts SET status=?, note=?, acted_at=? WHERE id=?",
                       (a.action, a.note[:500], time.time(), alert_id)).rowcount
        db.commit()
    if not n:
        raise HTTPException(404, "alert not found")
    return {"id": alert_id, "status": a.action}

@app.get("/graph/{account}")
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
            "senders_total": n_in, "receivers_total": n_out}

@app.get("/stats")
def get_stats():
    s = dict(stats)
    s["avg_ms"] = round(s["ms_total"] / s["scored"], 2) if s["scored"] else 0
    now = time.time()
    s["per_sec"] = round(sum(1 for t in ticks if t >= now - 10) / 10, 1)
    with db_lock:
        s["by_status"] = dict(db.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall())
    s["replay"] = dict(replay)
    s["uptime_s"] = round(now - START)
    return s

@app.get("/metrics")
def metrics():
    try:
        return json.load(open("eval/metrics.json"))
    except FileNotFoundError:
        raise HTTPException(404, "eval/metrics.json not found - run model/train.py")

@app.post("/replay/start")
def replay_start(r: ReplayReq):
    if replay["running"]:
        return replay
    _stop.clear()
    replay.update(running=True, speed=max(1, min(r.speed, 500)))
    threading.Thread(target=_replay_loop, args=(max(1, r.n), replay["speed"]), daemon=True).start()
    return replay

@app.post("/replay/stop")
def replay_stop():
    _stop.set()
    return replay
