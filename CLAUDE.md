# CLAUDE.md — Dragon Ball Arena engineering guide

Dragon Ball Arena is a browser-based, turn-based 3v3 tactics game whose gameplay structure is inspired by
Naruto-Arena, with an original Dragon Ball identity (we don't copy its visuals or assets). Target: a public
online game, **1v1 PvP only** (no bots), many concurrent matches.

Stack: Python (Flask + Flask-SocketIO + SQLAlchemy; SQLite in dev, Postgres planned), vanilla JS frontend with no
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
  seed_db.py                Manual registry sync (the server already syncs at startup; rarely needed)
  test_game_engine.py       Engine unit + per-character kit tests (no DB)
  test_content.py           Content: real roster loads, schema current, invalid cases, every skill castable
  test_integration_smoke.py Full stack in-process: HTTP + Socket.IO + DB
  test_browser_e2e.py       Playwright: real server + 2 headless browsers play a full match through the UI
  requirements.txt / requirements-dev.txt   runtime / test tools (playwright, coverage, pyflakes)
  photos/characters|skills/ Art (user-supplied; currently JPEG/WEBP named .png)
  game.db                   Local SQLite (gitignored; holds real local accounts)
frontend/  index.html · app.js (single file) · style.css
tools/     measure.py (metrics snapshot) · probe_exploits.py (reproduces known bugs)
docs/      plans, audit, roadmap, step log, measurements/
```

## Commands

From `backend/` unless noted (settings: see `config.py`; the defaults need nothing set):

```
pip install -r requirements-dev.txt && python -m playwright install chromium   # runtime + test tools
python app.py                          # http://localhost:5000 (PORT env to change); 2 windows (1 incognito) to play
python test_game_engine.py             # ~0.4 s (incl. one-time content load)
python test_content.py                 # content validation
DATABASE_URL=sqlite:///<temp>/smoke.db python test_integration_smoke.py   # ALWAYS set a temp DB (default = real game.db)
python test_browser_e2e.py             # ~15 s; own server + temp DB
python content_schema.py               # after changing content_schema.py: regenerate content/*.schema.json
python seed_db.py                      # rarely needed: the server syncs the registry on start
python ../tools/measure.py --save ../docs/measurements/<date>-<step>-before.md   # or from repo root: python tools/measure.py
python ../tools/probe_exploits.py      # CONFIRMED = bug still present; uses a temp DB
```

`measure.py` runs engine, content, smoke and browser suites (`--no-browser` skips the ~15 s browser run),
coverage, pyflakes and asset checks; tools come from `requirements-dev.txt` (Pillow optional, for image checks).
Ad-hoc audit tools (`pip-audit`, `radon`) go in a scratch folder, never into the requirements files.

## Workflow (how every change is made)

1. **One step at a time, user-approved.** Pick the next roadmap task. Say what changes and why; measure before;
   change; measure after; report (files, behavior, numbers, remaining problems, next task). Then **stop and wait**
   for the go-ahead. No unrequested extra changes. Make minor engineering decisions yourself; ask only for game-design
   preferences, architecture-level choices or irreversible actions.
2. **One branch per step:** `feature/stepN-<name>` from the previous step's branch. Commit code + tests + docs +
   that step's `docs/measurements/*` together, push, add a row to `docs/PLAN.md`. The user merges into `dev` in order.
3. **Bugs:** reproduce → add a probe item or failing test → fix → verify → run everything. Ask whether the bug hints
   at a bigger design problem.
4. **Measure honestly:** explain every metric that moved. If something can't be measured, say so. Passing tests
   don't prove a change is good; also check payload, complexity, UX and security.
5. Branches = environments: **`main` = PROD** (release PRs only, never commit directly), **`dev` = DEV/staging**.
6. Don't commit or reseed after every micro-edit (batch rule). Never delete `backend/game.db`.

### Definition of done

Implementation finished · existing behavior intact · regression/new tests added and all green · errors handled ·
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
  Matchmaking state (queue, seat checks, creating matches) is guarded by `MATCHMAKING_LOCK`. Lock order is always
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
- Use `log` (logging), not `print`, in new code.

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
| `update-state` | per-player view (`view_for`) + `turn_seconds_left` (countdown; `null` once the match is over) + `players[r].connected` |
| `message` | game event text (counter fired, game over) |
| `error-msg` | `GameError` text or generic server error |

HTTP: `POST /api/register {username,email,password}`, `POST /api/login`, `POST /api/logout`, `GET /api/me`.

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
- Known engine gaps (audit): ENG-2 mutual KO, ENG-3 dodge per effect, ENG-4 invulnerable targetable, ENG-7 unseeded RNG
  (rules decided, see below).

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
  unused groundwork (don't delete). No migrations yet: adding Flask-Migrate is required before the first schema
  change that must survive (DB-1).

### Frontend
- Today: vanilla JS, one file. **Frontend phase (decided 2026-11-20): React + TypeScript + Vite + React Router**,
  styled with custom CSS + design tokens. Do **not** add Tailwind, shadcn/ui, TanStack Query or Zustand unless a
  concrete need appears. Keep the Socket.IO client. Until then: no framework migration, only fixes.
- Browser tests (`test_browser_e2e.py`) drive the UI like a player: only enabled buttons, real dice selection,
  portrait clicks. Expected console noise is listed and counted in `KNOWN_CONSOLE_NOISE`; anything else fails.
- The client renders state and sends intents; it is never a source of truth for rules. Its affordability math must
  match the server's algorithm (FE-3, still open).
- Every action needs feedback, every error a readable message, every visible button must work.

### Security requirements
- Treat every client input as hostile; validate shape (`require`) and rules (engine) server-side.
- Never send hidden information to the client (`view_for`). Never trust client-sent identity.
- No secrets in code. **All settings come from `config.py`** (`config.load()` at app import): `ENV`
  (development | staging | production), `SECRET_KEY`, `DATABASE_URL`, `PORT`, `TURN_SECONDS`, `RECONNECT_SECONDS`,
  `TURN_TIMER_THREAD`. Don't read `os.environ` anywhere else; add new settings there, validated, with a test in
  `test_config.py`. Staging/production refuse to start without a strong `SECRET_KEY`; development generates a random
  key once into `backend/.dev_secret_key` (git-ignored; delete it to log every local session out).
- Still deploy blockers: CORS + cookie flags (SEC-2), rate limits (SEC-3), session revocation (SEC-4).
- New user-visible text from users (names, chat) requires the DOM-API frontend first (SEC-7).

### Performance requirements
Measure first (`measure.py`, ad-hoc timing). Current: 0.5 ms/turn, 0.23 ms per player view, 8.4 KB per
`update-state`. Payload bytes must not grow without reason; skill icons must be sized for display (AST-1).

### Assets
User supplies all art (don't auto-source anime stills). Portraits → `photos/characters/`, icons → `photos/skills/`.
Planned: real extensions + resize via a tool (AST-1).

### Deployment
Not deployed yet. Follow DEPLOY_PLAN: DEV site from `dev`, PROD from `main`, separate DBs/secrets, Postgres +
migrations, gunicorn + gevent with **one worker** (in-memory games), deploys end live matches until state moves to Redis.

## Important decisions (and why)
- **Server-authoritative engine, per-player views** (Steps 1–9): anti-cheat for online PvP.
- **Python/Flask/Socket.IO stays** (DEPLOY_PLAN §1): turn-based traffic is light; one process scales far.
- **Content architecture (2026-11-20, roadmap 1.13):** version-controlled JSON files (one per character, kit inside,
  Pydantic validation + generated JSON Schema, shared skills referenced) are the single source of truth.
  **Done (Steps 12a + 12b):** gameplay reads the in-memory catalog (never the DB); the `characters` table is an id
  registry for FKs, synced at startup, never deleted from; the lobby gets display fields only.
- **Rules decided (2026-11-20, delegated to Claude):** mutual KO = draw; invulnerable = untargetable except skills
  that explicitly ignore invulnerability; dodge/counter/reflect apply per skill, not per effect.
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
