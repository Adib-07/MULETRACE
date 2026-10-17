# MuleTrace 3-minute demo

Everything runs on the LinuxONE VM, bound to 127.0.0.1. You reach it through an SSH tunnel. HOLD and every analyst action are **simulated**: no money moves.

## Pre-demo checklist (T-10 min)

1. **VM up and server running:** `ssh -i <your-key.pem> linux1@<vm-ip> 'curl -s 127.0.0.1:8000/health'` should print `{"status":"ok",...}`.
2. **Fresh state:** run the reset command below. It gives an empty case queue and a stream at the start of the test set.
3. **Tunnel open** on your laptop: `ssh -i <your-key.pem> -N -L 8000:127.0.0.1:8000 linux1@<vm-ip>`
4. **Token:** `ssh -i <your-key.pem> linux1@<vm-ip> 'cat ~/.muletrace_token'`. Open `http://localhost:8000/?token=<token>`. The top bar should show **● LIVE** and **IBM z17 · s390x**.
5. Set **Analyst** (top right) to your name. Close other tabs. Zoom the browser to 100–110%.

## Reset (fresh alerts.db, server restart)

```bash
ssh -i <your-key.pem> linux1@<vm-ip>
tmux kill-session -t api; cd ~/muletrace && rm -f alerts.db alerts.db-wal alerts.db-shm
tmux new -d -s api "source ~/venv/bin/activate && cd ~/muletrace && MULETRACE_TOKEN=\$(cat ~/.muletrace_token) python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 2>&1 | tee -a server.log"
sleep 10; curl -s 127.0.0.1:8000/health
```

## Script

| Time | Say | Click |
|---|---|---|
| 0:00 | "Mule accounts move stolen money away from scam victims within minutes. Each payment looks normal; the ring doesn't." | Live page is open |
| 0:20 | "This runs on an IBM z17, s390x, with no outbound data. The on-chip AI accelerator is present; our model runs on the CPU." | **System**: point at Machine, Architecture, NNPA "detected · model runs on CPU", Outbound data "none" |
| 0:40 | "We replay 400,000 payments the model never saw, in time order." | **Live** → speed **200/s** → **▶ Start stream**. Point at the decision-time p50 (about 1 ms), the FLAG/HOLD counters, and the feed |
| 1:20 | "Open a HOLD. The reasons are the ring patterns plus the model's own top signals, with the values." | Click a **⏸ HOLD** row in the feed (it opens Cases). Point at the simulated-recommendation banner, the reasons, the model signals and the money-flow graph (hover an edge, press **⤢ Fit graph**) |
| 2:00 | "A human decides, and it's on the record." | Type a note → **Confirm laundering** → the audit timeline shows "confirm by <you>". Point at **SIMULATED · recorded in audit log** |
| 2:20 | "Our headline is the conservative one: with payment order shuffled inside each minute, MuleTrace still ranks laundering far better than a transaction-only model and catches more of it. The standard run is only an upper bound. About 1 in 20 flags is laundering; a person decides." | **■ Stop** the stream (Live), then **Evidence**: point at the *Headline (conservative)* tiles (numbers come from eval/metrics_shuf.json), then the upper-bound table, latency and limits |
| 2:45 | "MuleTrace complements national efforts like MuleHunter.AI: real-time, explainable, auditable, on IBM Z." | Close |

## Fallbacks

- **Stream won't start (409 "all test payments replayed"):** run the reset command.
- **Top bar shows OFFLINE:** the tunnel dropped. Re-run the tunnel command and press **Retry**.
- **Actions return 401:** paste the token into the yellow banner, or reopen with `?token=`.
- **No HOLD in the feed yet:** open **Cases** and filter **⏸ HOLD**.
- **VM unreachable:** open `web/index.html?demo=1` locally. It is clearly labelled **DEMO · not live** and shows only the recorded sample. Say so out loud.
