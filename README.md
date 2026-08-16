# Dragon Ball Arena

A browser-based, turn-based 3v3 tactics game (Naruto-Arena-style) built with
a Python/Flask/Socket.IO backend, SQLite/SQLAlchemy for accounts and stats,
and a vanilla JS frontend. Players register an account, pick a team of 3
characters, then take turns spending dice ("Ki") to queue skills before both
sides' moves resolve simultaneously.

## Requirements

- Python 3.10+

## Setup

```
cd backend
pip install -r requirements.txt
python seed_db.py   # creates backend/game.db and loads the character roster into it
```

`python app.py` also auto-creates and auto-seeds the database on a totally
fresh checkout, so `seed_db.py` is mainly for re-running later after you
edit `characters.py` (it upserts by character id, so it picks up changes).

## Running

```
cd backend
python app.py
```

This serves everything from `http://localhost:5000` — the game page,
character art, API, and Socket.IO connection all come from the same server.
**Load the game at that URL, not via a `file://` path** — accounts are
session-cookie based, and cookies need a real origin to work reliably.

Since a match needs two players, open `http://localhost:5000` in **two**
separate browser windows (or a normal window + a private/incognito one, so
each gets its own login) to play both sides yourself, or share the URL with
someone on your network at `http://<your-LAN-IP>:5000` (printed in the
server's startup log).

Register or log in, then in each window: pick exactly 3 characters, click
**FIND MATCH**. Once both windows have queued, they're paired automatically.
Win/loss record and streak show top-right once logged in.

## Running the tests

```
cd backend
python test_game_engine.py        # effect engine unit tests (no DB, no server)
python test_integration_smoke.py  # full stack: register -> login -> find-match -> queue-skill -> commit-turn -> stats persisted
```

Both are plain scripts (no pytest needed) — they print PASS/FAIL per case
and exit non-zero on any failure. `test_integration_smoke.py` runs against
the real `backend/game.db` and registers two throwaway accounts (unique
per run, via a random suffix) — it doesn't need `python app.py` running
separately, it drives the Flask/Socket.IO app in-process.

## Project layout

```
backend/
  app.py                Flask + Socket.IO server: auth routes, matchmaking, rooms, event handlers
  models.py              SQLAlchemy models: User, UserStats, Character, UserCharacter, Mission, UserMissionProgress, Match
  seed_db.py              Loads/refreshes the characters table from characters.py
  game_engine.py         Turn/effect resolution engine (damage, status effects, chakra, etc.)
  characters.py           Character roster and skill definitions (source of truth for seeding; the DB is what the app actually reads from once seeded)
  game.db                  SQLite database (gitignored -- created by seed_db.py / app.py)
  photos/                   Character portraits
  test_game_engine.py       Direct engine unit tests
  test_integration_smoke.py  End-to-end test: HTTP auth + Socket.IO + DB persistence
frontend/
  index.html              Page structure (auth screen, lobby, game board)
  style.css                Styling
  app.js                    Client logic (auth, lobby, board rendering, targeting, payment modal)
```

## Accounts & database

- `POST /api/register` `{username, email, password}`, `POST /api/login` `{username, password}`,
  `POST /api/logout`, `GET /api/me` — plain JSON HTTP endpoints, not Socket.IO events.
  A successful register/login sets a Flask session cookie; Socket.IO connections
  read that same cookie to resolve which account owns the connection.
- New accounts currently get **every existing character unlocked automatically**.
  The `Mission`/`UserMissionProgress` tables exist for the planned mission-based
  unlock system (like Naruto Arena's), but that's not wired up to gameplay yet —
  see the TODO comment on the unlock loop in `app.py`'s `/api/register` route.
  Two open design questions before building it for real: (1) should mission
  progress auto-track from gameplay events (e.g. "win 5 matches") or be
  manually granted at first, and (2) should skills stay as one JSON blob per
  character (current design) or become fully normalized rows.
- `UserStats` (total matches/wins/losses, current win streak, longest win
  streak, current loss streak) updates automatically at the end of every
  match, including disconnects (counted as a loss for whoever left).
- **Local dev only, do not deploy this way:** the database is a single SQLite
  file (`backend/game.db`). Most free/cheap hosts (Render, Fly.io, Railway)
  wipe local disk on every redeploy, so production needs `DATABASE_URL` set
  to a real hosted Postgres instance — see the deployment discussion for why.
  Everything here goes through SQLAlchemy specifically so that's a connection
  string change, not a rewrite.

## Authoring a new skill

A skill lives on a character in `characters.py` and looks like:

```python
{
    "id": "unique_skill_id", "name": "Display Name", "description": "shown in the UI",
    "cost": {"energy": 1, "random": 1},   # chakra cost; keys: energy/martial/spirit/rage/random
    "target_type": "enemy",                # enemy | ally | self | enemy_team | ally_team
    "classes": ["physical"],               # optional; interacts with class-scoped invuln/silence
    "image": "skill_file.png",             # optional; filename under backend/photos/skills/
    "effects": [
        {"type": "damage", "value": 20}
    ],
    "cooldown": 0, "currentCooldown": 0
}
```

Any effect can add `"target": "self"` to hit the caster instead of the
skill's normal target (e.g. damage an enemy while buffing yourself).

Skill icons are optional — if `"image"` is omitted or the file doesn't exist
yet under `backend/photos/skills/`, the frontend just doesn't render an icon
for that skill (no broken-image placeholder). We deliberately don't
auto-source anime stills for these; drop your own images in that folder
under the filename referenced by each skill.

**Character roster naming convention:** characters are saga-versioned, not
just named after the person — e.g. `goku_saiyan_saga`, not `goku`. A later
version of the same character (e.g. Namek Saga Goku) gets its own separate
id/roster entry rather than replacing this one, so multiple versions can
coexist. **Every character is meant to eventually carry one shared universal
4th skill** — id `afterimage_technique`, `{"type": "invulnerable", "duration": 1}`
— the DBZ equivalent of Naruto Arena's Substitution (blocks all damage/harmful
effects for the opponent's next turn). It's only on `goku_saiyan_saga` so far;
each character picks it up when their kit gets its balance pass.

Supported effect types:

| Category | Types |
|---|---|
| Damage | `damage`, `piercing_damage` (ignores dmg-reduction buffs), `affliction_damage` (ignores reduction, shields, invuln), `self_damage`, `aoe_damage` (legacy: always hits whole enemy team), `dot` |
| Healing | `heal`, `hot`, `team_heal`, `heal_block` |
| Defense | `defense` (shield/destructible defense), `remove_defense`, `invulnerable`, `physical_invulnerable`, `chakra_invulnerable`, `mental_invulnerable` |
| Reactive | `dodge`, `counter`, `reflect` (one-shot, consumed on trigger) |
| Modifiers | `damage_taken_mod`, `damage_dealt_mod`, `heal_received_mod`, `heal_dealt_mod` (all are % duration-based buffs/debuffs) |
| Control | `stun`, `silence` (optionally scoped to `classes`) |
| Cleanse | `cleanse` (`scope`: `"harmful"`, `"buff"`, or a specific status type) |
| Chakra | `remove_chakra`, `steal_chakra`, `chakra_regen`, `chakra_restrict`, `chakra_drain_over_time` |

After adding a skill, run `python test_game_engine.py` — `test_content_smoke`
will catch a typo'd effect type immediately.

## Known limitations

Not yet implemented (would need a trigger/event system beyond the current
status-effect model): summons/clones, skill copying, marks/links/redirects,
conditional traps, delayed effects, and true "pick N of M enemies"
multi-target selection (only "one target" or "whole team" exist today).
