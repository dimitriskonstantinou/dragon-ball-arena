# tests.py (full) -- 2026-11-27 19:19 -- git 66d8a5c + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.8s |
| content | ok | 53 | 0 | 0 | 1.1s |
| config | ok | 110 | 0 | 0 | 26.4s |
| rate_limit | ok | 10 | 0 | 0 | 0.6s |
| migrations | ok | 17 | 0 | 0 | 15.7s |
| smoke | ok | 219 | 0 | 0 | 17.7s |
| browser | ok | 46 | 0 | 0 | 46.5s |
| postgres | ok | 17 | 0 | 0 | 18.9s |
| smoke_postgres | ok | 219 | 0 | 0 | 18.8s |
| container | ok | 33 | 0 | 0 | 125.6s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.297 ms per turn with 18 ticking statuses (baseline 0.291)
exploit probe: 1 confirmed, 39 not reproduced (9.6s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:550:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
ALL GREEN in 293s
