# Dragon Ball Arena — Project Audit

**Audit date:** 2026-11-20 · **Code audited:** `feature/step10-audit` = `0b0e465` (Steps 1–9 applied, not yet merged into `dev`)
**Baseline:** [measurements/2026-11-20-step10-audit-baseline.md](measurements/2026-11-20-step10-audit-baseline.md) + [probe](measurements/2026-11-20-step10-probe-baseline.txt)
**Roadmap built from this audit:** [MASTER_ROADMAP.md](MASTER_ROADMAP.md)

Every finding below is backed by code that was read or behavior that was run during this audit. Items marked
**(verified)** were reproduced by executing code. **(by reading)** means the conclusion comes from the source
alone. **(unverified)** means a plausible risk that could not be demonstrated.

Severity: **CRITICAL** (exploitable now / data loss) · **HIGH** (breaks core play, or blocks going online) ·
**MEDIUM** (real defect, limited impact) · **LOW** (minor) · **IMPROVEMENT** (not a defect).

---

## 1. What exists today

A working, server-authoritative, turn-based 3v3 PvP prototype:

- Account registration/login (session cookie), per-account win/loss/streak stats, match history rows.
- Lobby: pick 3 different unlocked characters → automatic 1v1 matchmaking.
- Battle: Ki dice (energy/martial/spirit/rage), one queued skill per character per turn, cost/target validation,
  payment modal for "any type" costs, statuses, cooldowns, win/lose, disconnect = forfeit.
- 5 characters (Goku, Piccolo, Raditz, Tien, Yamcha — all Saiyan Saga), 20 skills, all with icons.
- A data-driven effect engine with ~45 effect types (damage variants, heal/HoT/DoT, shields, invulnerability,
  stun/silence, dodge/counter/reflect, chakra manipulation, stacking transformations, skill priming, protect,
  delayed damage, counter-traps).
- 205 automated checks (162 engine + 43 full-stack), 86% backend coverage, a measurement tool and an exploit probe.

## 2. Architecture map

```
Browser (frontend/index.html + app.js + style.css, vanilla JS, socket.io client from CDN)
  │ HTTP  POST /api/register|login|logout, GET /api/me      → session cookie (Flask signed cookie)
  │ HTTP  GET /, /<file>, /photos/<path>                     → static files
  │ WS    socket.io events (same cookie authenticates the socket)
  ▼
backend/app.py  (Flask + Flask-SocketIO, async_mode=threading, single process)
  │ in-memory: GAMES{room→state} (live matches only, since Step 13), MATCHMAKING_QUEUE[], SID_ROOM_MAP{sid→room}
  │ handlers: connect, disconnect, find-match, queue-skill, cancel-skill, commit-turn
  │ → validate payload (require) → identify player (current_match, from request.sid)
  │ → call game_engine → broadcast_state (per-player view_for) / report_error
  ▼
backend/game_engine.py  (pure functions over plain dicts, no Flask/DB)
  start_turn → queue_move / cancel_move → resolve_turn (validate → snapshot → _apply_turn → check_winner)
  apply_effect (one if/elif over ~45 effect types) · tick_statuses · view_for
  ▲
backend/content/*.json ──content_loader (Pydantic)──▶ catalog() in memory ──▶ app/engine (teams)
                                                      └──startup sync──▶ SQLite characters table (id registry only)
(updated 2026-11-20, Steps 12a/12b; this diagram originally showed characters.py → DB skills blob)
backend/models.py  (SQLAlchemy: User, UserStats, Character, UserCharacter, Mission*, UserMissionProgress*, Match)
                    * schema only, unused
```

| # | Question | Answer |
|---|---|---|
| 1 | Frontend ↔ backend | Auth over JSON HTTP; everything in-match over Socket.IO. Client sends **intents** (`queue-skill {charId, skillId, targetPlayerKey, targetIndex}`, `cancel-skill {charId}`, `commit-turn {paymentList}`, `find-match [ids]`); server pushes `update-state` (per-player view), `message`, `error-msg`, `game-start`, `match-status`, `character-list`, `auth-required`. |
| 2 | Request processing | Each socket handler: `require()` validates shape → `current_match()` derives room+role from the connection → engine call → `broadcast_state()`. Errors: `GameError` → message to sender; anything else → logged traceback + generic message (`report_error`). |
| 3 | Game engine | Alternating turns. `start_turn` ticks all statuses (1 turn = 2 ticks), rolls Ki (1 die on the very first turn, then 1 per living character), decrements the active player's cooldowns. `queue_move` validates everything; `resolve_turn` validates payment, snapshots, applies moves in queue order, checks the winner, starts the next turn. |
| 4 | Characters/abilities | *(Since Steps 12a/12b: JSON files in `backend/content/`, validated by Pydantic, served from an in-memory catalog.)* Originally dicts in `characters.py`; a skill = `{id, name, description, cost, target_type, classes?, image, effects[], cooldown, currentCooldown, locked?}`. Effects are typed dicts interpreted by `apply_effect`. Skill ids are unique only within a kit. |
| 5 | Team creation | `find-match`: logged in, not already queued/in a match (per account), exactly 3 distinct ids, all unlocked for the account (every account currently unlocks everything). Teams are deep copies of DB rows. |
| 6 | Combat actions | Queue (validated: turn, actor alive, skill exists/unlocked, not stunned/silenced, off cooldown, legal target, Ki affordable together with the queue, not restricted) → commit (payment must match exactly) → all-or-nothing resolution. |
| 7 | State storage | Live matches: process memory only (lost on restart, never pruned). Accounts/stats/matches/roster: SQLite via SQLAlchemy. |
| 8 | Database use | Read roster on connect/find-match; write user on register; write Match + UserStats on game end. `db.create_all()` at import; no migrations. |
| 9 | Test validation | `test_game_engine.py`: engine unit + per-character kit tests (no DB). `test_integration_smoke.py`: full HTTP + Socket.IO + DB in-process. `tools/probe_exploits.py`: reproduces known bugs. `tools/measure.py`: metrics snapshot. |
| 10 | Status of parts | **Complete:** auth, matchmaking, core combat, validation/anti-cheat, per-player views. **Incomplete:** turn timer, surrender, reconnect, room cleanup, battle log, missions/unlocks, progression. **Fragile:** `apply_effect` size, tick-timing model, frontend (one file, innerHTML). **Disconnected:** Mission tables, `is_starter`, `opponent-left` listener, `onPaymentDieClick`. |

---

## 3. What is already done well — do not change

- **Pure engine.** `game_engine.py` has no Flask/DB imports, so a full turn runs in ~0.5 ms and is testable in isolation. Keep this boundary.
- **Server-authoritative play (Steps 1–9).** Costs, payment, targets, turn order, identity and payload shape are all validated server-side. Each player gets a filtered view (no opponent queue, hidden traps, ids or skill internals).
- **All-or-nothing turns.** `resolve_turn` validates first and rolls back in place on any crash.
- **Clean error contract.** `GameError` for rules vs logged bugs.
- **Data-driven skills.** Most mechanics are reusable effect types; characters need no engine code.
- **Tests with intent.** Every fixed bug has a regression test; the kit tests use real character data; the probe documents what is still exploitable.
- **Safe seeding.** `seed_db.py` never touches accounts/stats/matches.
- **Pinned dependencies, no known vulnerabilities** (pip-audit, 2026-11-20). No raw SQL anywhere (ORM only).
- **Comments that explain *why*** (tick model, prime durations, rollback-in-place).

---

## 4. Findings

Format: **ID — Severity — Title** · *Where* · Problem / Why it matters · **Fix** · Safe now? · Depends on.

### 4.1 Game engine

**ENG-1 — HIGH — No winner when a team dies from a start-of-turn tick (verified) — ✅ FIXED in Step 11**
*Where:* `start_turn` → `tick_statuses` (game_engine.py); `check_winner` only runs inside `_apply_turn` / counter path.
Delayed damage, DoT or Ki drain resolving at turn start can wipe a team, and the game carries on. Reproduced:
Piccolo's Special Beam Cannon detonated on Raditz (30 HP) → Raditz at 0 HP, `winner = None`, game continues.
If the wiped team's owner has the turn, they can simply never commit; with no turn timer the winner can only
leave, and leaving counts as a loss.
**Fix:** call `check_winner` after `tick_statuses` in `start_turn`; app ends the game when `start_turn` produces a winner. Safe now: yes. Depends on: —.

**ENG-2 — MEDIUM — Mutual KO is always awarded to p2 (verified)** — *decided 2026-11-20: draw*
*Where:* `check_winner` checks p1's team first. Tien (10 HP) killing Raditz with Tri-Beam (15 self-damage) → winner `p2`
although p1 acted. Also reachable with Kaioken self-damage and reflect.
**Fix:** needs a rule decision: draw, or "the acting player wins". Then encode it in `check_winner`. Safe now: after the decision.

**ENG-3 — MEDIUM (latent) — Dodge/counter/reflect protect against one *effect*, not one *skill* (verified)** — *decided: per skill*
*Where:* `apply_damage` / `is_harmful_blocked`. Knee Attack (damage + stun) vs Dodge: the damage was dodged, the stun still landed.
No current character grants dodge/counter/reflect, so this is latent until one does.
**Fix:** resolve reactive defenses once per skill application. Safe now: yes, with tests. Depends on: decision on intended semantics (proposed: one dodge = whole skill).

**ENG-4 — MEDIUM — Invulnerable characters can still be targeted (verified)** — *decided: untargetable, except skills that ignore invulnerability*
*Where:* `resolve_target`. The attacker's Ki and cooldown are spent for nothing. Every "Afterimage/Block" text says "Untargetable".
**Fix (decision):** either reject targeting invulnerable enemies (Naruto-Arena-like, needs a UI cue), or change the text to "immune". Recommended: untargetable, except skills that explicitly ignore invulnerability (Spirit Ball, affliction).

**ENG-5 — LOW — Reflect/counter semantics are thin (by reading)**
Reflect returns raw damage ignoring the attacker's invulnerability/defense/modifiers; "counter" only negates (no damage back). Unused by current content. **Fix:** define the rules when the first character uses them.

**ENG-6 — IMPROVEMENT (MEDIUM for scale) — `apply_effect` is one 280-line branch chain (measured)**
Cyclomatic complexity 131 (radon grade F); `game_engine.py` maintainability index 0/100; also `tick_statuses` D(27), `queue_move` D(23).
Every new mechanic grows the chain, and the content test keeps its own hand-copied list of known types.
**Fix:** effect registry (`EFFECTS = {'damage': fn, ...}`), one function per effect, content test uses `EFFECTS.keys()`. Safe: yes, behavior-preserving refactor covered by the existing 162 checks. Do it before the roster grows.

**ENG-7 — LOW — Engine randomness is global and unseeded (by reading)**
`roll_dice`, `remove_dice`, `random_multi_damage` use the module-level `random`. Matches can't be replayed, and random bugs can't be reproduced.
**Fix:** a per-game `random.Random(seed)` with the seed stored in the game state. Prepares replays and anti-cheat audits.

**ENG-8 — LOW — Duplicate code / dead paths (by reading)**
Primed-skill restore is written twice (`unprime_skill` and `tick_statuses`); the legacy single-`effect` fallback and `aoe_damage` are unused by content.

**ENG-9 — LOW — Move order rule is invisible to players (by reading)**
Moves resolve in queue order, and re-queuing a character moves its skill to the end. This is a real tactical rule (e.g. remove defense before piercing) that the UI never shows.

### 4.2 Backend & multiplayer

**BE-1 — HIGH — No turn timer (by reading)** — ✅ FIXED in Step 16 (60 s turns, auto-pass, 3 timeouts in a row = forfeit; verified in a real browser against the real ticker)
A player can stall a match forever; the opponent's only exit is disconnecting, which records *their* loss. Blocks going online.
**Fix:** server-side deadline per turn (background task), auto-pass on expiry, deadline in the state. Depends on: BE-3 (clean end-of-match path).

**BE-2 — HIGH — Refresh or disconnect = instant forfeit, no reconnect (by reading)** — ✅ FIXED in Step 17 (30 s grace window, same account rejoins from any tab; verified with a real page reload in the browser tests)
`handle_disconnect` ends the match immediately. A page reload or a phone switching networks loses the match. Blocks going online.
**Fix:** grace window keyed by `user_id`, re-attach the new socket, re-send state. Depends on: BE-3.

**BE-3 — HIGH — Finished matches are never removed from memory (verified)** — ✅ FIXED in Step 13
`GAMES` and `ENDED_ROOMS` only grow. Measured ~27 KB retained per finished match: about 270 MB/day at 10k matches/day.
*Step 13:* a third copy was found, Socket.IO's room membership (players stayed in every old match room while
connected). Re-measured with 200 real matches through the handlers: ~30 KB/match retained, 220/220 matches kept.
After the fix: 0 rooms left after 1,020 matches; memory growth flat (161 KB fixed cache warm-up, not per match).
**Fix:** remove the room after the final broadcast; handle late events cleanly. Safe now: yes.

**BE-4 — MEDIUM — No surrender (by reading).** Fix: `surrender` event → `end_game`.

**BE-5 — MEDIUM (unverified) — No per-room locking under `async_mode=threading`** — ✅ FIXED in Step 15; **was HIGH (verified exploit)**
Handlers mutate shared dicts. Two near-simultaneous `commit-turn` events could interleave. Not demonstrated.
*Step 15 findings:* the server runs **every** Socket.IO event in its own thread (`async_handlers=True`; the test
client turns that off, which is why no test saw it). Reproduced with parallel threads: (1) a double commit resolved
**two** turns -- the opponent's turn was skipped and the same player moved again; (2) two tabs of one account searching
at the same instant were matched against each other (bypassing Step 9). Also latent: `user_in_active_match` iterated
`GAMES` while other threads changed it (RuntimeError risk); `MATCHMAKING_QUEUE.pop(0)` twice could race.
Fixed with a lock per match (`locked_match()`, re-checks the match after waiting) and a matchmaking lock.
**Fix:** per-room `threading.Lock` around engine calls (cheap insurance), revisit with gevent in deployment.

**BE-6 — MEDIUM — End-of-match persistence errors are unhandled (by reading)** — ✅ FIXED in Step 14 (reproduced first: 0/2 players saw the end; now 2/2, error logged with room/winner/user ids)
`end_game` → `persist_match_result` → `db.session.commit()` with no error handling; on failure the room is already marked ended but stats are lost, and the error escapes the disconnect handler.
**Fix:** wrap and log; keep the game result regardless.

**BE-7 — LOW — Messages use roles, not names (by reading)**
"GAME OVER! P1 WINS!" while players never see which role they are.

**BE-8 — LOW — Logging is only configured under `__main__`; `print()` still used (by reading).**

**BE-9 — IMPROVEMENT — `app.py` mixes auth, static serving, matchmaking and match handlers (414 lines)**
Fine today. Split (`auth.py`, `matchmaking.py`, `match_handlers.py`) when the timer/reconnect work lands.

**BE-10 — LOW — Lobby `character-list` still sends skill `effects` (measured)** — ✅ FIXED in Step 12b (10,343 → 7,437 B)
10,343 B for 5 characters, of which 2,646 B are `effects` the client never reads (Step 7 stripped them only from match updates).
**Fix:** reuse the same display-field stripping for the lobby list.

### 4.3 Security & fair play

**SEC-1 — HIGH (deploy blocker; CRITICAL once online) — Hardcoded fallback `SECRET_KEY` (verified)**
`app.py:23`. If deployed without the env var, anyone knowing the default can sign a session cookie for any `user_id`, which is full account takeover.
**Fix:** refuse to start without `SECRET_KEY` outside development.

**SEC-2 — HIGH (deploy blocker) — Socket.IO accepts any origin with cookie auth (verified)**
`cors_allowed_origins="*"` and no explicit `SameSite`, so a cross-site page can open an authenticated socket in browsers that send the cookie.
**Fix:** allowed origins from env; `SESSION_COOKIE_SAMESITE='Lax'`, `Secure` in production.

**SEC-3 — MEDIUM — No rate limiting on login/register (by reading).** Enables password guessing and account spam. Fix: per-IP limits (Flask-Limiter or a small in-process counter).

**SEC-4 — MEDIUM — Sessions can't be revoked or expire (by reading)**
Signed client-side cookie with only `user_id`; logout just clears that browser. A stolen cookie works forever.
**Fix:** session version/nonce stored per user (bump on logout/password change) + lifetime.

**SEC-5 — MEDIUM — Username/email rules (by reading)**
Usernames are case-sensitive ("Goku" and "goku" can coexist, which allows impersonation); email format isn't checked; a concurrent duplicate register would hit the unique index and return a 500.
**Fix:** case-insensitive uniqueness, simple email check, catch `IntegrityError`.

**SEC-6 — LOW — Account enumeration (by reading).** Register says "username already taken"/"email already registered"; login only hashes when the user exists (timing).

**SEC-7 — LOW (becomes HIGH with user text) — Frontend builds HTML from strings (measured)**
12 `innerHTML` uses, inline `onclick="...'${id}'..."`. Today only authored content flows through it; the first chat, username display or custom name makes it XSS. Fix in the frontend rewrite (DOM APIs / `textContent`).

**SEC-8 — LOW — socket.io client loaded from a third-party CDN without SRI (by reading).** Self-host it.

**Cheating vectors checked and closed (Steps 1–9, probe-verified):** free skills, unaffordable queues,
illegal targets, dead actors, hidden-info leaks (opponent queue, traps, ids, skill internals), spoofed player slot,
malformed payloads, opponent cancelling your move, duplicate-character teams, self-matching.
**Still open:** stalling (BE-1), forced-forfeit by connection drop (BE-2).

### 4.4 Characters & abilities

**CON-1 — MEDIUM — All 20 descriptions hardcode the cost text (measured)**
"… | 1 Eng, 1 Rand" duplicates `cost`, and it already drifted once (Kaioken, fixed in Step 6). The UI draws cost boxes from `cost` anyway.
**Fix:** strip cost suffixes from descriptions.

**CON-2 — MEDIUM — Afterimage/Block text overpromises (by reading)**
"Untargetable/immune to all damage & harmful effects", yet Special Beam Cannon (delayed/affliction) and Spirit Ball (ignores invulnerability) go through it, and it doesn't make anyone untargetable. Tied to ENG-4.

**CON-3 — LOW — Skill `classes` are tagged inconsistently (by reading)**
Knee Attack, Double Sunday and Goku's Kamehameha have no class; Yamcha's Kamehameha is `chakra`; Kaioken Attack and Arm Attack are `physical`. Class-based silence/invulnerability will behave arbitrarily once a character uses them.
**Fix:** a tagging rule (physical/energy/mental/…) applied to every skill and checked by the content test.

**CON-4 — IMPROVEMENT — Balance is unmeasured (by reading; no telemetry)**
Observations to verify by playtesting, not conclusions:
- Tien's Arm Attack: 20 piercing for 1 Ki, no cooldown. That's the best damage per Ki in the roster.
- Goku's post-Kaioken Kamehameha: 45 for 2 Ki, no cooldown.
- Raditz's Knee Attack: 25 damage + stun for 2 Ki.

There's no per-skill usage or win-rate data. **Fix:** log per-match skill usage and outcome, plus a balance sheet doc.

**CON-5 — LOW — No character metadata** (role, short bio, saga label) for a roster/details screen.

**CON-6 — MEDIUM (local only) — Local DB is stale (verified)** — ✅ FIXED in Steps 12a/12b: gameplay no longer reads the DB copy; the registry syncs at startup
`game.db` has 3 characters (Goku, Piccolo, Raditz); `characters.py` has 5. Tien and Yamcha can't be picked locally until `seed_db.py` runs.
Root cause: two sources of truth (file + DB). **Fix:** reseed now; in production the deploy release step syncs automatically (DEPLOY_PLAN).

**Verified OK:** every character has the universal 4th skill with identical mechanics; no missing or unreferenced images; every effect type in content is known to the engine.

### 4.5 Frontend

Full detail in [UI_PLAN.md](UI_PLAN.md). Re-verified on 2026-11-20:

**FE-1 — HIGH (UX) — You can't see what the opponent did.** No battle events from the server; HP just changes.
**FE-2 — MEDIUM — Game over is a dead end and hides the final hit (verified by reading)**
`update-state` returns before redrawing when `game.winner` is set (app.js ~L167), so the board keeps the pre-finish HP. There's also no "back to lobby"; the player must reload.
*Seen in the browser tests (2026-11-20):* after a lethal counter-trap, the loser's board still showed the dead character at 5 HP with an enabled skill button next to "YOU LOSE!".
**FE-3 — MEDIUM — Client affordability math differs from the server's** (`calculateRemainingDice` spends random costs with `pool.shift()`), so a skill can look usable and then be rejected, or the reverse.
**FE-4 — MEDIUM — Not responsive, not accessible (measured):** 0 media queries, 0 ARIA attributes, click-only `div`s, color-only Ki dice (red/green).
**FE-5 — MEDIUM — Manual dice picking for every "any type" cost**, every turn (~11 clicks per typical turn).
**FE-6 — LOW — Dead/incorrect code:**
- `opponent-left` listener (never emitted);
- `onPaymentDieClick` (undefined);
- `animation: pulse` with no `@keyframes`;
- "Earth (P1)/Saiyan (P2)" title;
- "both players' queued moves resolve" (wrong);
- `alert()` for a payment mismatch.
**FE-7 — LOW — One 638-line file, string-built HTML**; see SEC-7.

*Found by the Playwright browser tests (Step 12a, 2026-11-20):*
**FE-8 — MEDIUM — Spirit Ball's icon never loaded (verified, ✅ FIXED in Step 12a).** `primed_image` was sent as a
bare filename (`GET /Yamcha_SpiritBall.png` → 404); `characters_for_user` now converts it like other skill images.
**FE-9 — LOW — Internal status names shown to players (verified):** "? EXPIRING_DEFENSE", "? PRIMED_MARK" (no
`STATUS_META` entries for newer status types).
**FE-10 — LOW — Self-targeting needs a precise click (verified):** your own card is mostly skill buttons and status
badges cover the portrait's top-right, so "click self" only works on part of the portrait (UI_PLAN #8).
**FE-11 — LOW — Normal "logged out" check shows as a browser console error:** `/api/me` answers 401 when logged out.
**DEV-1 — LOW (dev only) — Werkzeug dev server logs "Invalid frame header" WebSocket errors on reload/logout**
(teardown only; never observed during play). Production uses gunicorn + gevent.
**DEV-2 — LOW — First page load waits on cdn.socket.io** (observed in browser tests); supports SEC-8.

### 4.6 Database

**DB-1 — HIGH (deploy blocker) — No migrations** (`db.create_all()` never alters tables). The first schema change after launch breaks production. Fix: Flask-Migrate.
**DB-2 — MEDIUM — SQLite unsuitable for hosted production** (ephemeral disks, single writer). Postgres planned (DEPLOY_PLAN).
**DB-3 — LOW — `matches` has no index on player ids**; needed once match history is shown.
**DB-4 — LOW — Throwaway test accounts in the real `game.db` (verified):** 2 of 4 users are `@test.local` from early smoke runs. Harmless locally; never ship this file.
**Unused schema:** `missions`, `user_mission_progress`, `characters.is_starter`. Intentional groundwork for unlocks; keep until that design is decided.

### 4.7 Testing

**TST-1 — MEDIUM — The documented smoke command writes to the real `game.db`** unless `DATABASE_URL` is set (source of DB-4). Fix: default to a temp DB.
**TST-2 — MEDIUM — No CI.** Tests only run when someone remembers.
**TST-3 — MEDIUM — Frontend has no automated tests, and Steps 3/7/8 (state shape and protocol changes) have not been played in a real browser (unverified).** Checked only by reading `app.js`.
— *✅ Addressed in Step 12a:* `test_browser_e2e.py` (Playwright) plays full matches, sessions and disconnects through the real UI.
**TST-4 — LOW — `seed_db.py` 0% covered**; 2 lint warnings (empty f-strings in the smoke test).
**IMPROVEMENT:** tests are custom scripts. That's fine, but you can't run a single test and there are no fixtures. Making them pytest-compatible is cheap.

### 4.8 Assets

**AST-1 — MEDIUM — All 26 images have the wrong extension (JPEG/WEBP named `.png`); 21 skill icons are >256 px (up to 1919×1079), 1,840 KB, rendered at 32 px (measured).** Each match downloads ~1–1.5 MB of icons. Fix: normalize + resize (≈100–150 KB total).

### 4.9 Deployment

Nothing deployable exists yet, which is expected. Plan: [DEPLOY_PLAN.md](DEPLOY_PLAN.md). Blockers found in code:
SEC-1, SEC-2, DB-1, BE-1, BE-2, BE-3, dev server only, absolute image URLs built from `request.host_url` (mixed
content behind an HTTPS proxy), socket.io from CDN, no health endpoint, no CI, no monitoring.
**Cost:** none incurred yet. **Scalability:** single process by design (in-memory games); measured CPU cost is tiny
(0.5 ms/turn, 0.23 ms per player view), so one instance should go far. Real capacity is unmeasured until the load test (DEPLOY_PLAN Stage 5).

---

## 5. Measurements (baseline for this audit)

| Metric | Value | Source |
|---|---|---|
| Engine tests | 42 functions / 162 checks, 0 fail, 0.08 s | measure.py |
| Smoke test | 43 checks, 0 fail, 1.75 s | measure.py |
| Coverage | 86% (app 81%, engine 90%, models 100%, seed_db 0%) | coverage |
| Lint | 2 pyflakes warnings | pyflakes |
| Complexity | `apply_effect` CC 131 (F); 8 more functions ≥ C; engine MI 0 | radon (scratch install) |
| Dependency vulnerabilities | 0 known (6 pinned packages) | pip-audit (scratch install) |
| Code | 4,195 lines (backend 2,966 incl. tests, frontend 887) | measure.py |
| Frontend first load | 37.5 KB (+ socket.io CDN) | measure.py |
| Assets | 26 files, 2,037 KB; 26 misnamed; 21 oversized (1,840 KB) | measure.py |
| Payload per player (`update-state`) | 8,416 B | measure.py |
| Lobby `character-list` | 10,343 B (2,646 B unused effects) | ad-hoc script |
| Engine speed | 0.48 ms per queue×2+resolve turn; 0.23 ms per `view_for` | ad-hoc timing |
| Memory retained per finished match | ~27 KB (never freed) | tracemalloc |
| Local DB | 69,632 B; 4 users (2 test), 2 matches, 3/5 characters | read-only sqlite |
| Probe | 4 confirmed (secret key, CORS, room pruning, reflect design) | probe_exploits.py |

**Not measured (no tooling or no data yet):** real browser load/render times, Lighthouse accessibility,
concurrent-player capacity, memory under real load, DB queries per request, skill usage/win rates.

---

## 6. Multiplayer: now vs. preparation vs. later

| Now (before anyone else plays) | Prepare now (cheap, avoids rewrites) | Later |
|---|---|---|
| ENG-1 winner on tick, BE-3 room cleanup, BE-1 turn timer, BE-2 reconnect, BE-4 surrender, BE-5 room lock, SEC-1/2 | Per-game seeded RNG (ENG-7); structured battle events (FE-1); keep `view_for` the only state path; key matches by `user_id` (needed by reconnect) | Redis-backed state + multi-instance, private matches, ranking/ladder, replays, spectating |

## 7. What should NOT be changed

- The engine/transport/content split and the engine's purity.
- `view_for` / `broadcast_state` as the only way state reaches clients; `GameError` + `report_error` contract.
- Snapshot + in-place rollback in `resolve_turn`; mutate module state in place.
- The data-driven skill format (extend it; don't add per-character code paths).
- Saga-versioned ids and the universal 4th skill convention.
- `seed_db.py` never touching account tables.
- Vanilla JS without a build step (restructure into modules instead; no framework needed at this size).
- Python/Flask/Socket.IO stack (see DEPLOY_PLAN §1 for why it fits).
