#!/usr/bin/env bash
# Egress check: while the server scores N replayed payments, sample every socket of the uvicorn process
# (ss + lsof) and record any connection whose peer is not loopback. Writes eval/egress.json.
# Usage (on the VM, repo root): PORT=8000 TOKEN_FILE=~/.muletrace.env N=2000 bash bench/egress_check.sh
set -euo pipefail
PORT="${PORT:-8000}"; N="${N:-2000}"; SPEED="${SPEED:-100}"; OUT="${OUT:-eval/egress.json}"
TOKEN="$(sed 's/^MULETRACE_TOKEN=//' "${TOKEN_FILE:-$HOME/.muletrace.env}")"
PID="$(ss -tlnpH "sport = :$PORT" | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"
[ -n "$PID" ] || { echo "no process listening on :$PORT" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
H=(-H "Content-Type: application/json" -H "X-MuleTrace-Token: $TOKEN")
before="$(curl -s "http://127.0.0.1:$PORT/stats" | python3 -c 'import sys,json;print(json.load(sys.stdin)["scored"])')"
curl -s -o /dev/null -X POST "${H[@]}" "http://127.0.0.1:$PORT/replay/start" -d "{\"n\":$N,\"speed\":$SPEED}"
t0=$(date +%s.%N); samples=0
while :; do
  ss -tunapH 2>/dev/null | grep "pid=$PID," >> "$TMP/ss.txt" || true
  lsof -a -p "$PID" -i -n -P 2>/dev/null | tail -n +2 >> "$TMP/lsof.txt" || true
  samples=$((samples + 1))
  running="$(curl -s "http://127.0.0.1:$PORT/stats" | python3 -c 'import sys,json;print(json.load(sys.stdin)["replay"]["running"])')"
  [ "$running" = "True" ] || break
  sleep 0.2
done
t1=$(date +%s.%N)
after="$(curl -s "http://127.0.0.1:$PORT/stats" | python3 -c 'import sys,json;print(json.load(sys.stdin)["scored"])')"
python3 - "$TMP" "$PID" "$PORT" "$samples" "$t0" "$t1" "$before" "$after" "$OUT" <<'PY'
import json, re, sys, time, platform
tmp, pid, port, samples, t0, t1, before, after, out = sys.argv[1:]
def peer_ok(addr):
    host = addr.rsplit(":", 1)[0].strip("[]")
    return host in ("*", "0.0.0.0", "::", "::1") or host.startswith("127.") or host.startswith("::ffff:127.")
ss = [l.split() for l in open(f"{tmp}/ss.txt") if l.strip()]
peers = sorted({(f[0], f[4], f[5]) for f in ss if len(f) >= 6})
bad_ss = [p for p in peers if not peer_ok(p[2])]
ls = [l.strip() for l in open(f"{tmp}/lsof.txt") if l.strip()]
names = sorted({re.split(r"\s+", l)[8] if len(re.split(r"\s+", l)) > 8 else l for l in ls})
bad_lsof = [n for n in names if "->" in n and not peer_ok(n.split("->")[1].split(" ")[0])]
res = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "host_arch": platform.machine(),
       "process": f"uvicorn pid {pid} (listening 127.0.0.1:{port})", "payments_scored_during_check": int(after) - int(before),
       "duration_s": round(float(t1) - float(t0), 1), "samples": int(samples), "sample_interval_s": 0.2,
       "method": "ss -tunap filtered by pid + lsof -a -p pid -i, sampled while replaying payments",
       "distinct_sockets_seen": [" ".join(p) for p in peers], "lsof_names_seen": names,
       "non_loopback_connections": sorted(set(map(str, bad_ss)) | set(bad_lsof))}
res["verdict"] = "no non-loopback connections observed" if not res["non_loopback_connections"] else "NON-LOOPBACK CONNECTIONS OBSERVED"
res["limits"] = "Sampling every 0.2 s can miss a connection shorter than the interval; the API code has no outbound network calls (grep)."
json.dump(res, open(out, "w"), indent=1); print(json.dumps({k: res[k] for k in ("payments_scored_during_check", "duration_s", "samples", "non_loopback_connections", "verdict")}))
PY
