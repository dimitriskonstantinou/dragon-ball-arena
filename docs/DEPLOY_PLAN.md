# Dragon Ball Arena — Technology & Deployment Plan

Goal: public online game, **1v1 player-vs-player only** (no bots), many matches running at the same time.
Companion to [MASTER_ROADMAP.md](MASTER_ROADMAP.md) (Phase 8) and [UI_PLAN.md](UI_PLAN.md).

---

## 1. Is the current stack good for this? — Yes, with changes

| Piece | Today | Verdict for online | What changes |
|---|---|---|---|
| Python + Flask | ✔ | **Keep.** A turn-based game sends a few small messages per player per minute. CPU isn't the bottleneck; the number of open connections is, and that's an async-server question, not a language one. | Run it under a production server (Stage 3). |
| Flask-SocketIO / Socket.IO | ✔ | **Keep.** Right tool for this: rooms, auto-reconnect, falls back to HTTP polling when websockets are blocked (some school and work networks). | Single process + gevent; message queue only when scaling out (Stage 10). |
| Vanilla JS frontend | ✔ | **Keep.** No build step, small, fast. | UI_PLAN restructures it into modules. |
| SQLite | ✔ dev | **Not for production.** Most hosts wipe local disk on redeploy, and it's one writer at a time. | Managed **PostgreSQL** (Stage 2). |
| `db.create_all()` | ✔ dev | **Not enough.** It never alters existing tables, so the first schema change after launch breaks prod. | **Flask-Migrate** (Alembic) migrations. |
| `python app.py` dev server | ✔ dev | **Not for production.** | **gunicorn + gevent**, 1 worker. |
| Game state in a Python dict (`GAMES`) | ✔ | **OK for launch**, with two consequences: (1) one server process only; (2) a restart or deploy ends every live match. | Accept for v1 (deploy at quiet hours + warning). Move state to Redis when scaling out (Stage 10). |
| Content files (`backend/content/*.json`) | ✔ | **Keep** as the source of truth (Steps 12a/12b). | Loaded + validated at startup into memory; the DB `characters` table is only an id registry, synced automatically on start. |
| Python 3.14 locally | | Very new; some async libs (gevent) can lag behind on wheels. | Pin **Python 3.12** in production (Docker image). Run tests on both. |

**Capacity (first estimate; measured in Step 37, see Stage 5):** one small instance (1–2 vCPU, 1–2 GB) with gevent
should hold **hundreds to a couple of thousand concurrent players** for a turn-based game. Grow vertically
(bigger box) first, because it's a config change. Horizontal scaling (Stage 10) is real work, so do it only
when the load-test numbers say you need it.

---

## 2. Target architecture (launch)

```
 Players' browsers
      │  HTTPS (pages, /api/*, /photos/*)   +   WSS (Socket.IO)
      ▼
 ┌──────────────────────┐
 │ Cloudflare (optional)│  DNS, TLS, DDoS shield, caches /photos
 └──────────┬───────────┘
            ▼
 ┌──────────────────────────────────────────────┐
 │ Host (Render / Fly.io / VPS) — 1 instance    │
 │  gunicorn -k gevent -w 1                     │
 │   └─ Flask app + Flask-SocketIO              │
 │       ├─ HTTP: auth, static, /healthz        │
 │       ├─ Socket.IO: matchmaking, matches     │
 │       └─ in-memory: GAMES, queue, timers     │
 └──────────┬───────────────────────────────────┘
            ▼
 ┌──────────────────────┐        ┌──────────────────┐
 │ Managed PostgreSQL   │        │ Sentry (errors)  │
 │ users, stats, matches│        │ Uptime monitor   │
 │ characters (synced)  │        └──────────────────┘
 │ daily backups        │
 └──────────────────────┘
```

Later (Stage 10): N instances behind a load balancer with **sticky sessions**, **Redis** as the Socket.IO
message queue + shared game state/matchmaking.

### Connections, explained
- **Browser → server:** one HTTPS origin serves everything (page, API, images, socket). Same-origin keeps
  cookies simple: no CORS, no third-party cookie problems.
- **Auth:** login over HTTPS sets a `Secure; HttpOnly; SameSite=Lax` session cookie. The Socket.IO handshake sends
  the same cookie, and the server maps socket → user. The client never sends its own identity or role.
- **Socket.IO:** tries websocket (WSS) and falls back to long-polling. The proxy must allow websocket upgrades
  and long idle connections (all hosts listed below do).
- **Server → DB:** connection pool via SQLAlchemy, `DATABASE_URL` from env, TLS to the managed DB.
- **In-match traffic:** client sends intents (`queue-skill`, `commit-turn`...); the server validates, resolves,
  and pushes each player their **own view** of the state. The server is the only authority.

---

## 2b. Environments: local → DEV (staging) → PROD

| | **Local** | **DEV / staging** (online test site) | **PROD** (players) |
|---|---|---|---|
| Git branch | any `feature/*` or `dev` | `dev` | `main` |
| Deploys | `python app.py` on your PC | **automatically** on every push to `dev` | **automatically** on every push/merge to `main` |
| URL | `http://localhost:5000` | e.g. `dev.yourdomain` / `dba-dev.onrender.com` | `yourdomain` |
| Database | `backend/game.db` (SQLite) or local Postgres | **its own** Postgres (test accounts, can be wiped) | **its own** Postgres (real accounts, backed up) |
| `ENV` | `development` | `staging` | `production` |
| `SECRET_KEY` | dev default OK | its own random value | its own random value, never reused |
| Who plays | you | you + invited testers | everyone |
| Size | — | smallest paid instance | sized from the Stage 5 load test |

**Rule: DEV and PROD never share a database or a secret key.** A bug on DEV must never be able to touch real accounts.

### Daily flow
```
feature/xyz ──PR──▶ dev ──(auto-deploy)──▶ DEV site: test with 2 browsers / friends
                     │
                     └──PR "Release vX"──▶ main ──(auto-deploy)──▶ PROD
```
1. Start work: `git switch dev && git pull && git switch -c feature/xyz`. Small fixes can go straight to `dev`.
2. Finish: tests + `tools/measure.py` green → merge into `dev` → push → DEV site updates in ~2 min.
3. Test on the DEV site (real internet, real HTTPS/websockets, its own DB).
4. Release: open a PR `dev → main`, CI must be green, merge → PROD updates. Tag it (`git tag v0.1.0`).
5. Hotfix on PROD: branch from `main`, fix, merge to `main`, then merge `main` back into `dev`.

### Setting it up (on the host, e.g. Render)
1. Create **two** Postgres databases: `dba-dev-db`, `dba-prod-db`.
2. Create **two** web services from the same GitHub repo: `dba-dev` (branch `dev`), `dba-prod` (branch `main`).
   Same Dockerfile / start command / release command (`flask db upgrade && python seed_db.py`).
3. Each service gets its own env vars: `ENV`, `SECRET_KEY`, `DATABASE_URL` (its own DB), `ALLOWED_ORIGINS` (its own URL).
4. Turn on auto-deploy for both. PROD can be switched to manual deploy if you want a final "go" button.
5. GitHub → Settings → Branches → protect `main`: require a PR + green CI, no direct pushes.
6. Optional: DEV banner in the UI when `ENV != production` so testers know which site they're on.

### Where we are now (2026-11-02)
- `main` = PROD = **Initial commit only** (correct: nothing released yet).
- `dev` = all current work (Goku, Piccolo, Raditz, Tien, Yamcha + docs/tools). New work branches from `dev`.
- **First release to `main`** = once Stage 0 (anti-cheat) is done and DEV has been played on.
- DEV can go online **before** PROD: once Stages 1–3 exist, the DEV site can run even before all of Stage 0 is
  finished, because only trusted testers use it.

## 3. Hosting recommendation

**Recommended for you: Render** (or Railway, which is similar): deploy from GitHub, Docker or native Python, websockets
supported, managed Postgres in the same dashboard, HTTPS automatic. Least ops work.
Use a **paid always-on instance**: free tiers sleep, and sleeping kills live sockets.

| Option | Pros | Cons |
|---|---|---|
| **Render / Railway** | Easiest, Git push deploys, managed DB, HTTPS | Costs more than a VPS at scale |
| Fly.io | Close-to-players regions, good websockets | More CLI/config knowledge |
| VPS (Hetzner, DigitalOcean) + Docker Compose + Caddy | Cheapest per CPU, full control | You handle OS updates, backups, security |

Database: the host's managed Postgres, or Neon/Supabase. Must have **automatic backups**.
Check current pricing when you sign up; all of these have small paid tiers suitable for launch.

---

## 4. Step-by-step

Each stage ends with a **check**. Measure before/after as usual (`tools/measure.py`), plus the stage-specific numbers.

### Stage 0 — Prerequisites (MASTER_ROADMAP Phases 1–3) — *must be done before anyone else plays*
**✅ Met after Step 32** (only the user's merges into `dev` are pending).
1. ✅ Roadmap Phase 1 (Steps 1–7, 11, 27–29, 31, 32): validation, per-player views, atomic turns, winner rules (no
   draws), untargetable invulnerability, reactive defenses per skill, seeded randomness.
2. ✅ Roadmap Phase 2 (Steps 8–9, 13–18): identity, payload validation, room cleanup, per-room locking, turn timer,
   surrender, reconnect grace window. (2.7 battle events / 2.8 names are UX -- frontend phase.)
3. ✅ Roadmap Phase 3 (Steps 19–26): config + secrets, origins + cookies, self-hosted client, rate limits, migrations,
   revocable sessions, usernames, proxy readiness.
- **Check:** `python tests.py` ALL GREEN; the probe's only confirmed item is the reflect design question (ENG-5).

### Stage 1 — Production-ready configuration
1. ✅ *(Step 19)* `backend/config.py` reads and validates every setting: `ENV` (development|staging|production),
   `SECRET_KEY` (required + strong in staging/production, or the server refuses to start), `DATABASE_URL`, `PORT`,
   `TURN_SECONDS`, `RECONNECT_SECONDS`, `TURN_TIMER_THREAD`, and (Step 20) `ALLOWED_ORIGINS` -- required, https only,
   in staging/production: set it to each site's own URL (e.g. `https://dev.yourdomain`, `https://yourdomain`). Note: the turn-timer ticker is a background thread in the one server process;
   with gevent it becomes a greenlet (`socketio.start_background_task` handles both).
2. ✅ *(Step 20)* Cookies: `HttpOnly` + `SameSite=Lax` always, `Secure` automatically in staging/production.
3. ✅ *(Step 22)* Behind a proxy: set `TRUSTED_PROXIES` (1 behind Render/one load balancer, 2 with Cloudflare in front
   as well) so ProxyFix reads the real client IP/scheme. **Without it the rate limits treat every player as one IP.**
4. ✅ *(Step 26)* **Image URLs → relative** (`/photos/...`) instead of `request.host_url + ...`. Behind HTTPS
   proxies the absolute URL can come out as `http://` and browsers block it (mixed content).
5. ✅ *(Step 26)* `GET /healthz` → 200 `{"status": "ok"}` when the DB answers, 503 `{"status": "unavailable"}` when
   not; `Cache-Control: no-store`; no login, reveals nothing else (used by the host + uptime monitor).
6. ✅ *(Step 26)* Logging: Python `logging` to stderr (hosts collect stdout/stderr) in one format, level from
   `LOG_LEVEL`; tracebacks for non-`GameError`s (Step 14).
7. Move the `if __name__ == '__main__'` dev runner to dev-only; prod uses gunicorn.
8. `.env.example` documenting every variable (never commit a real `.env`; add it to `.gitignore`).
- **Check:** app starts with `ENV=production` + env vars set, fails clearly without `SECRET_KEY`; tests green.

### Stage 2 — PostgreSQL + migrations — ✅ *done in Step 33*
1. ✅ `psycopg[binary]==3.3.9` in `requirements.txt` (pip-audit clean). (Flask-Migrate/Alembic: Step 23.)
2. ✅ Local Postgres: `python tests.py` starts a throwaway `postgres:16` container (`dba-test-postgres`, port 55432)
   whenever Docker is running. To run the game itself on it: `DATABASE_URL=postgresql+psycopg://dba:dbatest@127.0.0.1:55432/dba_test python app.py`.
3. ✅ Migrations exist (Step 23) and are tested on PostgreSQL (`backend/test_postgres.py`): fresh build == models,
   full downgrade/upgrade, existing data through every later migration, refusal rolls back completely, Step 27's
   revision upgrades cleanly, VARCHAR limits enforced.
4. Release step: `flask db upgrade && python seed_db.py` (registers characters before the new version takes
   traffic; the server also syncs on start). Content is authored in `backend/content/`.
5. ✅ *(Step 25)* Case-insensitive unique usernames (`users.username_key`, unique index -- portable, no functional index).
6. ✅ The whole smoke suite runs against Postgres too (`smoke_postgres` in `tests.py`; CI will do the same).
- **Check:** ✅ fresh Postgres → upgrade → seed → smoke test passes; re-running seed is a no-op (all automated).

### Stage 3 — Production server & container — ✅ *items 1–3 done in Step 34*
1. ✅ `backend/requirements-server.txt`: gunicorn 27.0.1 + gevent 26.9.0 + packaging 26.3 (pip-audit clean). Start
   command (in the Dockerfile): `gunicorn --worker-class gevent --workers 1 --bind 0.0.0.0:$PORT app:app`.
   **Exactly 1 worker**: in-memory games can't be shared between processes. Websockets work through
   `simple-websocket` (python-engineio's gevent driver; no gevent-websocket needed) -- verified: the browser's
   transport is `websocket`. `SOCKETIO_ASYNC_MODE=gevent` is set by the image (default `threading` everywhere else).
2. ✅ `Dockerfile` on `python:3.12-slim` (283 MB): dependencies layer first, `backend/` + `frontend/`, non-root user
   `arena`, Docker `HEALTHCHECK` on `/healthz`. `.dockerignore` keeps out `game.db`, `.dev_secret_key`, `.env`, `.git`,
   docs, tools and tests. Settings only via environment variables.
   **Proof (`python tests.py --container` / `tools/check_container.py`, 22 checks):** production settings on
   PostgreSQL (migrations at start, `/healthz`, Secure/HttpOnly/SameSite cookie, foreign origin refused, Docker
   health "healthy"); missing `SECRET_KEY`/`DATABASE_URL` stops the container with a clear error (no restart loop);
   all backend suites pass on the image's Python 3.12; all 39 browser checks play through two containers over real
   websockets, incl. turn timeouts and disconnect forfeits under gevent.
3. ✅ *(Step 21)* The socket.io client is served from our own server (`frontend/vendor/socket.io-4.5.4.min.js`,
   versioned filename, so it can get long cache headers in Stage 3).
4. Optimize images (audit AST-1): ~2 MB → ~200 KB, since every player downloads them.
5. Static caching headers for `/photos/*` and JS/CSS (with a version query string on deploy).
- **Check:** `docker build` + `docker run` locally → two browsers play a full match over websockets
  (DevTools → Network → WS shows `101 Switching Protocols`).

### Stage 4 — CI (GitHub Actions) — ✅ *workflow added in Step 36; branch protection = the user's switch*
1. ✅ The repo is on GitHub.
2. ✅ `.github/workflows/tests.yml`, on every push, pull request and by hand (`workflow_dispatch`): Ubuntu 24.04,
   Python 3.12 (pip cache), `pip install -r backend/requirements-dev.txt`, `python -m playwright install --with-deps
   chromium`, then **`python tests.py --container`** -- every suite incl. PostgreSQL (tests.py starts it in Docker on
   the runner) and the production image check, compared with `tools/tests_baseline.json`; exit 1 = red run.
   Read-only token; a newer push to the same branch cancels the older run. (Once the React frontend exists:
   `npm ci && npm run build` before the browser tests.)
3. ✅ The `tests.py` report is shown on each run's summary page and kept as the `tests-report` artifact.
4. **Protect `main` and `dev`** (GitHub → Settings → Branches → Add rule → "Require status checks to pass before
   merging" → check `tests`; also "Require a pull request before merging" for `main`). Only the repo owner can do it.
- **Check:** a PR with a deliberately broken test is shown red and blocked (after step 4).
- Proven locally before the first cloud run: the same install + `tests.py` in a clean `python:3.12` Linux
  container (all non-Docker suites green, Chromium deps install), and `tests.py --container` on Docker Desktop
  with the Linux host mapping (`--add-host=host.docker.internal:host-gateway`) the runner needs.

### Stage 5 — Load test (measure capacity *before* launch) — ✅ *done in Step 37*
1. ✅ `tools/loadtest.py` (bots: register, connect over a websocket, get matched, play legal turns with exact Ki
   payments, 2-4 s per action, surrender after 8-20 turns and search again) + `tools/run_loadtest.py` (runs the
   production image with production settings on a fresh PostgreSQL, limited to 1 CPU / 1 GB, bots in their own
   container on the same Docker network, samples CPU/RAM every ~2 s, writes the report, removes everything).
2. ✅ Measured on 1 CPU / 1 GB (`docs/measurements/2026-11-23-step37-loadtest-{fast,human-pace,soak}.md`). Latency =
   commit sent -> new state received, p50 / p95 / p99:

   | Bots | Pace | Turns/s | Latency (ms) | CPU avg / max | RAM max |
   |---|---|---|---|---|---|
   | 500 | fast (2-4 s per action) | 65 | 4 / 10 / 33 | 38% / 58% | 147 MB |
   | 1,000 | fast | 129 | 6 / 107 / 266 | 71% / 100% | 217 MB |
   | 1,500 | fast | 184 | 40 / 353 / 499 | 91% / 98% | 262 MB |
   | 2,000 | fast | 189 (full: unlimited would be ~260) | 137 / 705 / 1,023 | 94% / 103% | 332 MB |
   | 2,000 | 10-30 s per action | 48 | 3 / 8 / 82 | 29% / 55% | 315 MB |
   | 4,000 | 10-30 s per action | 96 | 4 / 47 / 775 | 51% / 95% | 530 MB |

   Every bot connected at every level; 0 drops, 0 lost replies, 0 unanswered commits while measuring.
   30-minute soak (500 fast bots, 5,054 matches started): RAM 146-147 MB every minute, no leak; 0 ERROR lines.
   The fast run logged **11 ERROR lines** (while bots left in bulk, so no bot saw them): a real bug, BE-12.
3. **What it means:**
   - **One server process is full at ~185-190 turns/s** (about 5 ms of CPU per turn incl. its queue event). The
     target p95 < 200 ms was met at 129 turns/s and missed at 184.
   - **4,000 players at 10-30 s per action fit on one CPU (51% on average), but p99 is already 775 ms. Planning
     figure: ~2,000 concurrent players per server** (29% CPU, p99 82 ms).
   - Limits of these numbers: the 10-30 s pace is an **assumption** (measure the real one on the DEV site); the CPU
     is a share of the dev machine's, a cloud vCPU may be slower; players arrived over 90 s (everyone reconnecting
     at once after a deploy is not tested); no match ended during the human-pace windows (the fast + soak runs
     cover matches starting and ending).
   - Above 1,000 players `worker_connections` must be raised (PERF-2; now 5,000).
   - RAM: ~89 MB idle + ~0.11 MB per connection -> 2,000 players fit in 512 MB, 4,000 need 1 GB.
   - More CPU cores don't help one server (one gevent process = one core): choose **1 dedicated vCPU / 1 GB**.
     Beyond that: cut the CPU per turn (PERF-1), then Stage 10 (several processes + Redis).
   - Registration: 11.6 accounts/s at full speed (password hashing, deliberately slow).
- **Check:** ✅ we know the players per instance size. Earlier Step 37 runs (2026-11-22) are invalid: they hit
  PERF-2's connection limit and it was misread as CPU saturation.

### Stage 6 — DEV site on Render's free plan (user's choice, 2026-11-24) — *prepared in Step 40, not online yet*
1. ✅ `render.yaml` (Blueprint, valid against Render's published schema): free web service `dragon-ball-arena-dev`
   (Docker, Frankfurt, branch `dev`, deploys only after GitHub's checks pass, health check `/healthz`) + free
   PostgreSQL 16 that accepts no outside connections. `SECRET_KEY` is generated by Render. Migrations run at startup
   (free services have no pre-deploy command). `config.py` accepts what Render provides: `postgresql://` addresses,
   `RENDER_EXTERNAL_URL` as the allowed origin, `RENDER_GIT_COMMIT` as the logged version. `TRUSTED_PROXIES=1`: the
   real client address is the LAST in `X-Forwarded-For` (measured live in the user's Joker project, 2026-11-20).
2. ✅ Simulated in Docker (app 0.1 CPU / 512 MB, PostgreSQL 16 at 0.1 CPU / 256 MB, Render's variables): the code before
   Step 40 never started; now healthy after 20-23 s (49-59 s on 0.05 CPU), 89 MB RAM. 20 bots at 10-30 s per action:
   p99 5 ms; 80 bots: p95 30 ms, p99 95 ms, 0 errors. 0.1 CPU of the dev PC may be faster than Render's.
   Registering: about 1 account/s; 32 at the same instant -> ~10% fail (BE-14).
3. The user: merge, then Render -> New -> Blueprint -> this repository, branch `dev` -> check both say Free -> Apply.
4. Verify from outside: `/healthz`, HTTPS, log line `Server starting: version=<commit> env=staging`, a match from two
   networks, a wrong-password run from two addresses (rate limits count the real one), accounts survive a restart.
- **Free limits:** sleeps after 15 idle minutes (about a minute to wake), may restart any time (ends live matches),
  750 instance hours per month shared with the account's other free apps (**Joker would be suspended too** if they run
  out), one free database, **deleted 30 + 14 days after creation**, no backups. Test accounts are disposable.
- **PROD is never free:** paid always-on service (1 CPU) + paid database with backups, from `main`.
- **Check:** match works over the internet; restart the service → app comes back, accounts persist.

### Stage 7 — Domain & HTTPS
1. Buy a domain (pick a name that doesn't use trademarked names, see §6).
2. Point DNS at the host (or through Cloudflare, proxied, with websockets enabled, "Full (strict)" TLS).
3. HTTPS everywhere; redirect http → https; HSTS once stable.
- **Check:** `https://yourdomain` loads, socket connects over `wss://`, cookie shows `Secure`.

### Stage 8 — Monitoring, backups, operations
*(Logs are ready since Step 35: set `LOG_FORMAT=json` on the host and ship stderr to a log service; useful searches:
`Server starting` = every deploy with its `version`; `ERROR` = bugs with context + traceback; `Login failed` /
`Rate limit hit` = attacks; `Match ended` = results with cause; `arena.stats` = load every 60 s.)*
1. **Sentry** (free tier) for backend exceptions + frontend JS errors.
2. **Uptime monitor** (e.g. UptimeRobot / Better Stack) on `/healthz`, alert to your phone or email.
3. App metrics in logs every minute: connected sockets, active matches, queue length. Optional `/admin/stats`
   behind admin auth.
4. **Backups**: confirm the managed DB's daily backups; do one restore test into a scratch DB.
5. **Deploys end live matches** (in-memory state): add a server broadcast "Server restarting in 2 minutes",
   block new matchmaking during that window, deploy at low-traffic hours.
6. Privacy basics: you store emails + password hashes, so add a short privacy page and an account-deletion path
   (needed for EU players under GDPR).
- **Check:** trigger a test error → it appears in Sentry; stop the service → alert arrives.

### Stage 9 — Launch checklist
- [ ] Stage 0 checks green (no exploits)
- [ ] Load test passed at expected peak × 2
- [ ] Backups verified with a restore
- [ ] Alerts working
- [ ] `SECRET_KEY` set, debug off, CORS locked to the domain
- [ ] Terms/privacy pages up
- [ ] Rollback plan: host's "redeploy previous version" + migrations are backward-compatible
- [ ] Soft launch with friends → fix → public

### Stage 10 — Scaling out (only when Stage 5/8 numbers say so)
In order of effort:
1. **Bigger instance** (vertical). Zero code changes.
2. **Redis** for the Socket.IO message queue (`SocketIO(app, message_queue=REDIS_URL)`) **and** move
   `GAMES`, the matchmaking queue and turn timers into Redis (with a per-room lock), so any instance can serve any room.
   Load balancer with **sticky sessions** (required by Socket.IO polling).
3. Bonus: live matches survive deploys, because state lives in Redis and not in the process.
4. Separate matchmaking into its own small service only if it becomes a hotspot (unlikely for 1v1).

---

## 5. New dependencies (all pinned when added)

| Package | Stage | Why |
|---|---|---|
| `psycopg[binary]` | 2 | Postgres driver |
| `Flask-Migrate` | 2 | Schema migrations |
| `gunicorn`, `gevent` | 3 | Production async server |
| `Flask-Limiter` | 0/1 | Login/register rate limiting |
| `sentry-sdk[flask]` | 8 | Error tracking |
| `redis` | 10 | Message queue + shared state (later) |

---

## 6. Risks to know about

- **Trademark/IP:** "Dragon Ball", the character names and anime stills belong to their rights holders. Fine for a private
  hobby project, but a public site, especially one with ads or payments, can get takedown notices. Plan for it:
  your own art and names, or a non-monetized fan project with a clear disclaimer. This is the biggest non-technical
  risk to going public.
- **Deploys end matches** until Stage 10 (mitigated by the restart warning).
- **Single instance = single point of failure** until Stage 10; the host restarts it automatically on crash.
- **Cheating** is only prevented server-side (Stage 0). Never trust anything the browser sends.
