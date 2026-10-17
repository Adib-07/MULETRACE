import json, platform, sqlite3, sys, threading, time
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from xgboost import XGBClassifier
sys.path.insert(0, "model")
from features import FlowState, ALL_FEATURES, reasons

app = FastAPI(title="MuleTrace")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
stats = {"scored": 0, "review": 0, "hold": 0, "ms_total": 0.0}

db = sqlite3.connect("alerts.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, txn_id TEXT,
  ts INTEGER, src TEXT, dst TEXT, amount REAL, score REAL, decision TEXT,
  reasons TEXT, status TEXT DEFAULT 'open', truth INTEGER)""")
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
    print("Warm-up done (past history loaded) in", round(time.time() - t0), "s", flush=True)
warm_up()

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

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/system")
def system():
    cpu = open("/proc/cpuinfo").read()
    typ = next((l.split(":")[1].strip() for l in open("/proc/sysinfo") if l.startswith("Type:")), "")
    return {"arch": platform.machine(), "byteorder": sys.byteorder, "python": platform.python_version(),
            "nnpa": "nnpa" in cpu, "machine_type": typ, "data_egress": "none"}

@app.post("/score")
def score(x: Txn):
    t0 = time.perf_counter()
    t = tmin(x.ts)
    with lock:
        f = state.features(t, x.src, x.dst, x.amount, x.currency, x.cur_recv, x.fmt)
        state.update(t, x.src, x.dst, x.amount)
    row = pd.DataFrame([[f[k] for k in FEATS]], columns=FEATS, dtype="float32")
    p = float(model.predict_proba(row)[0, 1])
    decision = "HOLD" if p >= HOLD else "REVIEW" if p >= FLAG else "ALLOW"
    why = (reasons(f) or extra_reasons(f, p)) if decision != "ALLOW" else []
    ms = (time.perf_counter() - t0) * 1000
    stats["scored"] += 1; stats["ms_total"] += ms
    if decision != "ALLOW":
        stats[decision.lower()] += 1
        db.execute("INSERT INTO alerts(txn_id,ts,src,dst,amount,score,decision,reasons,truth) VALUES(?,?,?,?,?,?,?,?,?)",
                   (x.txn_id, t, x.src, x.dst, x.amount, p, decision, json.dumps(why), x.label))
        db.commit()
    return {"txn_id": x.txn_id, "score": round(p, 4), "decision": decision, "reasons": why, "latency_ms": round(ms, 2)}

@app.get("/alerts")
def alerts(limit: int = 50, status: str = "open"):
    cur = db.execute("SELECT id,txn_id,ts,src,dst,amount,score,decision,reasons,status,truth FROM alerts "
                     "WHERE status=? ORDER BY score DESC, id DESC LIMIT ?", (status, limit))
    cols = [c[0] for c in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    for a in out:
        a["reasons"] = json.loads(a["reasons"])
    return out

class Action(BaseModel):
    action: str

@app.post("/alerts/{alert_id}/action")
def action(alert_id: int, a: Action):
    if a.action not in ("confirm", "dismiss", "escalate"):
        raise HTTPException(400, "action must be confirm, dismiss or escalate")
    n = db.execute("UPDATE alerts SET status=? WHERE id=?", (a.action, alert_id)).rowcount
    db.commit()
    if not n:
        raise HTTPException(404, "alert not found")
    return {"id": alert_id, "status": a.action}

@app.get("/graph/{account}")
def graph(account: str):
    with lock:
        inn = list(state.inn.get(account, []))
        out = list(state.out.get(account, []))
    nodes = {account: {"id": account, "role": "focus"}}
    edges = []
    for t, other, amt in inn:
        nodes.setdefault(other, {"id": other, "role": "sender"})
        edges.append({"from": other, "to": account, "amount": amt, "t": t})
    for t, other, amt in out:
        nodes.setdefault(other, {"id": other, "role": "receiver"})
        edges.append({"from": account, "to": other, "amount": amt, "t": t})
    return {"nodes": list(nodes.values()), "edges": edges}

@app.get("/stats")
def get_stats():
    s = dict(stats)
    s["avg_ms"] = round(s["ms_total"] / s["scored"], 2) if s["scored"] else 0
    return s

def extra_reasons(f, p):
    out = []
    if f.get("self_txn"): out.append("Sender and receiver are the same account")
    if f.get("cross_cur"): out.append("Currency changes during the payment")
    if f.get("src_out_count", 0) >= 5: out.append("Sender made " + str(int(f["src_out_count"])) + " payments in the last hour")
    out.append("AI risk score " + str(round(p * 100)) + "/100, similar to known laundering")
    return out[:3]
