# tests.py (full) -- 2026-11-21 23:13 -- git de4bcae + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.6s |
| content | ok | 53 | 0 | 0 | 0.7s |
| config | ok | 67 | 0 | 0 | 10.7s |
| rate_limit | ok | 10 | 0 | 0 | 0.4s |
| migrations | ok | 17 | 0 | 0 | 10.2s |
| smoke | ok | 163 | 0 | 0 | 10.0s |
| browser | ok | 39 | 0 | 0 | 37.7s |
| postgres | ok | 17 | 0 | 0 | 15.0s |
| smoke_postgres | ok | 163 | 0 | 0 | 10.1s |
| container | ok | 27 | 0 | 0 | 83.1s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.345 ms per turn with 18 ticking statuses (baseline 0.294)
exploit probe: 1 confirmed, 35 not reproduced (8.0s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

Baseline updated: tools\tests_baseline.json (commit it with the change)
## Verdict
ALL GREEN in 193s
