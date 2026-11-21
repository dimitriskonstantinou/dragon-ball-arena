# Dragon Ball Arena — Step Log

This file records **what has been executed**: one row per step, with its branch and measured effect.

- Current findings: [PROJECT_AUDIT.md](PROJECT_AUDIT.md)
- What comes next: [MASTER_ROADMAP.md](MASTER_ROADMAP.md)
- Raw before/after reports: [measurements/](measurements/)

(Until 2026-11-20 this file held the first review and phase plan. Those were superseded by the audit and roadmap
and are in git history: `git show 0b0e465:docs/PLAN.md`.)

## Protocol

Every step: own branch `feature/stepN-<name>` (from the previous step's branch) → `tools/measure.py --save
docs/measurements/<date>-stepN-<name>-before.md` (+ probe) → change + regression tests → same measurements
`-after` → docs updated → commit + push → report → wait for approval. No regressions: FAIL stays 0, PASS and
coverage don't drop, pyflakes doesn't grow.

## Steps

| Step | Branch | What changed | Measured effect |
|---|---|---|---|
| 0 | `dev` (`86a42d9`) | First review, plans, CLAUDE.md, `measure.py`, `probe_exploits.py` | Baseline: 95 engine + 21 smoke checks, 82% cov, 18 confirmed bugs |
| 1 | `feature/step1-cost-validation` | Server validates Ki costs on queue and exact payment on commit (skills were free) | checks 95→109 / 21→22, bugs 18→16 |
| 2 | `feature/step2-target-validation` | Target side/index/alive validated; `self` forced to caster; dead actors rejected | checks →122, bugs →12 |
| 3 | `feature/step3-per-player-view` | `view_for` + `broadcast_state`: no opponent queue, hidden traps or ids sent | smoke →25, bugs →10 |
| 4 | `feature/step4-game-errors` | `GameError` vs logged bugs; counter-trap is a broadcast event; lethal counter ends match | checks →136 / →29, bugs →9 |
| 5 | `feature/step5-atomic-resolve` | `resolve_turn` validates first, applies on a snapshot, rolls back in place | checks →147 / →30, cov 84% |
| 6 | `feature/step6-skill-text` | Kaioken texts update correctly; `set_skill_cost_on_stack` NameError removed | checks →153, bugs →6; payload +2.7% |
| 7 | `feature/step7-lean-view` | Skill `effects`/`base_*` no longer sent to clients | payload 11,624→8,414 B (−26% vs baseline) |
| 8 | `feature/step8-socket-validation` | Identity from connection; payload validation; cancel/duplicate-team bugs fixed | smoke →37, cov 85%, bugs →5 |
| 9 | `feature/step9-one-account-one-seat` | One account can't queue twice or play itself | smoke →43, cov 86%, bugs →4 |
| 10 | `feature/step10-audit` | Full audit, master roadmap, CLAUDE.md rewrite (docs only) | Baseline re-recorded; 0 code changes |
| 11 | `feature/step11-winner-on-tick` | ENG-1: a team wiped by a turn-start tick loses immediately; decisions recorded | checks 162→167 / 43→44, bugs 5→4 |
| 12a | `feature/step12a-content-pipeline` | Content as JSON files (single source) + Pydantic validation + VS Code schemas; Playwright browser tests; Spirit Ball icon 404 fixed | checks 211→279 (+content 53, +browser 14, smoke +1); cov 86→88%; probe 4=4 |
| 12b | `feature/step12b-catalog-runtime` | Gameplay reads the in-memory catalog; `characters` table = id registry synced at startup (never deleted); shim removed; lobby display-only; all-unlocked policy applied to old accounts | SQL per connect/find-match 3→1 (0 roster reads); lobby 10,343→7,437 B; smoke 45→53; cov 88→90% |
| 13 | `feature/step13-prune-finished-matches` | `end_game` pops the room first (exactly-once guard), sends final state, closes the Socket.IO room; `ENDED_ROOMS` removed | 220/220 matches kept → 0; ~30 KB/match → flat; smoke 53→59; probe 4→3 |
| 14 | `feature/step14-safe-match-end` | A failed result save is caught, rolled back and logged; both players still get the final state | final states on DB failure 0/2 → 2/2; smoke 59→65; probe 4→3 |
| 15 | `feature/step15-room-lock` | Lock per match (`locked_match`) + matchmaking lock; reproduced 2 real races first (double commit skipped the opponent's turn; simultaneous tabs self-matched) | double commit 2 turns → 1; probe 5→3; smoke 65→71; app cov 83→85% |
| 16 | `feature/step16-turn-timer` | Turn timer: 60 s, auto-pass, 3 timeouts in a row = forfeit; one background ticker under match locks; countdown in the UI | idle stall reproduced → fixed; engine 167→177, smoke 71→80, browser 14→21; probe 4→3 |
| 17 | `feature/step17-reconnect` | Disconnect mid-match = 30 s grace instead of instant forfeit; same account rejoins from any tab (`rejoin_match`); opponent sees connected status | reload-forfeit reproduced → fixed in a real browser; smoke 80→96, browser 21→27; probe 4→3 |
| 18 | `feature/step18-surrender` | `surrender` event (any turn) + button behind a confirm dialog; loss recorded for the surrendering player | "no way to surrender" reproduced → fixed; engine 177→181, smoke 96→102, browser 27→34; probe 4→3 |
| 19 | `feature/step19-config-secret-key` | `config.py`: validated env settings; staging/production refuse to start without a strong `SECRET_KEY`; hardcoded key removed (dev: random per-machine key file) | prod start without key: exit 0 → refused; new config suite (25 checks); probe 3→2 |
| 20 | `feature/step20-origins-cookies` | `ALLOWED_ORIGINS` (same-origin default, https list required when deployed, `*` refused); cookie `SameSite=Lax` (+`Secure` when deployed) | foreign-origin handshake 200 → 400; probe 2→1 (no exploit left); config 25→39, smoke 102→107 |
| 21 | `feature/step21-self-host-socketio` | socket.io client served from our own server (npm build, integrity-verified, sha256 pinned); browser tests fail on any third-party request | third-party requests per page load 1 → 0; smoke 107→111; Step 20's extra load timeout removed |
| 22 | `feature/step22-rate-limits` | Per-IP limits: 5 failed logins / 5 min, 5 accounts / hour → 429; in-memory sliding window (no new dependency); `TRUSTED_PROXIES` (ProxyFix) | unlimited guessing/spam reproduced → 429 after 5; probe 2→1; new rate_limit suite (10), config 39→45, smoke 111→117 |
| 23 | `feature/step23-migrations` | Flask-Migrate/Alembic: baseline migration, server upgrades on start, pre-migration DBs adopted (rehearsed on a copy of the real game.db), `create_all` removed | adoption: every row identical, 0 schema diff; new migrations suite (9); startup +~0.5 s one-time (library load; no-op upgrade 5 ms) |
| 24 | `feature/step24-session-revocation` | `users.session_version` (first real migration): logout invalidates every copy of the cookie + closes the account's sockets; 30-day expiry; fresh session per login; stricter adoption (exact baseline columns) | stolen cookie after logout 200 → 401; probe 2→1; migrations 9→11, config 45→48, smoke 117→126; rehearsed on a copy of game.db |
| 25 | `feature/step25-usernames` | `users.username_key` (second real migration; refuses look-alike duplicates): case-insensitive unique names + login; new names `[A-Za-z0-9_-]`; basic email check; `IntegrityError` → 409; probe uses a fresh temp DB per run | Goku/goku 201/201 → 201/409; bad email 201 → 400; simultaneous same name 500 → 409; probe 2→1; migrations 11→14, smoke 126→142; rehearsed on a copy of game.db |
| 26 | `feature/step26-proxy-ready` | Site-relative image URLs (`/photos/...`, never from the Host header); `GET /healthz` (200/503, no-store); logging configured at import in one format + `LOG_LEVEL` — **Phase 3 complete** | Host header in image URLs yes → no; `/healthz` 404 → 200 (503 on DB outage); ~525–675 B less per `update-state`/`character-list`; probe 2→1; config 48→53, smoke 142→147 |
| 27 | `feature/step27-mutual-ko-draw` | Mutual KO = draw (ENG-2): `check_winner` → `DRAW`; "DRAW!" in the UI + D in the badge; `matches.is_draw` + `user_stats.total_draws` (third real migration, `sa.false()` default for Postgres); a draw ends both streaks | mutual KO winner `p2` → `draw`; probe 2→1; engine 181→192, migrations 14→15, smoke 147→154; rehearsed on a copy of game.db |

**Merged into `dev`:** none of steps 1–27 yet (user merges in order).
