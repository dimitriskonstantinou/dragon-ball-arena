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
  characters.py             Content: CHARACTERS roster (the user authors this)
  models.py                 SQLAlchemy models
  seed_db.py                Sync characters table from characters.py (never touches accounts)
  test_game_engine.py       Engine unit + per-character kit tests (no DB)
  test_integration_smoke.py Full stack in-process: HTTP + Socket.IO + DB
  photos/characters|skills/ Art (user-supplied; currently JPEG/WEBP named .png)
  game.db                   Local SQLite (gitignored; holds real local accounts)
frontend/  index.html · app.js (single file) · style.css
tools/     measure.py (metrics snapshot) · probe_exploits.py (reproduces known bugs)
docs/      plans, audit, roadmap, step log, measurements/
```

## Commands

From `backend/` unless noted:

```
pip install -r requirements.txt
python app.py                          # http://localhost:5000; open 2 windows (1 incognito) to play both sides
python test_game_engine.py             # ~0.1 s
DATABASE_URL=sqlite:///<temp>/smoke.db python test_integration_smoke.py   # ALWAYS set a temp DB (default = real game.db)
python seed_db.py                      # only when the user asks (batch rule)
python ../tools/measure.py --save ../docs/measurements/<date>-<step>-before.md   # or from repo root: python tools/measure.py
python ../tools/probe_exploits.py      # CONFIRMED = bug still present; uses a temp DB
```

`measure.py` uses `coverage`, `pyflakes` and `pillow` if installed (otherwise it skips those sections). In this
environment they live outside the project; put that folder on `PYTHONPATH` (`;` separator on Windows). Ad-hoc
audit tools (`pip-audit`, `radon`) also go in a scratch folder, never into `requirements.txt`.

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
          require(data, field=type, ...)          # shape/type validation -> GameError
          room_id, game, role = current_match()  # identity from request.sid, never from the payload
          ...engine call...
          broadcast_state(game)                  # or end_game(...) if game['winner']
      except Exception as e:
          report_error(e, 'event')               # GameError -> message; anything else -> logged + generic msg
  ```
- Module state (`GAMES`, `MATCHMAKING_QUEUE`, `SID_ROOM_MAP`, `ENDED_ROOMS`) is **mutated in place, never rebound**.
- One account, one seat: `find-match` rejects accounts already queued or in an unfinished match.
- Use `log` (logging), not `print`, in new code.

### Socket.IO API (client ↔ server contract; document changes here)

| Client → server | Payload | Notes |
|---|---|---|
| `find-match` | `[id, id, id]` | 3 distinct unlocked character ids |
| `queue-skill` | `{charId, skillId, targetPlayerKey, targetIndex}` | `self`/team skills: server picks the target |
| `cancel-skill` | `{charId}` | own move, own turn only |
| `commit-turn` | `{paymentList: [ki, ...]}` | must pay queued costs exactly |

| Server → client | Payload |
|---|---|
| `character-list` | unlocked characters (on connect) |
| `auth-required` | not logged in |
| `match-status` | text while searching |
| `game-start` | `{roomId, role}` |
| `update-state` | per-player view (`view_for`) |
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
- Known engine gaps (audit): ENG-1 no winner on turn-start wipe, ENG-2 mutual KO, ENG-3 dodge per effect, ENG-4
  invulnerable targetable, ENG-7 unseeded RNG.

### Adding an effect type
1. Branch in `apply_effect` (+ `tick_statuses` if timed). (ENG-6: a registry refactor is planned; then add a function.)
2. Add to `test_content_smoke`'s known types + a focused unit test (normal, blocked/invulnerable, edge cases).
3. Visible status → `STATUS_META` in `frontend/app.js`. If the client needs data from it, send a display field, not `effects`.
4. Document in the README effect table.

### Characters & abilities (`characters.py`)
- Data-driven only: no per-character code paths in the engine. New mechanic = new reusable effect type.
- Ids are **saga-versioned** (`goku_saiyan_saga`); a later version is a new entry.
- Every character's 4th skill is the universal `afterimage_technique` (invulnerable 1 turn, cooldown 4, 1 random);
  name/image may be re-flavored, mechanics/id stay identical.
- **Skill ids are unique only within a kit.** Always address skills by `(charId, skillId)`.
- Flat numbers, no percentage upgrades (design rule). Texts that numbers change must use `new_description`
  (boost/cost changes) or `description_template` with `{value}` (only on `scale_skill_by_stack`).
- After any content change: `test_game_engine.py` (content smoke + kit tests). The running game reads the **DB**,
  so a reseed is needed to see changes locally (production syncs on deploy).

### Database
- SQLAlchemy ORM only, no raw SQL. `seed_db.py` touches only `characters`. Mission tables are intentional,
  unused groundwork (don't delete). No migrations yet: adding Flask-Migrate is required before the first schema
  change that must survive (DB-1).

### Frontend
- Vanilla JS, no framework, no build step (decision; see UI_PLAN). Planned: ES modules, DOM helpers instead of
  `innerHTML` with data, event delegation, one design system (CSS custom properties).
- The client renders state and sends intents; it is never a source of truth for rules. Its affordability math must
  match the server's algorithm (FE-3, still open).
- Every action needs feedback, every error a readable message, every visible button must work.

### Security requirements
- Treat every client input as hostile; validate shape (`require`) and rules (engine) server-side.
- Never send hidden information to the client (`view_for`). Never trust client-sent identity.
- No secrets in code. `SECRET_KEY`/CORS/cookie flags are **deploy blockers** (SEC-1/SEC-2) until env-driven.
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
- **Content authored in `characters.py`**, synced to the DB (by the user's choice, 2026-11-02).
- **Vanilla JS** (no framework): small app, no build step.
- **Single process, in-memory matches for v1**; Redis only when load tests require it.

## Environment notes
Windows dev machine, Python 3.14 locally (production: pin 3.12). Use `;` in `PYTHONPATH`. The in-process
Socket.IO test client re-raises handler crashes to the caller, so wrap probe calls in `try/except`.
