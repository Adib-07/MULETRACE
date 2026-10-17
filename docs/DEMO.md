# MuleTrace 3-minute demo

## Start (on the LinuxONE VM)

```bash
ssh -i ~/.ssh/muletracekey1.pem linux1@<vm-ip>
tmux kill-session -t api 2>/dev/null                      # stop any old server
cd ~/muletrace && mv alerts.db alerts.db.bak-$(date +%s) 2>/dev/null; rm -f alerts.db-wal alerts.db-shm
tmux new -d -s api 'source ~/venv/bin/activate && cd ~/muletrace && \
  MULETRACE_TOKEN=$(cat ~/.muletrace_token) python -m uvicorn api.main:app --host 127.0.0.1 --port 8000'
sleep 10 && curl -s 127.0.0.1:8000/health                  # {"status":"ok",...}
cat ~/.muletrace_token                                      # the console token
```

On your laptop:

```bash
ssh -i ~/.ssh/muletracekey1.pem -N -L 8000:127.0.0.1:8000 linux1@<vm-ip>
# open http://localhost:8000/?token=<token>
```

## Pre-demo checklist

- [ ] VM up, `curl 127.0.0.1:8000/health` returns ok, tunnel open, console pill says **LIVE**
- [ ] Fresh `alerts.db` (server restarted after moving the old one aside). The stream starts at the beginning of the test set.
- [ ] Speed set to **50/s**; analyst name typed in (Investigate tab)
- [ ] Backup: if the API is unreachable, open `http://localhost:8000/?demo=1` (clearly labelled demo data) or show `eval/report.md`

## Script

| Time | Say / do |
|---|---|
| 0:00 | "Scam victims' money is moved through chains of mule accounts within minutes. Each payment looks normal; the ring doesn't." |
| 0:20 | **IBM Z System** tab: s390x, IBM z17 (type 9175), big-endian, NNPA present (model runs on CPU today), no outbound data. |
| 0:40 | **Live Monitor** → **Start stream** at 50/s. Point at PASS/FLAG/HOLD counts and the ~1 ms average decision time. Tick "flagged only". |
| 1:20 | Click a **HOLD** row → case: ring reasons first, then the top 3 model signals with their values. Point at the flow graph (payers → sender → receiver → payees). |
| 2:00 | Click **Confirm laundering**. The audit history shows "confirm by <name>". Point at the **SIMULATED — recommendation only** label: no payment was actually held. |
| 2:20 | **Model Results**: C vs transaction-only vs rules vs network-only. Say it straight: "about 1 in 20 flags is laundering, so a human decides. Shuffling same-minute order lowers PR-AUC to 0.137, still 13× the baseline." |
| 2:45 | Close: "Real-time, explainable, on-platform, and every decision is a human's, on the record." **Stop** the stream. |

## If something goes wrong

- **Pill says API OFFLINE:** the tunnel dropped. Re-run the `ssh -N -L` command and press **Retry**.
- **Start says "already running" or "all test payments replayed":** restart the server with the start block above (fresh DB).
- **401 on actions:** the token is missing. Reopen `/?token=<token>`.
- **No HOLD yet:** wait about 30 s at 50/s, or open any FLAG case. The steps are the same.
