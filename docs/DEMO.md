# MuleTrace 3-minute demo

Everything runs on the LinuxONE VM, bound to 127.0.0.1. You reach it through an SSH tunnel. HOLD and every analyst action are **simulated**: no money moves.

## Pre-demo checklist (T-10 min)

1. **Rotate the token and start fresh** (on the VM). This stops the old server, empties alerts.db and starts uvicorn on 127.0.0.1:8000 in tmux `mt`:
   ```bash
   ssh -i <your-key.pem> linux1@<vm-ip> 'cd ~/muletrace && git pull -q && bash scripts/demo_start.sh --rotate-token'
   ```
2. **Read the token** (it is never printed by the script): `ssh -i <your-key.pem> linux1@<vm-ip> 'cut -d= -f2 ~/.muletrace.env'`
3. **Open the tunnel** on your laptop: `ssh -i <your-key.pem> -N -L 8000:127.0.0.1:8000 linux1@<vm-ip>`
4. **Open** `http://localhost:8000/?token=<token>`. The top bar should show **● LIVE** and **IBM z17 · s390x**. Set **Analyst** to your name.
5. **Warm up:** on Live, start the stream at 200/s for about 20 s, stop it, then on **Cases** press **★ Best ring to show** and check that the graph has flows. Then run the reset (below) so the real demo starts clean, or keep this state if you prefer a pre-filled queue.

## Reset (keeps the token)

```bash
ssh -i <your-key.pem> linux1@<vm-ip> 'bash ~/muletrace/scripts/demo_reset.sh'
```

## Script

| Time | Say | Click |
|---|---|---|
| 0:00 | "Mule accounts move stolen money away from scam victims within minutes. Each payment looks normal; the ring doesn't." | Live page is open |
| 0:20 | "This runs on an IBM z17, s390x, with no outbound data. The on-chip AI accelerator is present; our model runs on the CPU." | **System**: point at Machine, Architecture, NNPA "detected · model runs on CPU", Outbound data "none" |
| 0:40 | "We replay 400,000 payments the model never saw, in time order." | **Live** → speed **200/s** → **▶ Start stream**. Point at the decision-time p50 (about 1 ms), the FLAG/HOLD counters, and the feed |
| 1:20 | "Here is the strongest ring right now. The reasons are the ring patterns first, then the model's own signals, each saying whether it raises or lowers risk." | **Cases** → **★ Best ring to show** (or click a card in the *Latest FLAG/HOLD* strip on Live). Point at the simulated-recommendation banner and the graph; click one payee node to expand it; hover an edge for amount/time. Scroll to Ring patterns / Network signals / Payment context |
| 2:00 | "A human decides, and it's on the record." | Type a note → **Confirm laundering** → the audit timeline shows "confirm by <you>". Point at **SIMULATED · recorded in audit log** |
| 2:20 | "Our headline is the conservative one: with payment order shuffled inside each minute, MuleTrace still ranks laundering far better than a transaction-only model and catches more of it. The standard run is only an upper bound. About 1 in 20 flags is laundering; a person decides." | **■ Stop** the stream (Live), then **Evidence**: point at the *Headline (conservative)* tiles (numbers come from eval/metrics_shuf.json), then the upper-bound table, latency and limits |
| 2:45 | "MuleTrace complements national efforts like MuleHunter.AI: real-time, explainable, auditable, on IBM Z." | Close |

## Fallbacks

- **Stream won't start (409 "all test payments replayed"):** run the reset command.
- **Best ring says no flows:** the stream has not run recently; start it for 20 s, stop, press the button again.
- **Top bar shows OFFLINE:** the tunnel dropped. Re-run the tunnel command and press **Retry**.
- **Actions return 401:** paste the token into the yellow banner, or reopen with `?token=`.
- **No HOLD in the feed yet:** open **Cases** and filter **⏸ HOLD**.
- **VM unreachable:** open `web/index.html?demo=1` locally. It is clearly labelled **DEMO · not live** and shows only the recorded sample. Say so out loud.
