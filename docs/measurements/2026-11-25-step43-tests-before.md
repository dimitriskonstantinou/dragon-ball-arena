# tests.py (full) -- 2026-11-25 22:21 -- git dda1fab

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.4s |
| content | ok | 53 | 0 | 0 | 0.5s |
| config | ok | 102 | 0 | 0 | 11.8s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 7.4s |
| smoke | ok | 217 | 0 | 0 | 10.7s |
| browser | ok | 46 | 0 | 0 | 45.0s |
| postgres | ok | 17 | 0 | 0 | 11.0s |
| smoke_postgres | ok | 217 | 0 | 0 | 11.4s |
| container | ok | 29 | 0 | 0 | 82.9s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.276 ms per turn with 18 ticking statuses (baseline 0.268)
exploit probe: 1 confirmed, 39 not reproduced (8.2s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
ALL GREEN in 195s
