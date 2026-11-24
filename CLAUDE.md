# CLAUDE.md — Dragon Ball Arena engineering guide

Dragon Ball Arena is a browser-based, turn-based 3v3 tactics game whose gameplay structure is inspired by
Naruto-Arena, with an original Dragon Ball identity (we don't copy its visuals or assets). Target: a public
online game, **1v1 PvP only** (no bots), many concurrent matches.

Stack: Python (Flask + Flask-SocketIO + SQLAlchemy; SQLite in dev, PostgreSQL 16 in production -- verified Step 33), vanilla JS frontend with no
build step.

## Read first

| Doc | Use it for |
|---|---|
| [docs/PROJECT_AUDIT.md](docs/PROJECT_AUDIT.md) | Current findings (IDs like ENG-1, BE-3), architecture map, what not to change |
| [docs/MASTER_ROADMAP.md](docs/MASTER_ROADMAP.md) | Phases, tasks, next task |
| [docs/PLAN.md](docs/PLAN.md) | Step log: what each executed step changed + numbers |
| [docs/UI_PLAN.md](docs/UI_PLAN.md) · [docs/DEPLOY_PLAN.md](docs/DEPLOY_PLAN.md) | UI detail · hosting/environments/deploy stages |
| [README.md](README.md) | Player-facing setup + effect-type reference (partly outdated; roadmap 4.8) |

Update the audit/roadmap/step log when a finding is fixed or a decision is made. Don't create new overlapping docs.

## Folder structure

```
backend/
  app.py                    HTTP auth routes, static serving, Socket.IO handlers, in-memory match state
  game_engine.py            Pure rules engine (no Flask/DB): turns, validation, effects, statuses, per-player views
  content/                  SOURCE OF TRUTH for characters (the user authors these)
    characters/<id>.json      one file per character, kit inside ("$schema" -> VS Code autocomplete)
    shared_abilities.json     skills shared roster-wide (afterimage_technique)
    *.schema.json             GENERATED from content_schema.py -- never edit by hand
  content_schema.py         Pydantic models of the content format (validation only, no game logic)
  content_loader.py         load_catalog() validates + resolves; catalog() = the roster, loaded once per process
  models.py                 SQLAlchemy models
  seed_db.py                Manual migrate + registry sync (the server already does both at startup; rarely needed)
  migrations/               Flask-Migrate/Alembic: env.py, versions/<rev>_*.py (schema history; never edit applied ones)
  test_migrations.py        Fresh/adopted/partial DBs, downgrade/upgrade round trip, models == migrations guard
  test_postgres.py          The same on PostgreSQL (needs TEST_POSTGRES_URL; tests.py provides a Docker container)
  test_game_engine.py       Engine unit + per-character kit tests (no DB)
  test_content.py           Content: real roster loads, schema current, invalid cases, every skill castable
  test_integration_smoke.py Full stack in-process: HTTP + Socket.IO + DB
  test_browser_e2e.py       Playwright: real server + 2 headless browsers play a full match through the UI
  requirements.txt / requirements-dev.txt   runtime / test tools (playwright, coverage, pyflakes)
  requirements-server.txt   production web server (gunicorn + gevent; Docker image only -- gunicorn doesn't run on Windows)
  gunicorn.conf.py          gunicorn settings (gevent, 1 worker, logging) -- top-level names ARE gunicorn settings
  logging_setup.py          one log format (text/json, UTC) for app + gunicorn + libraries; safe_database_url, short
  photos/characters|skills/ Art (user-supplied; currently JPEG/WEBP named .png)
  game.db                   Local SQLite (gitignored; holds real local accounts)
frontend/  index.html · app.js (single file) · style.css · vendor/ (third-party libraries, served by us)
tests.py   ONE command that checks everything + compares with tools/tests_baseline.json (run before/after every change)
Dockerfile · .dockerignore   production image (python:3.12-slim, gunicorn + gevent, 1 worker, non-root, HEALTHCHECK)
.github/workflows/tests.yml  CI: `python tests.py --container` on every push / pull request (Ubuntu, Python 3.12)
tools/     measure.py (detailed metrics snapshot) · probe_exploits.py (reproduces known bugs) ·
           tests_baseline.json (accepted numbers, committed) · test_tests_runner.py (unit tests of tests.py's gates) ·
           check_container.py (builds + proves the production image; `tests.py --container`) ·
           run_loadtest.py + loadtest.py (load test: bots vs the production image, 1 CPU / 1 GB; Docker)
docs/      plans, audit, roadmap, step log, measurements/
```

## Commands

**Before and after every change, from the repo root:**

```
python tests.py --quick                # ~12 s: engine, content, rate limit, smoke (+ runner gates) -- the edit loop
python tests.py                        # ~90 s: ALL suites incl. browser + PostgreSQL, probe, coverage, lint, payload, speed
python tests.py --no-postgres          # same without the PostgreSQL suites (they WARN-skip anyway if Docker is off)
python tests.py --container            # + build and prove the production Docker image (~3 min more): before any
                                       # change to the Dockerfile/requirements/server setup, and before deploys
python tests.py --update-baseline      # only after an INTENDED change (new tests, fixed exploit, accepted payload
                                       # growth): writes tools/tests_baseline.json -- commit it, explain it in the report
```

`tests.py` is green only if every suite passes **and** nothing regressed against the baseline: no suite runs fewer
checks (a test silently lost), no newly SKIPPED test, no new CONFIRMED probe item, no payload growth (fixed sample),
coverage not down by more than 1 point, no new pyflakes issue, and the real `backend/game.db` untouched (size, mtime,
sha256). Engine speed only warns (noisy machine). **PostgreSQL:** whenever Docker is running, a full run also runs
`test_postgres.py` + the whole smoke suite on PostgreSQL 16 in a throwaway container `dba-test-postgres` (port 55432,
user/password `dba`/`dbatest`, started on demand and left running; `docker rm -f dba-test-postgres` removes it), each
suite on a brand-new database. Never point it at a real database. Exit code 1 + a PROBLEM list otherwise. Every step's report
includes its verdict; a step is not done unless the full run is ALL GREEN. **CI** (GitHub Actions) runs
`python tests.py --container` on every push and pull request -- a pushed branch shows green/red in the repo's
Actions tab; the report is on the run's summary page. Anything a suite needs must work on Linux too (no
Windows-only paths; Docker containers reach the host via `host.docker.internal`, mapped with `host-gateway`).

Individual tools, from `backend/` unless noted (settings: see `config.py`; the defaults need nothing set):

```
pip install -r requirements-dev.txt && python -m playwright install chromium   # runtime + test tools
python app.py                          # http://localhost:5000 (PORT env to change); 2 windows (1 incognito) to play
python test_game_engine.py             # ~0.4 s (incl. one-time content load)
python test_content.py                 # content validation
DATABASE_URL=sqlite:///<temp>/smoke.db python test_integration_smoke.py   # ALWAYS set a temp DB (default = real game.db)
python test_browser_e2e.py             # ~15 s; own server + temp DB
python content_schema.py               # after changing content_schema.py: regenerate content/*.schema.json
python seed_db.py                      # rarely needed: the server migrates + syncs the registry on start
python test_migrations.py              # schema history checks (~5 s, separate processes)
DATABASE_URL=sqlite:///<temp>/m.db flask --app app db migrate -m "what changed"   # after changing models.py
DATABASE_URL=sqlite:///<temp>/m.db flask --app app db check                        # models == migrations?
python ../tools/measure.py --save ../docs/measurements/<date>-<step>-before.md   # or from repo root: python tools/measure.py
python ../tools/probe_exploits.py      # CONFIRMED = bug still present; uses a temp DB
```

`measure.py` writes the detailed before/after snapshot saved per step (`docs/measurements/`): suites, coverage per
file, pyflakes, code size, asset weight, content integrity, payload (`--no-browser` skips the browser run); tools come
from `requirements-dev.txt` (Pillow optional, for image checks). `tests.py` is the pass/fail gate; `measure.py` is the
detailed record.
Ad-hoc audit tools (`pip-audit`, `radon`) go in a scratch folder, never into the requirements files.

## Workflow (how every change is made)

1. **One step at a time, user-approved.** Pick the next roadmap task. Say what changes and why; measure before
   (`python tests.py` must be ALL GREEN first + `measure.py --save ...-before.md`); change (`tests.py --quick` while
   editing); measure after (`python tests.py` + `measure.py --save ...-after.md`); report (files, behavior, numbers,
   the tests.py verdict, remaining problems, next task). Then **stop and wait**
   for the go-ahead. No unrequested extra changes. Make minor engineering decisions yourself; ask only for game-design
   preferences, architecture-level choices or irreversible actions.
2. **One branch per step:** `feature/stepN-<name>` from **`dev`** (Steps 1-37 are merged; `dev` and `main` are
   protected by a GitHub ruleset: changes only via a pull request with a green `tests` check -- nobody can push to
   them directly). Commit code + tests + docs + that step's `docs/measurements/*` together, push, add a row to
   `docs/PLAN.md`, open the pull request to `dev`; the user merges it once CI is green.
3. **Bugs:** reproduce → add a probe item or failing test → fix → verify → run everything. Ask whether the bug hints
   at a bigger design problem.
4. **Measure honestly:** explain every metric that moved. If something can't be measured, say so. Passing tests
   don't prove a change is good; also check payload, complexity, UX and security.
5. Branches = environments: **`main` = PROD** (release PRs only, never commit directly), **`dev` = DEV/staging**.
6. Don't commit or reseed after every micro-edit (batch rule). Never delete `backend/game.db`.

### Definition of done

Implementation finished · existing behavior intact · regression/new tests added and **`python tests.py` ALL GREEN**
(baseline updated only for intended changes, and explained) · errors handled ·
security considered · before/after measured and explained · docs updated (audit/roadmap/step log/CLAUDE.md as
relevant) · no new dependencies without reason · no unexplained TODOs · self-reviewed diff · anything not verified
(e.g. not played in a browser) is **stated as unverified**.

## Architecture & conventions

### Backend (`app.py`)
- **Never emit raw game state.** Always `broadcast_state(game)` → per-player `game_engine.view_for`, which strips
  socket/account ids, the opponent's queue, invisible statuses on your own characters, and skill `effects`/`base_*`.
- **Socket handler pattern** (use it for every new event):
  ```python
  @socketio.on('event')
  def handle_event(data):
      try:
          require(data, field=type, ...)                    # shape/type validation -> GameError
          with locked_match() as (room_id, game, role):    # identity from request.sid + the match's lock
              ...engine call...
              broadcast_state(game)                        # or end_game(...) if game['winner']
      except Exception as e:
          report_error(e, 'event')    # GameError -> message; anything else -> logged + generic msg
  ```
- **Concurrency:** the server runs every Socket.IO event in its own thread (`async_handlers`); the in-process test
  client does not, so races never show up in normal tests. Anything that reads or changes a live match must hold its
  lock (`locked_match()` in handlers; `ROOM_LOCKS[room_id]` in background tasks such as the turn timer).
  Matchmaking state (queue, seat checks, creating matches) is guarded by `MATCHMAKING_LOCK`. An event can run after its
  own connection is gone: check `is_connected(sid)` **while holding the lock** before giving a connection a place in
  shared state (Step 38). `start_match` is all-or-nothing. Lock order is always
  `MATCHMAKING_LOCK` -> room lock, never the reverse. Iterate shared dicts over a `list(...)` snapshot. Test races by
  firing events from parallel threads with one step slowed down (see the Step 15 smoke checks).
- **Reconnect (Step 17):** a disconnect mid-match is not a forfeit: the player gets `disconnected_at` (server-only,
  in `PRIVATE_PLAYER_FIELDS`) and an entry in `DISCONNECTED_USERS` (user_id -> room, so lookups never scan all
  matches). The same account connecting again (any tab) is re-attached by `rejoin_match()` in the connect handler
  (new sid, `game-start` + state). `check_disconnect_timers()` (same ticker as the turn timer) forfeits after
  `RECONNECT_SECONDS` (default 30). `end_game` clears the bookkeeping. A still-connected player's second tab never
  takes over the seat. Tests must end matches explicitly -- disconnecting no longer does.
- **Turn timer:** every turn's deadline is `game['turn_deadline']` (server clock, never sent; clients get
  `turn_seconds_left`). Call `start_turn_clock(game)` whenever a new turn starts (match start, commit, timeout). One
  background ticker (`turn_timer_loop`, started with the first match) runs `check_turn_timers()` every second under
  each match's lock; the rules (auto-pass, `TIMEOUTS_TO_FORFEIT`) are in `game_engine.timeout_turn`. Config:
  `TURN_SECONDS` (default 60), `TURN_TIMER_THREAD=0` disables the ticker (the smoke test drives `check_turn_timers()`
  by hand with a shifted `time.time`). The app's clock is `app.now()`.
- Module state (`GAMES`, `MATCHMAKING_QUEUE`, `SID_ROOM_MAP`) is **mutated in place, never rebound**.
- **Every finished match goes through `end_game`**, which pops the room from `GAMES` first (that pop is the
  "ended exactly once" guard), saves the result, sends the final state + message, then closes the Socket.IO room.
  Nothing about a finished match stays in memory; don't keep references to finished games elsewhere.
  A failed save is logged ("Could not save match result: room=... winner=... p1_user=... p2_user=...") and
  rolled back, and never stops the players from seeing the end.
- One account, one seat: `find-match` rejects accounts already queued or in an unfinished match.
- **Logging (Step 35) -- every new feature logs its events.** Never `print`. Set up once at import
  (`logging_setup.configure`; `LOG_LEVEL`, `LOG_FORMAT=text|json`, UTC timestamps); gunicorn and engineio/socketio
  log through the same handler (one format, no duplicate lines). Loggers: `arena.http` (one line per request:
  method, path, status, ms, ip, user -- API at INFO, static + `/healthz` at DEBUG), `arena.auth` (accounts,
  logins, failures, rate limits, logouts, rejected old cookies), `arena.socket` (connects/disconnects; rule
  violations at DEBUG), `arena.match` (searching, match start with teams + `rng_seed`, every committed turn with
  its moves, timeouts, counter-traps, leave/rejoin, `Match ended: ... cause=ko|surrender|timeouts|disconnect`),
  `arena.stats` (every 60 s: live matches, queue, players online), `app` (startup line with `APP_VERSION` = the
  deploy, shutdown, database, **unexpected errors with `who()` context + payload + traceback**). Style: one line,
  `Event: key=value ...`, ids not names where possible, untrusted input through `logging_setup.short()`.
  **Never log** passwords, cookies, `SECRET_KEY`, database passwords (`safe_database_url`), emails, full socket
  ids (first 6 chars only) -- the smoke test captures a whole run and fails on any of them, and its list of
  expected events fails if one stops being logged (add new event kinds there).

### Socket.IO API (client ↔ server contract; document changes here)

| Client → server | Payload | Notes |
|---|---|---|
| `find-match` | `[id, id, id]` | 3 distinct unlocked character ids |
| `queue-skill` | `{charId, skillId, targetPlayerKey, targetIndex}` | `self`/team skills: server picks the target |
| `cancel-skill` | `{charId}` | own move, own turn only |
| `commit-turn` | `{paymentList: [ki, ...]}` | must pay queued costs exactly |
| `surrender` | (none; ignored) | any time during the match; the sender loses (UI asks for confirmation first) |

| Server → client | Payload |
|---|---|
| `character-list` | unlocked characters (on connect) |
| `auth-required` | not logged in |
| `match-status` | text while searching |
| `game-start` | `{roomId, role}` -- also sent on reconnect (a reloaded page lands back in its match) |
| `update-state` | per-player view (`view_for`; `winner`: `p1`/`p2` once over -- never a draw) + `turn_seconds_left` (countdown; `null` once the match is over) + `players[r].connected` |
| `message` | game event text (counter fired, game over) |
| `error-msg` | `GameError` text or generic server error |

HTTP: `POST /api/register {username,email,password}`, `POST /api/login` (both: 429 when rate-limited),
`POST /api/logout` (logs the account out on every device), `GET /api/me` (401 when not logged in),
`GET /healthz` (200 `{"status":"ok"}` / 503 `{"status":"unavailable"}` when the DB doesn't answer; for the host).
Image URLs sent to clients are site-relative (`/photos/...`, `app.PHOTOS_URL`); never build URLs from the request's
Host (`request.host_url`): behind a proxy it's the internal address, and clients control it.

### Game engine (`game_engine.py`)
- **Pure functions over plain dicts.** No Flask/DB imports; that's what makes it fast (~0.5 ms/turn) and testable.
- Rule violations raise `GameError`; game *events* (e.g. a counter-trap firing) are **return values**, not exceptions.
- `resolve_turn` = validate → deep-copy snapshot → `_apply_turn` → restore **in place** on any crash. All per-turn
  mutations belong inside `_apply_turn`.
- Server-side validation is authoritative: `resolve_target`, `can_afford`, `payment_matches_costs`. The client may
  display but never decides damage, Ki, cooldowns, legality or outcomes.
- Turns **alternate**. First turn of the match: 1 Ki die; after that 1 per living character. Moves resolve in queue order.
- **Durations are ticks: 1 turn = 2 ticks**, and every status ticks at the start of *every* turn. Authors write turns;
  the engine multiplies by 2. Exception: `prime_skill` uses `2N + 2` (see the engine comment).
- Cooldown: after use `currentCooldown = cooldown + 1`, decremented at the start of the owner's turn.
- Statuses: `{type, value?, duration, classes?, tag: 'harmful'|'buff', invisible?}`; player-level ones on `player['status']`.
- `start_turn` checks the winner right after ticking statuses; anything that can kill must be followed by `check_winner`.
- **No draws -- resolution order decides (Step 29, user 2026-11-21).** `game['winner']` is `'p1'` or `'p2'`. Every HP
  loss goes through `lose_health()` (stamps `ko_seq` when a character drops to 0); every status goes through
  `add_status()` (stamps `cast_seq`). Moves resolve in queue order, effects in listed order, and `_apply_turn` stops
  the moment `any_team_wiped()` -- nothing after the deciding effect applies. Start-of-turn HP payloads (DoT, HoT,
  delayed detonations) run in `cast_seq` order across both teams and stop once a team is wiped. `check_winner`: if both
  teams are somehow down, the one whose last character fell first loses. Both numbers are stripped in `view_for`.
  **Never set `char['health']` lower directly -- use `lose_health`.**
- **Invulnerable = untargetable (Step 28):** `resolve_target` refuses an enemy that `is_invulnerable` to the skill's
  classes unless `skill_ignores_invulnerability(skill)` (an effect in `IGNORES_INVULNERABILITY`, read from the skill's
  *current* effects -- priming changes them). The client gets `ignores_invulnerable: true` (only when true) from
  `strip_skill_internals` and greys out untargetable portraits; the server stays the authority.
- **Reactive defenses per skill (Step 31):** `react(target, reactions)` uses up the target's first dodge/counter/
  reflect once per skill application; `_apply_turn` passes one `reactions` memo per move into `apply_effect`, which
  hands it to every `apply_damage` / `is_harmful_blocked` call. **New harmful effect types must pass `reactions`
  through**, or they'd react per effect again. Calls outside a skill (counter-trap damage) pass nothing = one-off.
- **Randomness (Step 32):** never call `random` directly in the engine. Every random draw goes through
  `match_rng(game_state)` (dice: `roll_dice(n, game_state)`, `remove_dice(..., game_state)`, random targets), which
  uses the match's `rng_seed` + `rng_draws` (set by `seed_match()` in `app.start_match`, logged there). Same seed +
  same moves = same match. Both fields are in `PRIVATE_GAME_FIELDS` (never sent: the seed predicts every die).
  Hand-built test states without a seed fall back to the global `random`.
- Known engine gaps (audit): ENG-5 reflect semantics (raw, extras not reflected) -- a game-design question.

### Adding an effect type
1. Branch in `apply_effect` (+ `tick_statuses` if timed). (ENG-6: a registry refactor is planned; then add a function.)
2. Add a Pydantic model in `content_schema.py` (fields exactly as the engine reads them; add it to the `Effect`
   union), run `python content_schema.py`, add it to `test_content_smoke`'s known types, and write a focused unit
   test (normal, blocked/invulnerable, edge cases). `test_content.py` fails if models and engine disagree.
3. Visible status → `STATUS_META` in `frontend/app.js`. If the client needs data from it, send a display field, not `effects`.
4. Document in the README effect table.

### Characters & abilities (`backend/content/`)
- Data-driven only: no per-character code paths in the engine. New mechanic = new reusable effect type.
- Ids are **saga-versioned** (`goku_saiyan_saga`); a later version is a new entry.
- Every character's 4th skill is the universal `afterimage_technique` (invulnerable 1 turn, cooldown 4, 1 random);
  name/image may be re-flavored, mechanics/id stay identical.
- **Skill ids are unique only within a kit.** Always address skills by `(charId, skillId)`.
- Flat numbers, no percentage upgrades (design rule). Texts that numbers change must use `new_description`
  (boost/cost changes) or `description_template` with `{value}` (only on `scale_skill_by_stack`).
- **Edit only `backend/content/`.** One file per character (`<id>.json`, file name = id). Shared skills via
  `{"use": "afterimage_technique", "name": ..., "image": ...}` (mechanics can't be overridden). Design notes go in
  `"notes"` (stripped before reaching the engine/players). Never author runtime fields (`currentCooldown`,
  `maxHealth`, `status`).
- Validation = shape (Pydantic: unknown/typo'd fields rejected, ranges) + cross-references (images exist, skill_id /
  effect_index / stack_key / prime marks resolve, locked skills unlockable, universal skill exactly once). All
  problems are reported together; the server refuses to start on invalid content.
- After any content change: `test_content.py` + `test_game_engine.py`, then restart the server. Gameplay reads the
  in-memory `content_loader.catalog()` (never the DB), so there is nothing to reseed.
- `catalog()` is shared and read-only: anything that changes a character (teams, image URLs) must `copy.deepcopy` it
  first (`characters_for_user` does; a smoke check guards it).

### Database
- The `characters` table is an **id registry** (FK target for unlocks/missions), synced at every startup by
  `app.sync_character_registry()`: insert/update, **never delete** (removed characters stay registered and are just
  not offered). Its `skills_json` column is legacy (always `'[]'`), dropped with the first migration.
- Unlocks: `app.unlocked_character_ids()` = every active character (TEMP policy until missions; no DB query).
  `UserCharacter` rows are still written on register for the future mission system.
- SQLAlchemy ORM only, no raw SQL. The registry sync touches only `characters`. Mission tables are intentional,
  unused groundwork (don't delete).
- **Migrations (Step 23):** the schema is owned by `backend/migrations/` (Flask-Migrate/Alembic, `render_as_batch`
  for SQLite). Never `db.create_all()`. The server runs `upgrade_database()` at startup (no-op ~5 ms when current);
  a database made before migrations (tables, no `alembic_version`) is adopted by stamping the baseline
  `def555b6f5cf` when all baseline tables exist, and refused otherwise. **Every model change:** edit `models.py` ->
  `flask --app app db migrate -m "..."` against a temp DB -> read and fix the generated file (Alembic misses renames,
  some type changes, data moves) -> make `downgrade()` correct -> `python test_migrations.py` (its models == migrations
  guard fails if you forget) -> commit model + migration together. Never edit a migration that has been applied
  anywhere; add a new one. `migrations/env.py` only configures logging when nothing else has (CLI) and never
  disables existing loggers.

### Frontend
- Today: vanilla JS, one file. **Frontend phase (decided 2026-11-20): React + TypeScript + Vite + React Router**,
  styled with custom CSS + design tokens. Do **not** add Tailwind, shadcn/ui, TanStack Query or Zustand unless a
  concrete need appears. Keep the Socket.IO client. Until then: no framework migration, only fixes.
- **No third-party requests (Step 21).** Libraries are vendored into `frontend/vendor/` with the version in the file
  name and their license next to them, taken from the official npm tarball and checked against npm's integrity
  hash; the smoke test pins the sha256 and the server/client compatibility (JS client 4.x <-> python-socketio 5.x),
  and the browser tests fail on any request that doesn't go to our own server. To upgrade: same procedure, new
  versioned file, update the pin. `.gitattributes` marks `frontend/vendor/**` as `-text`: without it, Windows
  `core.autocrlf` rewrites line endings on checkout and the file no longer matches its verified build.
- Browser tests (`test_browser_e2e.py`) drive the UI like a player: only enabled buttons, real dice selection,
  portrait clicks. Expected console noise is listed and counted in `KNOWN_CONSOLE_NOISE`; anything else fails.
- The client renders state and sends intents; it is never a source of truth for rules. Its affordability math must
  match the server's algorithm (FE-3, still open).
- Every action needs feedback, every error a readable message, every visible button must work.

### Security requirements
- Treat every client input as hostile; validate shape (`require`) and rules (engine) server-side.
- Never send hidden information to the client (`view_for`). Never trust client-sent identity.
- No secrets in code. **All settings come from `config.py`** (`config.load()` at app import): `ENV`
  (development | staging | production), `SECRET_KEY`, `ALLOWED_ORIGINS`, `DATABASE_URL`, `PORT`, `TURN_SECONDS`,
  `RECONNECT_SECONDS`, `TURN_TIMER_THREAD`, `LOGIN_FAILURE_LIMIT`/`LOGIN_WINDOW_SECONDS`,
  `REGISTER_LIMIT`/`REGISTER_WINDOW_SECONDS`, `TRUSTED_PROXIES`, `SESSION_DAYS`, `LOG_LEVEL`, `LOG_FORMAT`, `APP_VERSION`,
  `SOCKETIO_ASYNC_MODE` (threading | gevent; the image sets gevent). Staging/production also require `DATABASE_URL`.
  A configuration error exits with code 3 (gunicorn then stops instead of restarting the worker forever). Don't read `os.environ` anywhere else; add new settings there, validated, with a test in
  `test_config.py`. Staging/production refuse to start without a strong `SECRET_KEY`; development generates a random
  key once into `backend/.dev_secret_key` (git-ignored; delete it to log every local session out).
- **Origins & cookies (Step 20):** Socket.IO accepts only `ALLOWED_ORIGINS` (development default: same origin;
  staging/production must list https origins; `*` is always refused -- logins are cookie-based). The session cookie is
  `HttpOnly` + `SameSite=Lax`, and `Secure` in staging/production.
- **Rate limits (Step 22):** `rate_limit.SlidingWindowLimiter` (in-memory, thread-safe, bounded) per client IP:
  failed logins (`login_limiter`) and created accounts (`register_limiter`) -> 429 + `Retry-After`. Behind a proxy
  set `TRUSTED_PROXIES` (ProxyFix), or every player shares the proxy's IP. Tests that create many accounts from
  127.0.0.1 raise `REGISTER_LIMIT` for their own process; the smoke test checks the real defaults with swapped-in
  limiters.
- **Sessions (Step 24):** `start_session(user)` (clears the session first, `permanent`, stores `user_id` + `sv` =
  `users.session_version`); `current_user()` returns None when the cookie's `sv` doesn't match the account's (or is
  missing). `/api/logout` logs out **everywhere**: bumps `session_version` (every copy of the cookie dies) and
  disconnects the account's open sockets (`USER_SIDS`). Logins expire after `SESSION_DAYS` (default 30) without a
  visit -- Flask verifies the signed timestamp; each request renews it. Anything that changes credentials later (a
  password change) must bump `session_version` too.
- **Accounts (Step 25):** usernames are unique **case-insensitively** via `users.username_key` (always
  `User.key_for(name)`); look a user up by `username_key`, never by `username` (that's the display spelling). New
  names: `[A-Za-z0-9_-]{3,20}`; emails: lower-cased + a basic shape check (no verification yet). The pre-check gives
  the nice message, but the unique indexes decide: `register` catches `IntegrityError` around the whole write and
  answers 409.
- New user-visible text from users (names, chat) requires the DOM-API frontend first (SEC-7).

### Performance requirements
Measure first (`measure.py`, ad-hoc timing; for engine timing compare old/new interleaved and take the minimum of
several rounds -- single runs on this machine vary by 3x). Current (Step 29): ~0.3 ms per turn incl. 18 ticking
statuses, ~0.29 ms per player view, 8.6 KB per `update-state`. **Capacity (Step 37 load test, 1 CPU):** one
server process is full at ~185-190 turns/s (~5 ms of CPU per turn end to end, PERF-1); p95 < 200 ms holds at 129
turns/s. 4,000 bots at 10-30 s per action (an assumed human pace): 51% CPU, p95 47 ms, p99 775 ms. **Plan ~2,000
concurrent players per server.** RAM ~89 MB + 0.11 MB per connection, flat over 30 minutes. `worker_connections`
(gunicorn, 5000) is a hard cap on connected players (PERF-2). Re-run `python tools/run_loadtest.py` after changes that
touch the per-turn path (payload, broadcasts, logging, the server stack) and compare with
`docs/measurements/2026-11-23-step37-loadtest-*.md`. Check "Connected", "Generator CPU" and the ERROR lines before
trusting a run: a limit in the server's settings or in the bots looks just like a full server.
Payload bytes must not grow without reason; skill icons must be sized for display (AST-1).

### Assets
User supplies all art (don't auto-source anime stills). Portraits → `photos/characters/`, icons → `photos/skills/`.
Planned: real extensions + resize via a tool (AST-1).

### Deployment
Not deployed yet (Stage 2 PostgreSQL: Step 33; Stage 3 production image: Step 34). Follow DEPLOY_PLAN: DEV site from
`dev`, PROD from `main`, separate DBs/secrets, Postgres + migrations, gunicorn + gevent with **one worker** (in-memory
games), deploys end live matches until state moves to Redis. The image: `docker build -t dragon-ball-arena .`; run with
`ENV`, `SECRET_KEY`, `ALLOWED_ORIGINS`, `DATABASE_URL`, `TRUSTED_PROXIES` as environment variables (see the Dockerfile).
Under gevent, background work must use `socketio.sleep` / `socketio.start_background_task` (never `time.sleep` /
raw threads), or it blocks every match. Docker commands from Git Bash need `MSYS_NO_PATHCONV=1` for container paths.

## Important decisions (and why)
- **Server-authoritative engine, per-player views** (Steps 1–9): anti-cheat for online PvP.
- **Python/Flask/Socket.IO stays** (DEPLOY_PLAN §1): turn-based traffic is light; one process scales far.
- **Content architecture (2026-11-20, roadmap 1.13):** version-controlled JSON files (one per character, kit inside,
  Pydantic validation + generated JSON Schema, shared skills referenced) are the single source of truth.
  **Done (Steps 12a + 12b):** gameplay reads the in-memory catalog (never the DB); the `characters` table is an id
  registry for FKs, synced at startup, never deleted from; the lobby gets display fields only.
- **Rules decided (2026-11-20, delegated to Claude):** invulnerable = untargetable except skills that explicitly
  ignore invulnerability (done, Step 28); dodge/counter/reflect apply per skill, not per effect (done, Step 31).
- **No draws (user, 2026-11-21; replaces "mutual KO = draw"):** the team wiped out **first** in resolution order loses
  (moves in queue order, effects in listed order, ticks in cast order) and the match ends at that moment (done, Step 29).
  Players will order their queued skills on a "timeline" in the Ki selector before committing (Phase 6, ENG-9).
- **Tech stack (2026-11-20):** keep Flask + Flask-SocketIO + the Socket.IO protocol (no FastAPI); Pydantic for
  content (later also socket payload) validation; SQLite dev / PostgreSQL prod + Flask-Migrate; live match state
  in memory, the DB only for durable data (accounts, results, history), never written per turn; Playwright
  (Python) browser tests now; React + TS + Vite + React Router in the frontend phase.
- **Single process, in-memory matches for v1**; Redis only when load tests require it.

## Environment notes
**Never `import app` (scripts, `python -c`, REPL) without `DATABASE_URL` pointing at a temp DB**: importing it runs
`ensure_db_ready()`, which writes to the real `backend/game.db` (registry sync). This happened once in Step 15
(characters table only; accounts untouched). All test/tool scripts already set a temp DB.
Windows dev machine, Python 3.14 locally (production: pin 3.12). Use `;` in `PYTHONPATH`. The in-process
Socket.IO test client re-raises handler crashes to the caller, so wrap probe calls in `try/except`.
`python app.py` passes `allow_unsafe_werkzeug=True` so it can start without a terminal (browser tests); it is the
dev runner only. The dev server logs "Invalid frame header" WebSocket errors when a page reloads or logs out
(teardown quirk, never seen during play). Shell heredocs mangle escapes like a backslash-n inside Python strings:
write edit scripts to a file (or use the Edit tool) instead.
