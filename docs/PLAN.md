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

**Merged into `dev`:** none of steps 1–17 yet (user merges in order).
