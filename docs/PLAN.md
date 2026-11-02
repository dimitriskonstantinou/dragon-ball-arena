# Dragon Ball Arena — Project Review & Plan

Review date: 2026-11-02 · Reviewed at `395fb22` + uncommitted Tien/Yamcha work on `feature/goku-rework-and-ui`.
Baseline numbers: [measurements/2026-11-02-baseline.md](measurements/2026-11-02-baseline.md).
UI work has its own plan: [UI_PLAN.md](UI_PLAN.md).

---

## 1. Measurement protocol (applies to every change)

1. `python tools/measure.py --save docs/measurements/<date>-<item>-before.md`
2. Make the change (with a test that would have caught the problem).
3. `python tools/measure.py --save docs/measurements/<date>-<item>-after.md`
4. Compare. **No regressions allowed**: test FAIL count stays 0, PASS count only grows,
   coverage doesn't drop, pyflakes issues don't grow, asset KB / payload bytes only shrink
   unless the change is meant to add them.

`tools/measure.py` never touches `backend/game.db` (the smoke test runs against a temp DB).
Optional extras it uses if installed: `pip install coverage pyflakes pillow`.

### Baseline (2026-11-02)

| Metric | Value |
|---|---|
| Engine tests | 32 functions / 95 checks, all pass, 0.06s |
| Smoke test | 21 checks, all pass, 1.4s |
| Coverage | 82% total — `game_engine.py` 88%, `app.py` 73%, `seed_db.py` 0% |
| pyflakes | 2 (both cosmetic, in the smoke test) |
| Code | 3,526 lines (backend 2,639 · frontend 887) |
| Frontend first load | 37.7 KB (+ socket.io from CDN) |
| Photos | 26 files, 2,037 KB; **26/26 have the wrong extension**; 21 skill icons >256px = 1,840 KB (rendered at 32px) |
| Content | 5 characters, 20 skills, 0 missing images, 20/20 descriptions hardcode the cost |
| `update-state` payload | ~11–12 KB per broadcast (3v3) |
| Confirmed bugs/exploits | 18 (see §3, reproduced with a probe script) |

---

## 2. What's good — keep it

- **Clean three-way split**: `game_engine.py` is pure functions over plain dicts (no Flask, no DB),
  `app.py` is transport/auth/matchmaking, `characters.py` is content. The engine can be tested in
  milliseconds without a server, and that's the right foundation.
- **Data-driven skills**: skills are lists of composable effects; any effect can be redirected to the caster
  with `"target": "self"`. New characters rarely need new engine code.
- **Comments explain *why***, not just *what* (tick model, `2N+2` priming durations, why
  `ENDED_ROOMS` exists). Keep that style.
- **Tests exist and are meaningful**: per-mechanic unit tests, per-character kit tests, a content
  smoke test that catches typo'd effect types, and an in-process full-stack test (HTTP + Socket.IO + DB).
- **Server owns the turn**: actions are checked against the socket that owns the player slot.
- **Sensible auth basics**: werkzeug password hashing, session cookies, socket auth via the same cookie.
- **Safe seeding**: `seed_db.py` only touches `characters`, never accounts/stats/matches.
- **Pinned dependencies**; SQLAlchemy keeps Postgres a connection-string change.

---

## 3. What's wrong — confirmed problems

All items marked ✅ were **reproduced** by running code, not just read.

### P0 — Cheating / correctness (fix first)

| # | Problem | Where | Fix |
|---|---|---|---|
| 1 ✅ | **Skills are free.** `resolve_turn` only checks the player *owns* the dice they send, never that they cover the queued costs. Sending `paymentList: []` casts everything. | [game_engine.py:680](../backend/game_engine.py#L680) | Compute required specific + random counts from `pending_moves`; require payment to match exactly. |
| 2 ✅ | `queue_move` never checks affordability, so you can queue more than your pool covers. | [game_engine.py:617](../backend/game_engine.py#L617) | Check cost against pool minus already-queued costs (specific first, then random). Same algorithm in the client. |
| 3 ✅ | **Targets not validated**: a `self` skill can be cast on another ally, out-of-range index is accepted (skill wasted, still goes on cooldown), dead enemies can be targeted, `targetPlayerKey` is ignored. | `queue_move` / `resolve_turn` | Validate `target_type` ↔ side ↔ index ↔ alive in `queue_move`; `self` forces the actor. |
| 4 ✅ | Dead characters can queue moves (silently skipped on resolve). | `queue_move` | Reject when `actor.health <= 0`. |
| 5 ✅ | **Hidden info is sent to the opponent**: the "invisible" Wolf Fang Fist mark, your live `pending_moves` (broadcast on every queue), and both players' socket ids are all in the shared `update-state`. | [app.py:341](../backend/app.py#L341) etc. | Add `view_for(game, role)` that strips invisible enemy statuses, enemy pending moves and sids; emit per player, not to the room. |
| 6 ✅ | `set_skill_cost_on_stack` with `description_template` → `NameError` (`new_value` is from a different branch). | [game_engine.py:446](../backend/game_engine.py#L446) | Use the effect's own value / drop the template there. Add a test. |
| 7 ✅ | Stale skill text: `scale_skill_by_stack` ignores its `description_template` (Kaioken Attack keeps saying "Locked until…"), and Kaioken still says "1 Rand" after its cost becomes 2. | `game_engine.py:427`, `characters.py` | Apply the template; remove cost text from descriptions (see #18). |
| 8 ✅ | Wolf Fang Fist counter damage is applied inside `queue_move`, which then **raises**; `app.py` only sends the error to the sender and **doesn't broadcast state**, so the HP loss is invisible until the next update. Exceptions are being used as game events. | `game_engine.py:644`, `app.py:342` | Return a result (`{'countered': dmg}`) instead of raising; broadcast state + a log event. |
| 9 | `resolve_turn` isn't atomic: dice are removed first, then a crash mid-loop leaves a half-resolved turn. | `game_engine.py:691` | Validate everything up front, then apply. |
| 10 | Every engine error is a bare `Exception`, so real bugs (KeyError, NameError) are shown to players as chat messages and swallowed. | engine + `app.py` | Add `class GameError(Exception)`; catch only that for user messages; log everything else with a traceback. |

### P1 — Match lifecycle & server robustness

| # | Problem | Fix |
|---|---|---|
| 11 | **No turn timer**: an opponent can stall forever and the match never ends. | Server-side per-turn deadline (e.g. 60s) via `socketio.start_background_task`; auto-pass on expiry; send `turn_deadline` in state. |
| 12 | **Refresh = forfeit**: disconnect ends the match instantly; no reconnect. | Key games by `user_id`, give a ~30s reconnect grace, re-send state on connect. |
| 13 | No surrender. | `surrender` event → `end_game`. |
| 14 ✅ | Same account can queue twice (two tabs) and play itself; stats get recorded for both sides. | Dedupe the queue by `user_id`; reject self-matches. |
| 15 ✅ | Socket payloads aren't validated (`find-match` with a non-list crashes; `cancel-skill` without `myPlayerKey` → KeyError). | Validate shape/types at the top of every handler; don't trust `myPlayerKey` at all, derive the role from `request.sid`. |
| 16 ✅ | `GAMES` and `ENDED_ROOMS` are never pruned (memory grows forever). | Remove the room on `end_game` (after the final emit) or after a short delay. |
| 17 | Default async mode is threading, so concurrent handlers mutate shared dicts with no locking. | Per-room `threading.Lock` (or move to eventlet/gevent for deploy). |

### P1 — Security hygiene

| # | Problem | Fix |
|---|---|---|
| 18 ✅ | `cors_allowed_origins="*"` with cookie auth → cross-site websocket hijacking possible. | Allowed origins from env (default same-origin). |
| 19 ✅ | `SECRET_KEY` silently falls back to a hardcoded value. | Refuse to start without it outside dev (`FLASK_ENV`/`DEBUG` flag). |
| 20 | Session cookie has no explicit `SameSite`; no login rate limit; usernames are case-sensitive ("Goku" vs "goku" both allowed); email format not checked. | `SESSION_COOKIE_SAMESITE='Lax'`; simple per-IP attempt counter; case-insensitive unique username; basic email regex. |
| 21 | Client builds HTML with `innerHTML` + inline `onclick="...'${id}'..."` from server strings. Safe today (content is authored), unsafe the moment any text is user-provided (usernames in a log, chat). | Covered by the UI rewrite: DOM APIs / `textContent`, event delegation. |

---

## 4. Remove

| What | Where | Why |
|---|---|---|
| `socket.on('opponent-left')` | `app.js:156` | Server never emits it. |
| `renderDice(..., clickable)` + `onPaymentDieClick` | `app.js:269-276` | `onPaymentDieClick` doesn't exist; parameter is never true. |
| `.random-slot.filled`, `.die.selected` | `style.css` | Unused. |
| `animation: pulse` | `style.css:218` | `@keyframes pulse` is never defined, so targeting has no pulse at all. Define it or remove it (UI plan replaces it). |
| `updateTitle()` "Earth (P1)" / "Saiyan (P2)" | `app.js:643` | Leftover from an old prototype. |
| Legacy single-`effect` fallback | `game_engine.py:718` | No content uses `skill['effect']`. |
| `aoe_damage` effect type *(optional)* | engine + 1 test | Superseded by `target_type: enemy_team` + `damage`; no content uses it. |
| `"maxHealth"`, `"status"` in character templates | `characters.py` | `Character.to_game_dict()` builds them; duplicates go stale. |
| Duplicate seeding logic | `app.py:ensure_db_ready` | Duplicates `seed_db.seed()`; call one function. |
| Duplicate "restore primed skill" code | `game_engine.py:504-519` and `551-568` | Same 15 lines twice; extract `_restore_primed(skill)`. |
| `"| 1 Eng, 1 Rand"` cost suffixes | all 20 descriptions | The UI already draws cost boxes from `cost`; the text drifts (Kaioken already wrong). |
| 2 `f`-strings without placeholders | `test_integration_smoke.py:67,193` | Lint noise. |

---

## 5. Update

| What | Detail |
|---|---|
| **Source of truth for content** *(decided 2026-11-02)* | Content is authored in `characters.py` for now. In production the DB is synced from it automatically on every deploy (release step, see [DEPLOY_PLAN.md](DEPLOY_PLAN.md) Stage 2). Locally, reseed when a batch of content edits is done. |
| **Image assets** | Give files their real extensions (they're JPEG/WEBP named `.png`) and resize: skill icons → 128×128 WEBP, portraits → max 480px. Expected: 1,840 KB → ~100–150 KB for icons. Add a small `tools/optimize_images.py` (Pillow) so new art is normalized on the way in. |
| **README** | Wrong in places: says both sides' moves "resolve simultaneously" (they don't, turns alternate); "Known limitations" lists delayed effects/marks/redirects as missing (they exist now); effect table is missing `protect`, `delayed_damage`, `random_multi_damage`, `damage_ignore_invuln`, `expiring_defense`, `mark_for_counter`, `set_skill_cost_on_stack`, `prime_skill`/`unprime_skill`. |
| **Integration test DB** | Defaults to the real `game.db`. Make it default to a temp DB (it already honors `DATABASE_URL`). |
| **Tests** | Add a regression test for every P0/P1 fix. Raise `app.py` coverage (73%): error paths, disconnect, cancel, auth validation. Optionally make the scripts pytest-compatible (plain `assert`) while keeping `python test_x.py` working. |
| **Engine dispatch** *(later, only when it hurts)* | The ~40-branch `if/elif` in `apply_effect` → a `EFFECTS = {'damage': _damage, ...}` registry. Makes the content smoke test trivially exact (`type in EFFECTS`). |
| **Client affordability math** | `calculateRemainingDice` spends random costs with `pool.shift()`, so it can wrongly grey out skills. Use the same "specific first, then random" algorithm as the server fix (#2). |
| **socket.io client** | Pinned at 4.5.4 from cdn.socket.io; serve it from Flask (`/static`) or add SRI so the game doesn't depend on a third-party CDN at runtime. |

---

## 6. Add (after the foundation is solid)

- **Structured battle events** from the server (`{actor, skill, target, damage, statuses}`) → readable battle log + floating damage numbers. Biggest single UX gap: today you can't see what the opponent did.
- Turn timer, surrender, reconnect (P1 #11–13).
- Lobby: view a character's skills before picking; remember last team.
- **Progression**: the `Mission` / `UserMissionProgress` tables exist but aren't wired. Open questions from README still apply (auto-tracked vs manual; JSON skills vs normalized).
- Leaderboard + match history page (`Match` table already records results).
- Deployment: Postgres via `DATABASE_URL`, eventlet/gevent worker, env-based config, HTTPS. Don't deploy SQLite on an ephemeral-disk host.
- Roster growth: every character gets the universal `afterimage_technique` 4th skill (done for all 5 now).

---

## 7. Phased roadmap

Each phase goes on its own feature branch off `main` and merges only when green.
**Before Phase 1:** decide what to do with the uncommitted Tien/Yamcha work on `feature/goku-rework-and-ui` (commit it first so the fixes start from a clean tree).

### Phase 0 — Safety net ✔ (this review)
- [x] `tools/measure.py` + baseline snapshot
- [x] `CLAUDE.md`, this plan, UI plan
- [ ] Smoke test defaults to a temp DB

### Phase 1 — Anti-cheat & correctness (P0 #1–10)
- [ ] `GameError`; engine raises only that for player errors
- [ ] Server-side cost validation in `queue_move` + exact payment check in `resolve_turn`
- [ ] Target validation (side, index, alive, `self` = actor), dead-actor rejection
- [ ] Atomic `resolve_turn`
- [ ] Counter-mark returns a result instead of raising; state broadcast
- [ ] Fix `set_skill_cost_on_stack` NameError; apply `scale_skill_by_stack` description template
- [ ] `view_for(game, role)` per-player state (no invisible statuses, no enemy queue, no sids)
- **Done when:** probe script reports 0 of items 1–12 reproduced; new regression tests pass; payload bytes ≤ baseline.

### Phase 2 — Match lifecycle (P1 #11–17)
- [ ] Derive role from `request.sid`; validate all socket payloads
- [ ] Queue dedupe by `user_id`
- [ ] Turn timer + auto-pass; surrender; reconnect grace window
- [ ] Prune finished rooms; per-room lock
- **Done when:** smoke test covers surrender, timeout and reconnect; `app.py` coverage ≥ 85%.

### Phase 3 — Security hygiene & cleanup (#18–21, §4, §5)
- [ ] CORS origins + SECRET_KEY + cookie flags + login rate limit + case-insensitive usernames
- [ ] Remove dead code / duplicates listed in §4
- [ ] Strip cost text from descriptions
- [ ] Image extensions + resize + `tools/optimize_images.py`
- [ ] README refresh
- **Done when:** pyflakes = 0; photo KB ≤ 400; "extension != real format" = 0; "hardcoded cost text" = 0.

### Phase 4 — UI overhaul → [UI_PLAN.md](UI_PLAN.md)
Depends on Phase 1 (per-player view) and the battle-events item in §6.

### Phase 5 — Content & progression
Battle events, roster growth, missions/unlocks, leaderboard.

### Phase 6 — Deployment → [DEPLOY_PLAN.md](DEPLOY_PLAN.md)
Stage 0 of the deploy plan = Phases 1–3 here. Stages 1–9 can start in parallel with Phase 4/5.
