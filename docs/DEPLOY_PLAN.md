# Dragon Ball Arena — Technology & Deployment Plan

Goal: public online game, **1v1 player-vs-player only** (no bots), many matches running at the same time.
Companion to [PLAN.md](PLAN.md) (code fixes) and [UI_PLAN.md](UI_PLAN.md).

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
| `characters.py` as content source | ✔ | **Keep** while you're authoring. | Auto-sync to the DB on every deploy (release step), so there's no manual reseed in prod. |
| Python 3.14 locally | | Very new; some async libs (gevent) can lag behind on wheels. | Pin **Python 3.12** in production (Docker image). Run tests on both. |

**Capacity (honest estimate, to be measured in Stage 5):** one small instance (1–2 vCPU, 1–2 GB) with gevent
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

### Stage 0 — Prerequisites (from PLAN.md) — *must be done before anyone else plays*
1. PLAN Phase 1: server-side cost/target validation, per-player state view. **Without this, players can cheat
   by sending crafted socket messages from the browser console.**
2. PLAN Phase 2: role from `request.sid`, payload validation, turn timer, surrender, reconnect grace window,
   room cleanup, per-room locking, no self-matching.
3. PLAN Phase 3 security items: CORS origins, required `SECRET_KEY`, cookie flags, login rate limit.
- **Check:** `python tools/probe_exploits.py` reports nothing reproduced; all tests green.

### Stage 1 — Production-ready configuration
1. `backend/config.py`: read everything from env: `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_ORIGINS`,
   `ENV=development|production`. In production, refuse to start if `SECRET_KEY` is missing.
2. Cookies in prod: `SESSION_COOKIE_SECURE=True`, `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`.
3. Behind a proxy: wrap the app in `werkzeug.middleware.proxy_fix.ProxyFix` so scheme/IP are correct.
4. **Image URLs → relative** (`/photos/...`) instead of `request.host_url + ...`. Behind HTTPS proxies the
   absolute URL can come out as `http://` and browsers block it (mixed content).
5. `GET /healthz` → `{"ok": true}` plus a cheap DB check (used by the host + uptime monitor).
6. Logging: Python `logging` to stdout (hosts collect stdout); replace `print()`; log tracebacks for non-`GameError`s.
7. Move the `if __name__ == '__main__'` dev runner to dev-only; prod uses gunicorn.
8. `.env.example` documenting every variable (never commit a real `.env`; add it to `.gitignore`).
- **Check:** app starts with `ENV=production` + env vars set, fails clearly without `SECRET_KEY`; tests green.

### Stage 2 — PostgreSQL + migrations
1. Add `psycopg[binary]` and `Flask-Migrate` to `requirements.txt` (pinned).
2. Run Postgres locally (Docker: `docker run -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16`) and point
   `DATABASE_URL` at it.
3. `flask db init` → `flask db migrate -m "initial"` → review the generated migration → `flask db upgrade`.
   From now on **every model change = a migration**; remove `db.create_all()` from app startup.
4. Seeding becomes a **release step**: `flask db upgrade && python seed_db.py` runs on every deploy before the
   new version takes traffic. `characters.py` stays where you author content.
5. Case-insensitive unique usernames (functional index on `lower(username)`).
6. Make the smoke test run against Postgres too (CI does this in Stage 4).
- **Check:** fresh Postgres → upgrade → seed → smoke test passes; re-running seed is a no-op.

### Stage 3 — Production server & container
1. Add `gunicorn` + `gevent` (pinned). Start command:
   `gunicorn -k gevent -w 1 --bind 0.0.0.0:$PORT app:app`
   **Exactly 1 worker**: in-memory games can't be shared between processes. Confirm the exact worker class
   against the Flask-SocketIO deployment docs for the pinned versions, and verify websockets in Stage 5.
2. `Dockerfile` on `python:3.12-slim`: install requirements, copy `backend/` + `frontend/`, non-root user,
   `CMD` = the gunicorn line. `.dockerignore` excludes `game.db`, `__pycache__`, `.git`.
3. Serve the socket.io client JS from our own server (not cdn.socket.io), versioned with the backend.
4. Optimize images (PLAN §5): ~2 MB → ~200 KB, since every player downloads them.
5. Static caching headers for `/photos/*` and JS/CSS (with a version query string on deploy).
- **Check:** `docker build` + `docker run` locally → two browsers play a full match over websockets
  (DevTools → Network → WS shows `101 Switching Protocols`).

### Stage 4 — CI (GitHub Actions)
1. Push the repo to GitHub (private).
2. Workflow on every push/PR: set up Python 3.12, start a Postgres service container, install deps,
   run `test_game_engine.py`, `test_integration_smoke.py` (against that Postgres), `pyflakes`, `probe_exploits.py`.
3. Upload the `tools/measure.py` report as a build artifact, so every PR has before/after numbers.
4. Protect `main`: merge only when CI is green.
- **Check:** a PR with a deliberately broken test is blocked.

### Stage 5 — Load test (measure capacity *before* launch)
1. `tools/loadtest.py`: uses the `python-socketio` client to register N users, pair them into N/2 matches, and
   play random legal turns with think-time delays.
2. Run against the Docker container at 100 → 500 → 1,000 → 2,000 concurrent players.
3. Record per level: CPU %, RAM, p50/p95 time from `commit-turn` to `update-state`, errors, dropped sockets.
   Save to `docs/measurements/<date>-loadtest.md`.
4. Targets: p95 < 200 ms, 0 errors, RAM stable over 30 min (no leak; catches the `GAMES` pruning issue).
- **Check:** we know the max players per instance size → choose the instance size with 2× headroom.

### Stage 6 — Staging deploy
1. Create the host account, a Postgres instance, and a web service from the GitHub repo (Docker).
2. Set env vars: `ENV=production`, `SECRET_KEY` (long random), `DATABASE_URL`, `ALLOWED_ORIGINS`.
3. Release command: `flask db upgrade && python seed_db.py`. Health check path: `/healthz`.
4. Auto-deploy from a `staging` branch.
5. Play full matches from two different networks (Wi-Fi + phone 4G/5G).
- **Check:** match works over the internet; restart the service → app comes back, accounts persist.

### Stage 7 — Domain & HTTPS
1. Buy a domain (pick a name that doesn't use trademarked names, see §6).
2. Point DNS at the host (or through Cloudflare, proxied, with websockets enabled, "Full (strict)" TLS).
3. HTTPS everywhere; redirect http → https; HSTS once stable.
- **Check:** `https://yourdomain` loads, socket connects over `wss://`, cookie shows `Secure`.

### Stage 8 — Monitoring, backups, operations
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
