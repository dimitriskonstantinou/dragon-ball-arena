# Dragon Ball Arena — Master Roadmap

Built from [PROJECT_AUDIT.md](PROJECT_AUDIT.md) (2026-11-20). Finding IDs (ENG-1, BE-3, …) refer to the audit.
Detailed sub-plans: UI → [UI_PLAN.md](UI_PLAN.md), deployment → [DEPLOY_PLAN.md](DEPLOY_PLAN.md).
Executed steps and their numbers: [PLAN.md](PLAN.md) (step log).

**How work flows:** one task = one step = one branch (`feature/stepN-<name>`), measured before/after with
`tools/measure.py` (+ `tools/probe_exploits.py` when relevant), with tests and docs in the same commit, reported, then
the user approves the next step. Priority order: security → data integrity → broken core play → engine correctness
→ architecture → tests → gameplay completeness → integration → UI/UX → performance → polish.

```
P0 Stability ─▶ P1 Engine integrity ─▶ P2 Match lifecycle ─▶ P3 Security & config ─┬─▶ P8 Deployment (DEV, then PROD)
                       │                      │                                    │
                       └──▶ P4 Content system ┴──▶ P5 Frontend foundation ─▶ P6 Battle UX ─▶ P7 Lobby & roster
                                                                                    └─▶ P9 Progression ─▶ P10 Competitive ─▶ P11 Balance & roster growth
```

---

## Phase 0 — Stability & baseline · *mostly done*

**Objective:** a trustworthy baseline and a safe way to change code.
**Current state:** measure + probe tools, audit, CLAUDE.md, 205 checks green. Steps 1–9 are pushed but **not merged into `dev`** and **not yet played in a browser**.

| Task | Why | Done when |
|---|---|---|
| ✅ 0.1 Browser playtest — automated with Playwright in *Step 12a* (`test_browser_e2e.py`) | TST-3 | Done: full matches play to the end in a real browser (3/3 runs); found FE-8/FE-9 |
| 0.2 Merge steps 1–9 (+10 audit) into `dev` in order | `dev` is the integration branch | `dev` = step10 tip, tests green on `dev` |
| 0.3 Reseed local DB | CON-6: Tien/Yamcha missing locally | `characters` table = 5 rows |
| 0.4 Smoke test defaults to a temp DB | TST-1/DB-4: documented command writes to real DB | Running it leaves `game.db` unchanged (checked by mtime) |
| 0.5 Extend `measure.py`: DB size, dependency count, engine timing | Audit metrics currently ad hoc | Metrics appear in every report |
| ✅ 0.6 One test command with regression gates (`tests.py` + baseline) — *Step 30*, asked by the user | Tests only proved "nothing failed", not "nothing got worse" | Done: `python tests.py` (full) / `--quick`; fails on lost tests, new exploits, payload growth, coverage/lint drops, real-DB writes; the gates have their own unit tests; the CI job (Stage 4) will run it |

**Risks:** merging 10 stacked branches; mitigated by merging in order (they're linear).

## Phase 1 — Engine integrity · *✅ complete (Steps 1–7, 11, 27–29, 31, 32)*

**Objective:** the rules are correct, deterministic where intended, and unexploitable.
**Problems:** ENG-1 (no winner on tick wipe), ENG-2 (mutual KO), ENG-3 (dodge per effect), ENG-4 (targeting invulnerable), ENG-7 (unseeded RNG).
**Files:** `game_engine.py`, `app.py` (end game after `start_turn`), `test_game_engine.py`, `test_integration_smoke.py`.

| Task | Needs a user decision? | Done when |
|---|---|---|
| ✅ 1.8 ENG-1: `check_winner` after turn-start ticks — *Step 11* | No | Done: probe #22 fixed; engine + smoke regression tests |
| ✅ 1.9 ENG-2: mutual KO = **draw** (decided) — *Step 27* | Needed a draws column (migration) | Done: draw shown to both, saved with no winner, `total_draws` counted, streaks end; 4 paths tested |
| ✅ 1.9b ENG-2 (**changed 2026-11-21 by the user: no draws**): the team wiped out **first** loses, in resolution order (moves in queue order, effects in listed order, start-of-turn ticks in the order they were cast); the match ends at that moment — *Step 29* | Replaces Step 27's draw (new migration drops its columns) | Done: Tri-Beam kill = Tien's player wins (recoil never lands); reflected first hit = attacker loses; ticks in cast order; no draw anywhere (engine, DB, UI) |
| ✅ 1.10 ENG-4 + CON-2: invulnerable = **untargetable** except skills that ignore invulnerability (decided) — *Step 28* | — | Done: refused at queue time (no Ki/cooldown lost); greyed out in the UI (browser test); text fixed |
| ✅ 1.11 ENG-3: reactive defenses apply **per skill** (decided) — *Step 31* | — | Done: Knee Attack fully dodged by one dodge (real content); 12 tests, 7 of them fail on the old engine |
| ✅ 1.12 ENG-7: per-game seeded RNG stored in state — *Step 32* | No | Done: same seed + same moves → identical match (real 12-turn scenario); seed never sent; rollback keeps the stream in step |
| ✅ **1.13 Content pipeline** (moved up from Phase 4; decided 2026-11-20) | — | **Done in Steps 12a + 12b**; 12c (socket payloads) later |

**1.13 Content pipeline (decided architecture).** One authoritative source: version-controlled JSON files, one per
character with its kit inside, validated by Pydantic models (`content_schema.py`, which also generate the JSON Schema
files for VS Code autocomplete) plus semantic checks (references, images, costs, effect types). Shared skills (`afterimage_technique`)
are defined once and referenced. Loaded once at startup into an in-memory catalog; **gameplay never reads content from
the DB**. The `characters` table becomes an id registry for unlock/match FKs, synced automatically (removed characters
are marked inactive, never deleted). `characters.py` is converted automatically (equality test) and removed.
Content tests: every file loads, every reference/image exists, **every skill can be cast once in a sandbox match**.
Done when: one source of truth, server refuses to start on invalid content with a clear message, no manual reseed,
no DB query for roster data on connect/find-match, all existing checks unchanged.

- **12a ✅ (Step 12a):** content files + Pydantic models + generated schemas + loader with cross-reference checks;
  5 characters converted (exact equality with the old dicts); `characters.py` is a shim over the loader (so the JSON is
  already the only copy); `test_content.py` (53 checks incl. every skill castable); Playwright browser tests.
- **12b ✅ (Step 12b):** gameplay reads `content_loader.catalog()` (in memory) instead of the DB; `characters` table is an
  id registry synced at every startup (never deleted from; legacy `skills_json` emptied); shim and seeding duplication
  removed; lobby list display-only (BE-10, 10,343 → 7,437 B); connect/find-match 3 → 1 SQL statement each, 0 roster reads;
  every account sees every active character (TEMP unlock policy, no query).
- **12c (later, small):** Pydantic models for socket payloads, replacing `require()` with identical messages.

**Measurable:** probe has 0 engine items; engine coverage ≥ 90%.

## Phase 2 — Match lifecycle & server robustness

**Objective:** a match always ends correctly, can't be held hostage, survives a page reload, and never leaks memory.
**Current state:** matches end only by wipe or disconnect; nothing is cleaned up; no timer/surrender/reconnect.
**Files:** `app.py` (likely split into modules here, BE-9), `game_engine.py` (pass turn), frontend (timer display, surrender button), tests.

| Task | Finding | Done when |
|---|---|---|
| ✅ 2.1 Remove finished rooms after the final broadcast; late events answered cleanly — *Step 13* | BE-3 | Done: probe item fixed; 0 rooms left and flat memory over 1,020 real matches |
| ✅ 2.2 End-of-match persistence errors handled + logged — *Step 14* | BE-6 | Done: real failing COMMIT → both players get the end, error logged, nothing half-saved, next match saves |
| ✅ 2.3 Per-room lock around engine calls — *Step 15* | BE-5 | Done: double commit resolves 1 turn (was 2); simultaneous tabs never self-match; 4-player x10 stress clean |
| ✅ 2.4 Surrender — *Step 18* | BE-4 | Done: any turn, behind a confirm dialog; loss/win recorded; both told |
| ✅ 2.5 Turn timer + auto-pass (deadline sent in state) — *Step 16* | BE-1 | Done: 60 s (`TURN_SECONDS`), auto-pass, 3 timeouts in a row forfeit (rules confirmed by the user); countdown in the UI |
| ✅ 2.6 Reconnect grace window (by `user_id`) — *Step 17* | BE-2 | Done: reload mid-match → same match, same role, current state (real browser); 30 s (`RECONNECT_SECONDS`) then forfeit |
| 2.7 Structured battle events from the server (`actor, skill, targets, damage, statuses`) | FE-1 | Each resolved move produces an event in both clients' streams |
| 2.8 Names instead of roles in messages | BE-7 | "Goku_fan wins" |

**Risks:** background timer tasks in tests (use an injectable clock); reconnect touches identity. Do it after 2.1.

## Phase 3 — Security & production configuration

**Objective:** safe to put on the internet. Overlaps DEPLOY_PLAN Stages 0–1.

| Task | Finding | Done when |
|---|---|---|
| ✅ 3.1 `config.py`: env-driven settings; refuse to start without `SECRET_KEY` in prod — *Step 19* | SEC-1 | Done: probe item fixed; a real production start without a key exits with a clear message |
| ✅ 3.2 Allowed origins from env; cookie `SameSite=Lax`, `Secure`, `HttpOnly` — *Step 20* | SEC-2 | Done: probe item fixed; foreign/look-alike origins refused (smoke); production cookie flags verified in a real start |
| ✅ 3.3 Login/register rate limits — *Step 22* | SEC-3 | Done: 6th failed login / 6th account per IP → 429; proxy-aware via `TRUSTED_PROXIES` |
| ✅ 3.4 Session versioning + lifetime — *Step 24* | SEC-4 | Done: a copied cookie dies at logout; open sockets closed; 30-day expiry; first real migration |
| ✅ 3.5 Case-insensitive usernames, email check, IntegrityError handled — *Step 25* | SEC-5 | Done: look-alike names 409, bad emails 400, simultaneous registration 500 → 409; second real migration |
| ✅ 3.6 Relative image URLs, `/healthz`, logging config, self-hosted socket.io (*Step 21*) — *Step 26* | DEPLOY Stage 1, SEC-8, BE-8 | Done: Host header no longer in any URL (smoke + probe); `/healthz` 200/503; one log format + `LOG_LEVEL`. Real proxy not tried yet (DEV site) |

## Phase 4 — Content system & cleanup

**Objective:** adding the 6th to the 50th character is cheap and safe.

| Task | Finding | Done when |
|---|---|---|
| 4.1 Effect registry refactor (behavior-preserving) | ENG-6 | `apply_effect` CC < 10; all checks unchanged |
| 4.2 Strip cost text from descriptions | CON-1 | measure "hardcoded cost text" = 0 |
| 4.3 Class-tagging rule + content-test enforcement | CON-3 | Every skill tagged per rule |
| 4.4 Dead code / duplicates (primed restore, `effect` fallback, `aoe_damage`) | ENG-8 | pyflakes 0; no behavior change |
| ✅ 4.5 Lobby list uses the display-field stripping — *Step 12b* | BE-10 | Done: 7,437 B for 5 chars |
| 4.6 Image normalization + resize tool | AST-1 | Misnamed = 0, assets ≤ 400 KB |
| 4.7 Character metadata (role, bio, saga) | CON-5 | Shown in roster screen (P7) |
| 4.8 README refresh (turn model, effect table, limitations) | docs drift | README matches code |

## Phase 5 — Frontend foundation (UI_PLAN UI-1 + UI-2)

**Objective:** a maintainable frontend before redesigning screens.
**Tech (decided 2026-11-20):** migrate to React + TypeScript + Vite + React Router with custom CSS design tokens
(no Tailwind/shadcn/TanStack Query/Zustand unless a concrete need appears), keeping the Socket.IO protocol; the
Playwright suite is the safety net for the migration.
**Tasks:** auth `<form>`s, correct how-to-play, game-over → back to lobby / play again and **render the final state** (FE-2),
player-facing labels for every status (FE-9), self-target without clicking a covered portrait (FE-10),
toasts instead of log errors / `alert`, ES-module split, DOM helper (no `innerHTML` with data, SEC-7), event delegation,
dead code removed (FE-6), **server-equivalent affordability math** (FE-3).
**Done when:** 0 `innerHTML` with data, 0 inline handlers, game over → lobby without reload, client and server agree on affordability (shared test vectors).

## Phase 6 — Battle experience (UI_PLAN UI-3 + UI-4)

**Depends on:** Phase 2 (events, timer, surrender), Phase 5.
**Tasks:** icon skills + detail panel with inline disabled reasons, valid-target highlighting, auto-target self, auto-pay with
"adjust", **queue-order timeline (ENG-9, decided 2026-11-21 by the user)**: the Ki selector shows the queued skills' icons
in cast order and the player drags them into another order before committing (server: `commit-turn` carries the order,
validated as a permutation of the queue), battle log from server events, floating numbers, turn banner, timer bar, Ki symbols (colorblind).
**Measurable:** clicks per typical turn 11 → ≤ 6; board fits 1366×768; opponent actions 100% visible; keyboard-only turn possible.

## Phase 7 — Lobby, team builder & roster (UI_PLAN UI-5)

Skill preview before picking, team slots, remember last team, cancel search, roster/character details (uses 4.7),
responsive breakpoints, accessibility pass. **Measurable:** Lighthouse accessibility ≥ 90 (baseline to be recorded first).

## Phase 8 — Deployment (DEPLOY_PLAN Stages 1–9)

DEV (staging) online first, PROD after Phases 1–3 are done and DEV has been played on.
Key items: Postgres (DB-2 ✅ ready, Step 33; Flask-Migrate/DB-1 ✅ Step 23), gunicorn + gevent, Docker, CI (TST-2), load test (capacity is currently
unmeasured), domain/HTTPS, Sentry + uptime, backups, restart warnings.
**Measurable:** load test p95 < 200 ms at 2× expected peak; restore test passed; alerts fire.

## Phase 9 — Accounts & progression

Mission-based unlocks (schema exists, unused). **Needs design decisions:** auto-tracked vs manual missions; JSON vs
normalized skills. Also: profile page, match history (needs DB-3 index), privacy page + account deletion (GDPR).

## Phase 10 — Competitive systems

Ranking/ladder (e.g. Elo/Glicko), private matches (invite code), replays (needs ENG-7), seasonal stats.

## Phase 11 — Balance, roster growth & polish

Per-skill usage/win-rate telemetry (CON-4), balance sheet doc, roster expansion (new sagas, new mechanics as needed:
transformations, passives, conditionals, ultimates), visual polish, sound.

---

## Next task

**Going online (user's choice after Step 32): DEPLOY_PLAN Stages 2 → 3 → 4, then the DEV site.**

**Stage 3 / Step 34: production server + container.** `python app.py` is the development server (Werkzeug,
`allow_unsafe_werkzeug`); online it must run under gunicorn with the gevent worker -- **exactly 1 worker**, since
matches live in memory -- in a Docker image (`python:3.12-slim`, the production Python version; non-root user;
`.dockerignore` keeps `game.db`, secrets and `.git` out). Plan: pin gunicorn + gevent (pip-audit), a `wsgi`
entry point, `Dockerfile` + `.dockerignore`, then prove it: build the image, run it against the Postgres container
with production settings, and play a full match through it in the browser test (real websockets, `101 Switching
Protocols`), plus `/healthz` and the turn timer under gevent. Image optimisation (AST-1) and cache headers stay
separate steps. Then Stage 4: GitHub Actions running `python tests.py`.
*(Step 33 done: PostgreSQL verified -- migrations, release step and the whole smoke suite pass on Postgres 16.
Step 32: Phase 1 complete.)*
Remaining Phase 2 items (2.7 battle events, 2.8 names in messages) are UX and fit with the frontend phase.
Small UI fixes found by the browser tests (FE-9 status labels) fit into Phase 5's UI-1.
Phase 0's 0.2 (merge steps into `dev`) remains the user's; 0.1 is automated and 0.3 (reseed) is no longer needed.
