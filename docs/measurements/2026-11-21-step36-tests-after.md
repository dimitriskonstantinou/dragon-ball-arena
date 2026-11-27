# tests.py (full) -- 2026-11-21 23:37 -- git 415bbea + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.5s |
| content | ok | 53 | 0 | 0 | 0.7s |
| config | ok | 67 | 0 | 0 | 11.3s |
| rate_limit | ok | 10 | 0 | 0 | 0.4s |
| migrations | ok | 17 | 0 | 0 | 10.1s |
| smoke | ok | 163 | 0 | 0 | 10.9s |
| browser | ok | 39 | 0 | 0 | 34.6s |
| postgres | ok | 17 | 0 | 0 | 15.7s |
| smoke_postgres | ok | 163 | 0 | 0 | 10.4s |
| container | ok | 27 | 0 | 0 | 83.4s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.343 ms per turn with 18 ticking statuses (baseline 0.345)
exploit probe: 1 confirmed, 35 not reproduced (8.0s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
ALL GREEN in 193s
