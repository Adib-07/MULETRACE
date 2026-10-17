# MuleTrace final readiness (2026-10-18)

Team Quorvex · IBM Z Datathon 2026 · Real-Time AI for Critical Decisions. Fallback tag `v1-demo`; this state is tagged `v2-submission`.

## Verdict: CONDITIONALLY READY

The working demo, repo and evidence are in place. Conditions **met**:
- every automated check below passes on the LinuxONE VM
- the token is required for account data
- egress is measured
- restart persistence is proven
- every number traces to `eval/`

Conditions **still missing**, all of them human tasks:
- the Hack2Skill submission: deck, short description, demo video, team ID
- a decision on the reboot autostart (prepared, not applied)
- a decision on rewriting git history (a key **filename**, not a key, appears in an old commit)

## Commits in this pass

| Commit | Change |
|---|---|
| `ce99610` | Token required for `/alerts*`, `/graph`, `/recent`; public `/health /system /stats /evidence` carry no account IDs (tests) |
| `7e3bc4b` | `bench/egress_check.sh` + `eval/egress.json`; `/system` cites the measurement |
| `22f5f5c` | Real-server e2e: explanation order and restart persistence |
| `bf93ee3` | `bench/detection_delay.py` + `eval/detection_delay.json`; README/UI number check (`scripts/readme_results.py --check`, tamper test) |
| `13fc535` | Big-endian model consistency test; Snap ML retry recorded; LINUXONE.md + Trust panel |
| `1334e1c` | `scripts/autostart.sh` (crontab `@reboot`, not applied) |
| `c58b27c` | a11y fix (listbox role), e2e no-token check, screenshots |

## Checks

| Check | Result | Command |
|---|---|---|
| Unit/API/pipeline/consistency/README-number tests on the VM | PASS: 42 passed | `python -m pytest -q tests` |
| Real-server e2e (real model, 2M payments): token out of URL; Overview live; start; tour; Best ring; node expansion (21→23 accounts); explanations order; keyboard Confirm + audit; no-token view; keyboard nav; Evidence/System; back/forward; 390px; restart → status and audit identical; 0 console errors | PASS: 14 checks | `MULETRACE_RESTART_CMD=… python tests/e2e/e2e_real.py` |
| Reads without token → 401, with → 200 (`/alerts`, `/alerts/1`, `/alerts/1/audit`, `/graph/x`, `/recent`); public endpoints → 200 | PASS | `curl` on the VM |
| Writes without token → 401; foreign-origin CORS preflight refused (405); 0 allow-origin headers | PASS | `curl` |
| Token in server log | PASS: 0 occurrences (uvicorn runs `--no-access-log`) | `grep -c -F` |
| Egress while scoring 2,000 payments | PASS: 0 non-loopback connections, 75 samples, 20 s | `bench/egress_check.sh` |
| README/UI numbers vs `eval/` | PASS | `python scripts/readme_results.py --check` |
| Contrast | PASS: 30/30 pairs AA, min 5.02:1 | `python scripts/contrast_check.py` |
| Lighthouse accessibility | PASS: 100 on overview, live, cases, score, evidence, system | `npx lighthouse@12.2.1 --only-categories=accessibility` |
| Deploy: `demo_reset.sh` → `/health` ok, `/system` s390x/9175/auth token | PASS | `bash scripts/demo_reset.sh` |
| Listening sockets | PASS: only 127.0.0.1:8000 and SSH (plus the systemd DNS stub on loopback) | `ss -tlnp` |
| Secret scan (tree + all history) | PASS for keys, IPs and tokens. **Open:** the key filename appears 4× in history (commit `1b2bf28`), 0× in the tree | `git log --all -p \| grep` |
| Reboot resilience | BLOCKED: awaiting approval to run `bash scripts/autostart.sh --apply`. App restart with `--keep-db` is tested | – |

## Measured metrics (from `eval/`)

| Metric | Conservative (order-shuffled) | Standard (upper bound) |
|---|---:|---:|
| PR-AUC, MuleTrace C | 0.1369 (95% CI 0.104–0.186) | 0.2188 (0.175–0.264) |
| PR-AUC, transaction-only A | 0.0104 | 0.0094 |
| Recall C at ~1% review | 42.2% | 45.7% |
| Precision C | 4.8% (≈1 in 21) | 5.0% (≈1 in 20) |
| FP per 1,000 payments, C | 8.31 | 8.57 |
| P@100 / P@500 / P@1000, C | 0.47 / 0.15 / 0.096 | 0.74 / 0.218 / 0.133 |

| Other measurement | Value | Source |
|---|---|---|
| IBM-labelled attempts detected (start in test window) | 23 of 37 (62.2%), VERIFIED (100% pattern match) | `eval/detection_delay.json` |
| Detection delay (first payment → first FLAG/HOLD) | median 0 min, p90 587 min, max 1,063 min (standard model) | same |
| Decision latency in-process (20,000 payments) | p50 1.10 ms, p95 1.59 ms, p99 4.06 ms | `eval/latency.json` |
| HTTP `/score` at 50 req/s for 30 s | server p50 1.35 ms, p99 4.35 ms; 1,500 requests, 0 errors | same |
| Egress | 0 non-loopback connections | `eval/egress.json` |

## Scorecard (strict judge, before → after)

| Area | Max | Before | After | Evidence for the change |
|---|---:|---:|---:|---|
| Problem fit | 10 | 8 | 9 | time-to-detect on IBM-labelled attempts |
| Originality | 10 | 6 | 6 | unchanged |
| Technical depth | 15 | 11 | 12 | detection-delay evaluation, egress tooling, number check |
| IBM Z relevance | 15 | 7 | 9 | egress measured; big-endian round-trip test; Snap ML retry documented. NNPA still unused |
| E2E functionality | 10 | 9 | 10 | 14-check real-server e2e incl. restart persistence |
| Model evidence | 10 | 7 | 8 | detection delay; conservative headline everywhere. Still one split |
| UX & explainability | 10 | 8 | 9 | Lighthouse 100 on all pages; network signals before context |
| Security/privacy/oversight | 8 | 5 | 7 | token on account-data reads; egress measured. Shared token; key filename in history |
| Reliability/testing/deploy | 7 | 5 | 6 | restart persistence proven; reboot autostart not applied |
| Demo/reproducibility | 5 | 4 | 5 | scripts, DEMO.md, numbers regenerated from files |
| **Total** | 100 | **70** | **81** | |

## Remaining defects and risks

- **Single shared token**: there are no per-user accounts. The analyst name is self-declared (recorded, not authenticated).
- **Key filename in git history** (`1b2bf28`): not a secret, but cleaning it needs a history rewrite. Not done without your approval.
- **No reboot autostart yet**: after a VM reboot, run `bash ~/muletrace/scripts/demo_start.sh --keep-db` (or approve `autostart.sh --apply`).
- **Model evidence**: one time split, one seed. Precision is about 5%, so roughly 19 of 20 flags are false alarms. The standard-run numbers partly depend on within-minute file order.
- **Detection delay** uses the standard model, covers only the 37 attempts that start in the test window (68 of 396 laundering rows), and has minute resolution.
- **Scale**: tested at 50 req/s on 3 vCPUs, single process, in-memory state. Higher rates are not measured.
- **NNPA**: present but not used. Snap ML could not import model C, and a retrained Snap ML model scored at chance level.
- **Egress sampling** (0.2 s) could miss a connection shorter than the interval. The code has no outbound calls.

## Mocked / simulated

- SIMULATED: HOLD (no payment is paused); Confirm/Escalate/Dismiss (recorded in the audit log only); the payment stream (a replay of IBM's synthetic test set).
- MOCKED (opt-in demo mode `?demo=1` only, labelled): recorded alerts from the first model; no metrics.
- VERIFIED on the VM: everything in the Checks table.

## Manual checks left for the team

1. Hack2Skill: team ID, the submission form, and the deadline (18 Oct 2026 22:00 IST, as you stated; we could not read the rules page).
2. Deck and short description: use README TL;DR and Results (conservative headline first).
3. Demo video: follow `docs/DEMO.md`; rotate the token first (`demo_start.sh --rotate-token`).
4. Decide on reboot autostart and the git-history rewrite.
5. Confirm all 6 team members are registered.
