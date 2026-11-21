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
```

`python app.py` creates the database on first start and registers the
characters from `backend/content/` on every start, so after editing a
character file you just restart the server: there is nothing to reseed.
(`python seed_db.py` does the same registration without starting the server.)
Content is validated when the server starts: invalid files stop it with a
list of every problem, instead of failing mid-match.

For tests and measurements also run:

```
pip install -r requirements-dev.txt
python -m playwright install chromium   # headless browser for test_browser_e2e.py
```

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
Win/loss record and streak show top-right once logged in. There are no draws: everything resolves in
order (skills in the order you queue them, a skill's effects in their listed order, start-of-turn damage
in the order it was cast), and the team wiped out first loses -- the match ends at that moment. E.g. a
skill that kills the last enemy and then hurts its user wins before the recoil ever lands.

## Running the tests

One command runs everything and tells you whether anything got worse:

```
python tests.py --quick    # ~12 s, while editing
python tests.py            # ~70 s, everything (browser, exploit probe, coverage, lint, payload, speed)
```

It exits non-zero and lists each PROBLEM if a test fails, a test silently disappears, a known exploit comes
back, the network payload grows, coverage or lint get worse, or the real `backend/game.db` is touched. The
accepted numbers live in `tools/tests_baseline.json`; after an intended change, `python tests.py
--update-baseline` records the new ones. The individual suites can also be run on their own:

```
cd backend
python test_game_engine.py        # engine unit + per-character kit tests (no DB, no server)
python test_content.py            # content files: validation, broken-content cases, every skill castable
DATABASE_URL=sqlite:///<temp>/smoke.db python test_integration_smoke.py   # full stack in-process
python test_browser_e2e.py        # real browser (Playwright): two players play a full match through the UI
python ../tools/measure.py        # all of the above + coverage, lint, sizes (from repo root: python tools/measure.py)
```

All are plain scripts (no pytest needed) — they print PASS/FAIL per case
and exit non-zero on any failure. **Set `DATABASE_URL` for the smoke test**:
without it, it writes throwaway accounts into the real `backend/game.db`.
`test_browser_e2e.py` starts its own server on a free port with a temporary
database.

## Project layout

```
backend/
  app.py                Flask + Socket.IO server: auth routes, matchmaking, rooms, event handlers
  models.py              SQLAlchemy models: User, UserStats, Character, UserCharacter, Mission, UserMissionProgress, Match
  seed_db.py              Manual character-registry sync (the server already does it on start)
  game_engine.py         Turn/effect resolution engine (damage, status effects, chakra, etc.)
  content/                 THE source of truth for characters: one JSON file per character + shared_abilities.json
  content_schema.py        Pydantic models for content; `python content_schema.py` regenerates the VS Code schema files
  content_loader.py        Loads + validates content/ at startup
  game.db                  SQLite database (gitignored -- created by app.py): accounts, stats, matches, character id registry
  photos/
    characters/               Character portraits (one per roster entry, e.g. Goku_(Saiyan-Saga).png)
    skills/                    Per-skill icons (optional; gracefully absent until added)
  test_game_engine.py       Direct engine unit tests
  test_content.py           Content pipeline tests
  test_integration_smoke.py  End-to-end test: HTTP auth + Socket.IO + DB persistence
  test_browser_e2e.py       Real-browser tests (Playwright)
frontend/
  index.html              Page structure (auth screen, lobby, game board)
  style.css                Styling
  app.js                    Client logic (auth, lobby, board rendering, targeting, payment modal)
  vendor/                   socket.io client 4.5.4 (+ license), served by our own server -- no third-party requests
```

## Accounts & database

- `POST /api/register` `{username, email, password}`, `POST /api/login` `{username, password}`,
  `POST /api/logout`, `GET /api/me` — plain JSON HTTP endpoints, not Socket.IO events.
  A successful register/login sets a Flask session cookie; Socket.IO connections
  read that same cookie to resolve which account owns the connection. Logins expire
  after 30 days without a visit, and logging out signs the account out on every device.
- Usernames are 3-20 letters, digits, `_` or `-`, unique regardless of capitalization
  ("Goku" and "goku" are the same name; you can log in with either).
- Every account currently has **every character in `backend/content/`** (including ones added
  after it registered) -- a temporary rule until mission-based unlocks exist.
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

## Authoring characters and skills

Each character is one file, `backend/content/characters/<character_id>.json`
(the file name must equal the id). Open it in VS Code: the `"$schema"` line
gives autocomplete and red underlines for mistakes while you type. A skill
inside its `"skills"` list looks like:

```json
{
  "id": "unique_skill_id", "name": "Display Name", "description": "shown in the UI",
  "cost": {"energy": 1, "random": 1},
  "target_type": "enemy",
  "classes": ["physical"],
  "image": "skill_file.png",
  "effects": [{"type": "damage", "value": 20}],
  "cooldown": 0,
  "notes": "optional design notes for authors -- never sent to players"
}
```

- `cost` keys: `energy`, `martial`, `spirit`, `rage`, `random` (any type).
- `target_type`: `enemy`, `ally`, `self`, `enemy_team`, `ally_team`.
- `classes` (optional): `physical`, `chakra`, `mental` — interacts with class-scoped invulnerability/silence.
- `image` (optional): file name under `backend/photos/skills/`.
- Don't write `currentCooldown`, `maxHealth` or `status`; the loader adds runtime fields.

The universal 4th skill is defined once in `content/shared_abilities.json`
and referenced, with only the name/icon changeable:
`{"use": "afterimage_technique", "name": "Block", "image": "Piccolo_(Saiyan-Saga)_Block.png"}`.

Then run `python test_content.py` (or just start the server); every problem is
listed with its file and position.

Any effect can add `"target": "self"` to hit the caster instead of the
skill's normal target (e.g. damage an enemy while buffing yourself).

A skill can be born locked with `"locked": true, "locked_reason": "shown in the error/tooltip"`
— `queue_move` rejects it and the frontend greys it out with a 🔒 until
something unlocks it (see the stacking effects below).

**Permanent stacking transformations** (e.g. Kaioken) are a different thing
from a timed status buff — they never expire, and work by directly rewriting
the *caster's other skill dicts* in place, permanently, for the rest of the
match:

| Type | Does |
|---|---|
| `add_stack` | Increments `actor['stacks'][stack_key]` by 1 |
| `self_damage_by_stack` | Self-damage looked up from `schedule` by current stack count (last value repeats past the end of the list) |
| `boost_skill_on_stack` | One-shot: at the exact stack count `at_stack`, permanently adds `bonus` to another skill's `effects[effect_index].value` |
| `unlock_skill_on_stack` | One-shot: at stack count `at_stack`, sets another skill's `locked` to `false` |
| `scale_skill_by_stack` | Every use: sets another skill's `effects[effect_index].value` to `base + increment * (stacks - 1)` |
| `set_skill_cost_on_stack` | One-shot: at stack count `at_stack`, permanently replaces another (or the same) skill's `cost` |

Descriptions are just authored text, not derived from `effects`, so these
effects can update the text when they change the numbers:

- `boost_skill_on_stack`, `set_skill_cost_on_stack`: `"new_description"` (fixed text).
- `scale_skill_by_stack`: `"description_template"` with a `{value}` placeholder, filled with the
  newly computed value every time. `test_content_smoke` rejects `description_template` anywhere else.

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
| Reactive | `dodge`, `counter`, `reflect` (one-shot; one answers a **whole skill** on that target: dodge/counter = the skill misses, reflect = all its damage goes back to the attacker and its stun etc. is blocked; affliction ignores them) |
| Modifiers | `damage_taken_mod`, `damage_dealt_mod`, `heal_received_mod`, `heal_dealt_mod` (all are % duration-based buffs/debuffs) |
| Control | `stun`, `silence` (optionally scoped to `classes`) |
| Cleanse | `cleanse` (`scope`: `"harmful"`, `"buff"`, or a specific status type) |
| Chakra | `remove_chakra`, `steal_chakra`, `chakra_regen`, `chakra_restrict`, `chakra_drain_over_time` |

Invulnerable means **untargetable**: a single-target enemy skill can't pick an invulnerable character (class-scoped: `physical_invulnerable` only stops physical skills), unless the skill contains `affliction_damage`, `damage_ignore_invuln` or `delayed_damage`. Team skills simply skip them, and random hits never pick them.

After adding a skill, run `python test_content.py` and `python test_game_engine.py`.
The content tests reject typo'd fields and effect types, broken references and
missing images, and cast every skill once in a sandbox match.

## Known limitations

Not yet implemented (would need a trigger/event system beyond the current
status-effect model): summons/clones, skill copying, marks/links/redirects,
conditional traps, delayed effects, and true "pick N of M enemies"
multi-target selection (only "one target" or "whole team" exist today).
