# MuleTrace final readiness (final submission pass, 2026-10-18)

Team Quorvex · IBM Z Datathon 2026 · Real-Time AI for Critical Decisions. Fallback tags: `v1-demo`, `v2-submission`, `v2.1-submission`. **This state: `v2.2-submission`.**

## Verdict: CONDITIONALLY READY

**Met:**
- Every automated check below passes on the LinuxONE VM and in the browser.
- Public judge mode is built and tested.
- The admin app is never exposed.
- Every number traces to `eval/`.

**Missing:**
1. **Public URL.** It needs your approval for three VM changes (firewall 80/443, `setcap` for Caddy, LinuxONE terms check) and then a verification from outside.
2. **Team-only work:** the demo video, deck, short description and Hack2Skill submission.
3. **Decisions:** reboot autostart, and the git-history key-filename cleanup.

## Changes in this pass

| Commit | Change |
|---|---|
| `61c45a3` | Cases list race fixed (a stale response could overwrite a newer filter); `tests/e2e/e2e_controls.py` clicks every control; unmeasured "act faster" claim removed; `requirements-optional.txt`, `requirements-dev.txt` |
| `ced3a43` | Judge mode (`MULETRACE_PUBLIC_DEMO=1`): public role, per-IP rate limits, 16 KB body cap, CSP with inline-script hashes and other security headers, `POST /demo/reset` (archives the DB; public once per 10 min); console banner and Reset button; `tests/test_public.py`, `tests/e2e/e2e_public.py` |
| `26b6258` | `deploy/Caddyfile`, `scripts/public_start.sh`; Caddy v2.11.7 s390x verified (SHA-512) in `~/bin` on the VM; static GitHub Pages fallback (MOCKED banner, evidence from `eval/`), `tests/e2e/e2e_static.py` |
| `a72414a` | README restructured for the public (all required sections); `scripts/check_links.py` |
| `9494985` | Screenshots from the final runs |

## Checks

| Check | Result | Command |
|---|---|---|
| Unit / API / pipeline / security tests on the VM | PASS: 58 passed | `python -m pytest -q tests` |
| Core workflow e2e on the real server (overview → stream → tour → hover pause → Best ring → expand 21→23 → explanations → Confirm + audit → Evidence/System/NNPA → back/forward → no-token view → 390px → restart persistence) | PASS: 15 checks, 0 console errors | `tests/e2e/e2e_real.py` |
| Auth e2e: no / wrong / env-line / refresh / navigation / Forget / Change; 5 reads + 4 writes 401 without token, 200 with | PASS: 8 checks | `tests/e2e/e2e_auth.py` |
| Every control (filters, sorts, speed, flagged-only, Score form valid/invalid, note rules, Fit/Reset/close, tour Back/Skip/Esc, demo mode) | PASS: 15 checks (found and fixed the list race) | `tests/e2e/e2e_controls.py` |
| Judge mode in the browser: banner, no token prompt, stream ≤100/s, Score disabled, Best ring + action, Reset + throttle, rate limit (server-side burst: 130×200, 70×429) | PASS: 6 checks | `tests/e2e/e2e_public.py` |
| Static fallback: MOCKED banner, no live claims, evidence from `eval/`, actions disabled | PASS | `tests/e2e/e2e_static.py` |
| Security with curl: public reads 200, wrong token 401, public `/score` 403, replay 200/s 403, oversized body 413, text/plain 415, foreign CORS preflight refused, NaN 422, CSP / nosniff / no-referrer / DENY headers | PASS | `curl` on the VM |
| Lighthouse accessibility (judge mode) | PASS: 100 on all six pages | `npx lighthouse@12.2.1` |
| Contrast | PASS: 33/33 (text ≥ 4.5, logo ≥ 3) | `scripts/contrast_check.py` |
| README/UI numbers vs `eval/` | PASS | `scripts/readme_results.py --check` |
| Links | PASS: 22 in README, 25 across docs | `scripts/check_links.py --all` |
| Deploy: `demo_start.sh` (token not rotated) + `public_start.sh --app-only`; `/health` 200 on :8000 and :8100 | PASS | VM |
| Listening sockets on the VM | PASS: SSH on 0.0.0.0; app :8000 and judge :8100 on 127.0.0.1 only | `ss -tlnp` |
| External reachability (from the Mac, another network) | PASS: 22 open; 80, 443, 8000, 8100 closed | `nc -z` |
| Token in logs / tree / history | PASS: 0 / 0 / 0 | `grep -cF` (values never printed) |
| Secret scan | PASS for keys, IP and tokens. **Open:** key *filename* 4× in history (commit `1b2bf28`), 0× in the tree | `git log --all -p \| grep` |
| Public HTTPS URL from outside | **BLOCKED**: ports 80/443 rejected by the VM firewall; needs approval | – |
| Reboot autostart | **BLOCKED**: crontab change needs approval (`scripts/autostart.sh`) | – |
| Memory with both instances | 4.0 GiB used, 3.8 GiB available of 7.8 GiB | `free -h` |

## Measured metrics (from `eval/`)

| Metric | Conservative (order-shuffled) | Standard (upper bound) |
|---|---:|---:|
| PR-AUC, MuleTrace C | 0.1369 (95% CI 0.104–0.186) | 0.2188 (0.175–0.264) |
| PR-AUC, transaction-only A | 0.0104 | 0.0094 |
| Recall C at ~1% review | 42.2% | 45.7% |
| Precision C | 4.8% | 5.0% |
| FP per 1,000 payments | 8.31 | 8.57 |
| P@100 | 0.47 | 0.74 |

| Other | Value | Source |
|---|---|---|
| Labelled attempts detected | 23 of 37 (62.2%), median delay 0 min, p90 587 min (standard model) | `eval/detection_delay.json` |
| Latency in-process | p50 1.10 ms, p99 4.06 ms (20,000 payments) | `eval/latency.json` |
| HTTP 50 req/s for 30 s | server p50 1.35 ms, p99 4.35 ms; 1,500 requests, 0 errors | same |
| Egress | 0 non-loopback connections (75 samples, 2,000 payments) | `eval/egress.json` |
| NNPA path (Snap ML on zDNN) | PR-AUC 0.2012 vs C 0.2188; slower than Snap ML on CPU at batch 1/256; proof of NNPA use recorded | `eval/nnpa.json` |

## Public URL status: NOT DEPLOYED (built and tested; awaiting approval)

The VM firewall (`/etc/iptables/rules.v4`, `netfilter-persistent`) accepts only SSH and rejects everything else. Non-root processes cannot bind below port 1024 (`ip_unprivileged_port_start` = 1024). Everything else is ready: the judge-mode instance runs on 127.0.0.1:8100, and Caddy v2.11.7 for s390x is verified with a validated config.

**Open ports now:** 22 (SSH) only.

## Remaining defects and security concerns

- **One shared admin token**; analyst names are self-declared.
- **The key filename in git history** (`1b2bf28`): not a secret; cleaning it needs a history rewrite and a force-push.
- **Judge mode is a public service once exposed.** Rate limits and the demo reset limit abuse, but there is no per-user identity. The admin app stays private.
- **Rate limits are per process and in memory** (they reset on restart). Behind Caddy the client IP comes from `X-Forwarded-For`, trusted only from localhost.
- **Model evidence:** one split and seed; about 5% precision; the standard run partly depends on within-minute file order; tested to 50 payments/s on 3 vCPUs only.
- **The NNPA path** needs `~/zdnn` (user-space library); it isn't installed system-wide.

## MOCKED / SIMULATED / VERIFIED

- **SIMULATED:** HOLD; Confirm / Escalate / Dismiss (audit-logged only); the payment stream (a replay of IBM's synthetic test data).
- **MOCKED:** `?demo=1` and the static GitHub Pages build: a recorded alert sample from the first model, and recorded `eval/` result files. Always bannered "DEMO" / "MOCKED — recorded from the LinuxONE run".
- **VERIFIED on the VM:** everything marked PASS above.
- **UNVERIFIED:** whether the LinuxONE Community Cloud terms allow a public web service; the Hack2Skill rules beyond what you provided.

## Scorecard (same rubric, strict)

| Area | Max | Previous | Now | Evidence |
|---|---:|---:|---:|---|
| Problem fit | 10 | 9 | 9 | detection delay on labelled attempts |
| Originality | 10 | 6 | 6 | unchanged |
| Technical depth | 15 | 12 | 13 | judge mode with roles, rate limits, CSP hashes, reset; static fallback; 5 e2e suites |
| IBM Z relevance | 15 | 11 | 11 | unchanged (measured latency, egress, NNPA path) |
| E2E functionality | 10 | 10 | 10 | 15 + 8 + 15 + 6 browser checks |
| Model evidence | 10 | 8 | 8 | unchanged |
| UX & explainability | 10 | 10 | 10 | list race fixed; Lighthouse 100 in judge mode |
| Security/privacy/oversight | 8 | 7 | 7 | roles, limits, headers, body cap; still a shared token and history filename |
| Reliability/testing/deploy | 7 | 6 | 6 | restart verified; reboot autostart not applied |
| Demo/reproducibility | 5 | 5 | 4 | no public URL yet: judges need the tunnel or a video |
| **Total** | 100 | **84** | **84** | |

## Manual steps left (exact)

1. **Approve the public URL** (three VM changes, see the chat message), then I run `scripts/public_start.sh` and verify from outside. Please also check from a phone on mobile data.
2. **Or enable the static fallback:** GitHub → Adib-07/MULETRACE → Settings → Pages → Build and deployment → Source "Deploy from a branch" → Branch `main`, folder `/ (root)` → Save. The page then appears at `https://<owner>.github.io/MULETRACE/web/` (labelled MOCKED).
3. **Record the demo video** following `docs/DEMO.md` (rotate the token first).
4. **Write the deck and short description** from README TL;DR / Results / IBM LinuxONE.
5. **Submit on Hack2Skill** (team ID, repo link, demo link or video, description, deck) before 18 Oct 2026 22:00 IST.
6. **Decide** on `scripts/autostart.sh --apply` (crontab) and on the git-history rewrite.
