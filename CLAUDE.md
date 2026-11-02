# CLAUDE.md

Dragon Ball Arena: a browser-based, turn-based 3v3 tactics game in the style of Naruto-Arena, with a
Dragon Ball theme. Flask + Flask-SocketIO + SQLAlchemy (SQLite in dev) backend, vanilla JS frontend
with no build step.

Target: public online deployment, 1v1 PvP only (no bots), many concurrent matches.

Plans live in `docs/`: [PLAN.md](docs/PLAN.md) (review + roadmap), [UI_PLAN.md](docs/UI_PLAN.md) and
[DEPLOY_PLAN.md](docs/DEPLOY_PLAN.md) (tech stack, hosting, step-by-step deployment).
Check them before starting work, and tick items off when they're done.

## Commands (run from `backend/` unless noted)

```
pip install -r requirements.txt
python app.py                         # http://localhost:5000 (open 2 windows / 1 incognito to play both sides)
python test_game_engine.py            # engine unit tests, no DB/server, ~0.1s
python test_integration_smoke.py      # full stack in-process; WARNING: uses backend/game.db unless DATABASE_URL is set
python seed_db.py                     # sync characters table from characters.py (only when the user asks)
python tools/measure.py [--save f.md] # from repo root: tests, coverage, lint, sizes, assets, payload
```

Safe way to run the smoke test without touching the real DB:
`DATABASE_URL=sqlite:///<some temp path>/smoke.db python test_integration_smoke.py`

## Workflow rules

- **One step at a time, user-approved.** Work through PLAN.md items in priority order, one fix per step. For each
  step: say what you'll change and why, measure before, change, measure after, report exactly what changed
  (files, behavior, numbers). Then **stop and wait** for the user's go-ahead. Never start the next step, or
  make extra changes nobody asked for, on your own.
- **Measure before and after every change**: `python tools/measure.py --save docs/measurements/<date>-<item>-{before,after}.md`.
  No regressions: FAIL stays 0, PASS/coverage don't drop, pyflakes count doesn't grow.
- Every bug fix gets a regression test in `test_game_engine.py` (engine) or `test_integration_smoke.py` (transport/DB).
- Branches = environments: **`main` = PROD** (only released code, via a `dev → main` PR), **`dev` = DEV/staging**
  (integration branch, auto-deploys to the test site once hosting exists). New work: branch from `dev` (or commit
  straight to `dev` for small things); never commit directly to `main`. Details: DEPLOY_PLAN.md §2b.
- Don't commit or reseed after every small edit: batch changes and commit/reseed when the user says the batch is done.
- Never delete `backend/game.db` to "reset" anything; it holds real accounts. Re-run `seed_db.py` for character changes.

## Architecture

- `backend/game_engine.py`: **pure functions over plain dicts**, no Flask/DB imports. Turn lifecycle
  (`start_turn` → `queue_move`/`cancel_move` → `resolve_turn`) plus `apply_effect`, one big `if/elif` on effect `type`.
  Keep it pure; that's what makes it testable.
- `backend/app.py`: HTTP auth routes (`/api/register|login|logout|me`), static serving, Socket.IO handlers
  (`find-match`, `queue-skill`, `cancel-skill`, `commit-turn`). In-memory state: `GAMES`, `MATCHMAKING_QUEUE`,
  `SID_ROOM_MAP`, `ENDED_ROOMS`. Games are lost on server restart.
- `backend/characters.py`: content (roster + skills). **The running game reads characters from the DB**, which
  `seed_db.py` syncs from this file, so content edits need a reseed to show up in-game. The user authors all
  content here; in production the sync runs automatically as a deploy release step.
- `backend/models.py`: User, UserStats, Character (skills as a JSON blob), UserCharacter (unlocks),
  Mission/UserMissionProgress (schema only, not wired), Match.
- `frontend/app.js`: one file; renders on every `update-state` broadcast. Payment modal handles random costs.

## Game rules worth knowing

- Turns **alternate** (they aren't simultaneous): the active player queues at most one skill per character, then
  `commit-turn` pays and resolves only their moves. First turn of the match gives 1 Ki die; after that 1 per living character.
- Ki types: `energy`, `martial`, `spirit`, `rage`; `random` in a cost means any type.
- **Durations are stored in ticks: 1 turn = 2 ticks.** Every status ticks down at the start of *every* player's turn.
  Effects author `duration` in turns and the engine multiplies by 2. Exception: `prime_skill` uses `2N + 2`
  (see the comment in the engine for why).
- Cooldown: after use, `currentCooldown = cooldown + 1`, decremented at the start of the owner's turn.
- Status dicts: `{type, value?, duration, classes?, tag: 'harmful'|'buff', invisible?}`. Player-level statuses
  (chakra restrict/drain) live on `player['status']`.

## Content conventions

- Character ids are **saga-versioned**: `goku_saiyan_saga`, not `goku`. A later version is a new entry.
- Every character's 4th skill is the universal `afterimage_technique` (`invulnerable`, duration 1, cooldown 4,
  1 random). Name/image can be re-flavored ("Block", "Fake Death"), but the id and mechanics stay identical.
- **Skill ids are unique only within one character's kit** (several share `afterimage_technique`, `kamehameha`).
  Always look skills up by `(charId, skillId)`, never by skill id alone.
- Skill icons go in `backend/photos/skills/`, portraits in `backend/photos/characters/`. Don't auto-source anime
  stills; the user supplies the art. Heads-up: the current files are JPEG/WEBP despite the `.png` names.
- No percentage-based upgrades in kits (design rule); prefer flat numbers.
- After adding or changing a skill, run `test_game_engine.py`: `test_content_smoke` catches unknown effect
  types, and each character has a kit test.

## Adding a new effect type

1. Add an `elif etype == '...'` branch in `apply_effect` (and tick handling in `tick_statuses` if it's a timed status).
2. Add it to the known-types list in `test_content_smoke` and write a focused unit test.
3. If it creates a visible status, add an entry to `STATUS_META` in `frontend/app.js`.
4. Document it in the README effect table.

## Known sharp edges (see PLAN.md §3 for the full list)

- The server does **not** yet validate that payment covers skill costs, or that targets are legal.
- The full game state (including "invisible" statuses and the opponent's queued moves) is broadcast to both players.
- Engine errors are bare `Exception`s used as user messages, and real bugs get shown to players the same way.
- Windows dev machine (Python 3.14): use the `;` separator in `PYTHONPATH`, and avoid Unix-only shell tricks in tooling.
