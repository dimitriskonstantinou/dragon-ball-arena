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

**Merged into `dev`:** none of steps 1–11 yet (user merges in order).
