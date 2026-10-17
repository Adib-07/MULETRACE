# MuleTrace final readiness (final submission pass, 2026-10-18)

Team Quorvex · IBM Z Datathon 2026 · Real-Time AI for Critical Decisions. Fallback tags: `v1-demo`, `v2-submission`, `v2.1-submission`. `v2.2-submission` = before going public; `v2.3-public` = public demo verified, **later switched off**. **Current state: public exposure OFF** (ports 80/443 closed, Caddy and the judge instance stopped).

## Verdict: CONDITIONALLY READY

**Met:**
- Every automated check below passes on the LinuxONE VM and in the browser.
- The public HTTPS judge demo is live and **verified from outside the VM** (valid Let's Encrypt certificate, judge-mode rules, rate limit, closed admin ports, restart recovery).
- The admin app is never exposed.
- Every number traces to `eval/`.

**Missing:**
1. **Phone check** of the public URL on mobile data (I can only test from the Mac's network).
2. **LinuxONE Community Cloud terms:** not read by me; confirm that a public web service is allowed.
3. **Reboot autostart** (crontab, not applied): after a VM reboot the firewall rules persist but the apps do not restart on their own.
4. **Team-only work:** the demo video, deck, short description and Hack2Skill submission (put the public URL in the form).
5. **Decision:** the git-history key-filename cleanup.

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
| External reachability (from the Mac, another network) | PASS: 22, 80, 443 open; 8000, 8100 closed | `nc -z` |
| Token in logs / tree / history | PASS: 0 / 0 / 0 | `grep -cF` (values never printed) |
| Secret scan | PASS for keys, IP and tokens. **Open:** key *filename* 4× in history (commit `1b2bf28`), 0× in the tree | `git log --all -p \| grep` |
| Public HTTPS: certificate (Let's Encrypt, 90 days), HTTP→HTTPS 308, HSTS + CSP + nosniff + no-referrer + DENY, `/health` 200, `/system` public_demo=true | PASS (from the Mac, other network) | `openssl s_client`, `curl` |
| Judge rules over HTTPS: `/alerts` 200, wrong token 401, `/score` 403, replay 200/s 403, body > 16 KB 413; scanner probes `/.env`, `/.git/config`, path traversal 404 | PASS | `curl` |
| Per-IP rate limit through Caddy: 400-request burst → 143×429, client recovers within 12 s | PASS | `xargs -P 40 curl` |
| Judge-mode browser e2e over HTTPS | PASS: 5 checks (rate-limit step skipped, covered by the burst test above) | `e2e_public.py` against the public URL |
| Lighthouse accessibility on the public URL | PASS: 100 (overview, cases, evidence) | `npx lighthouse@12.2.1` |
| Caddy access log: no query strings, tokens, cookies | PASS: fake `?token=` and header values absent (tested; an earlier config logged `?limit=80`: fixed) | `grep` on the VM |
| Restart recovery: kill app + Caddy, `public_start.sh`, URL back to 200, twice, exactly one Caddy | PASS (found and fixed: restarts leaked stale Caddy processes) | VM |
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

## Public URL status: was VERIFIED from outside, now switched OFF at the team's request

**Current open ports: 22 (SSH) only**, checked from the Mac. The firewall rules, Caddy's port permission and the processes are all removed or stopped. To re-enable: open 80/443 again, `setcap` Caddy, run `scripts/public_start.sh`. The verification below describes the state while it was live.

Hostname `<dashed-public-ip>.sslip.io` (kept out of the repo; it is in `~/.muletrace-public.env` on the VM and in the chat). What was changed on the VM, with your approval:
- `setcap cap_net_bind_service=+ep` on `~/bin/caddy` (Caddy stays non-root).
- iptables ACCEPT for TCP 80 and 443 (SSH rule untouched), saved with `netfilter-persistent` (backup of the old rules: `~/rules.v4.before-public`).
- `~/.muletrace-public.env`, then `scripts/public_start.sh` (judge instance on 127.0.0.1:8100 in tmux `pub`, Caddy in tmux `caddy`).

**Open ports now:** 22 (SSH), 80 (redirect + certificate challenge), 443 (HTTPS). **Closed:** 8000 (admin), 8100 (judge instance).

**To undo:** `sudo iptables -D INPUT -p tcp -m conntrack --ctstate NEW --dport 80 -j ACCEPT` (same for 443), `sudo netfilter-persistent save`, `sudo setcap -r ~/bin/caddy`, `pkill -x caddy; tmux kill-session -t pub`.

## Remaining defects and security concerns

- **One shared admin token**; analyst names are self-declared.
- **The key filename in git history** (`1b2bf28`): not a secret; cleaning it needs a history rewrite and a force-push.
- **Judge mode is a public service.** Rate limits, body cap and the demo reset limit abuse, but there is no per-user identity and no DDoS protection beyond per-IP limits; internet scanners already probe it (all 404). One public visitor can reset the demo for everyone (at most every 10 minutes).
- **Public demo state is shared:** all judges see the same queue.
- **The certificate renews automatically** (Caddy); it needs port 80 to stay open.
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
| Demo/reproducibility | 5 | 5 | 5 | public HTTPS demo verified from outside; scripts and docs reproduce it |
| **Total** | 100 | **84** | **85** | |

## Manual steps left (exact)

1. **Phone check:** open the public URL on mobile data; the Overview should load with the "Public demo" banner, and Start live investigation should work.
2. **Confirm the LinuxONE Community Cloud terms allow a public web service** (I could not read them). If they do not, undo with the commands above and use the static fallback.
3. **Decide on reboot autostart:** `bash ~/muletrace/scripts/autostart.sh --apply` (user crontab, no sudo; it now starts the admin app and the public demo).
4. **Optional static page:** GitHub → Settings → Pages → Deploy from a branch → `main` / root → Save (labelled MOCKED).
5. **Record the demo video** following `docs/DEMO.md`; **write the deck and short description** from README TL;DR / Results / IBM LinuxONE.
6. **Submit on Hack2Skill** (team ID, repo link, public URL, video, description, deck) before 18 Oct 2026 22:00 IST.
7. **Decide** on the git-history rewrite for the old key *filename*.
