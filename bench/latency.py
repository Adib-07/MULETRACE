"""Latency benchmark. Run from the repo root.

  python bench/latency.py inproc 20000          # score_payment() in-process on the first N test payments
  python bench/latency.py http 50 30 [offset]   # HTTP POST /score at a fixed rate (req/s) for S seconds

HTTP mode needs a running server (MULETRACE_URL, default http://127.0.0.1:8000; MULETRACE_TOKEN if set) whose
stream is at the start of the test set. Results are merged into eval/latency.json with machine info.
"""
import http.client, json, os, platform, sys, tempfile, time
from urllib.parse import urlparse
import numpy as np, pandas as pd

def pct(ms):
    a = np.asarray(ms)
    return {"n": int(a.size), "mean": round(float(a.mean()), 3), "p50": round(float(np.percentile(a, 50)), 3),
            "p95": round(float(np.percentile(a, 95)), 3), "p99": round(float(np.percentile(a, 99)), 3),
            "max": round(float(a.max()), 3)}

def machine():
    typ = ""
    if os.path.exists("/proc/sysinfo"):
        typ = next((l.split(":")[1].strip() for l in open("/proc/sysinfo") if l.startswith("Type:")), "")
    cpu = open("/proc/cpuinfo").read() if os.path.exists("/proc/cpuinfo") else ""
    return {"arch": platform.machine(), "machine_type": typ, "nnpa_present": "nnpa" in cpu, "cpus": os.cpu_count(),
            "python": platform.python_version(), "node": platform.node(), "inference": "CPU (XGBoost)"}

def rows(df):
    for r in df.itertuples(index=False):
        yield {"txn_id": str(r.txn_id), "ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": float(r.amount),
               "currency": r.currency, "cur_recv": r.cur_recv, "fmt": r.fmt}

def inproc(n):
    os.environ["MULETRACE_DB"] = os.path.join(tempfile.mkdtemp(), "bench.db")
    os.environ.setdefault("MULETRACE_LOG_LEVEL", "WARNING")
    sys.path.insert(0, ".")
    from api import main
    test = pd.read_pickle(os.path.join(main.DATA, "test.pkl")).head(n)
    ms, flagged = [], []
    for x in rows(test):
        t0 = time.perf_counter()
        out = main.score_payment(x)
        dt = (time.perf_counter() - t0) * 1000
        ms.append(dt)
        if out["decision"] != "PASS":
            flagged.append(dt)
    return {"what": "score_payment() in-process: features + XGBoost + (FLAG/HOLD) pred_contribs + SQLite insert",
            "payments": n, "all": pct(ms), "flag_or_hold_only": pct(flagged) if flagged else None}

def http_run(rate, seconds, offset=0):
    url = urlparse(os.environ.get("MULETRACE_URL", "http://127.0.0.1:8000"))
    headers = {"Content-Type": "application/json"}
    if os.environ.get("MULETRACE_TOKEN"):
        headers["X-MuleTrace-Token"] = os.environ["MULETRACE_TOKEN"]
    test = pd.read_pickle("data/test.pkl").iloc[offset: offset + int(rate * seconds) + 10]
    conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=10)
    rtt, server, errors, sent = [], [], {}, 0
    gap, start = 1.0 / rate, time.perf_counter()
    for i, x in enumerate(rows(test)):
        due = start + i * gap
        if due - start >= seconds:
            break
        wait = due - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        t0 = time.perf_counter()
        try:
            conn.request("POST", "/score", json.dumps(x), headers)
            resp = conn.getresponse()
            body = resp.read()
            rtt.append((time.perf_counter() - t0) * 1000)
            if resp.status == 200:
                server.append(json.loads(body)["latency_ms"])
            else:
                errors[str(resp.status)] = errors.get(str(resp.status), 0) + 1
        except Exception as e:      # count and keep going; reported in the result file
            errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1
            conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=10)
        sent += 1
    elapsed = time.perf_counter() - start
    return {"what": "HTTP POST /score, one keep-alive client, fixed send rate", "target_rate": rate,
            "seconds": round(elapsed, 2), "sent": sent, "achieved_rate": round(sent / elapsed, 1),
            "errors": errors, "client_round_trip_ms": pct(rtt) if rtt else None,
            "server_latency_ms": pct(server) if server else None}

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "inproc":
        result = inproc(int(sys.argv[2]) if len(sys.argv) > 2 else 20000)
    else:
        result = http_run(float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    result["measured_at"] = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    result["command"] = "python bench/latency.py " + " ".join(sys.argv[1:])
    out = json.load(open("eval/latency.json")) if os.path.exists("eval/latency.json") else {}
    out["machine"] = machine()
    out["inproc" if mode == "inproc" else f"http_{sys.argv[2]}rps"] = result
    json.dump(out, open("eval/latency.json", "w"), indent=2)
    print(json.dumps(result, indent=2))
