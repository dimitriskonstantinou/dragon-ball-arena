# tests.py (full) -- 2026-11-25 22:39 -- git dda1fab + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.4s |
| content | ok | 53 | 0 | 0 | 0.5s |
| config | ok | 110 | 0 | 0 | 12.8s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 7.5s |
| smoke | ok | 219 | 0 | 0 | 11.1s |
| browser | ok | 46 | 0 | 0 | 46.7s |
| postgres | ok | 17 | 0 | 0 | 12.8s |
| smoke_postgres | ok | 219 | 0 | 0 | 11.6s |
| container | ok | 33 | 0 | 0 | 87.4s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.291 ms per turn with 18 ticking statuses (baseline 0.268)
exploit probe: 1 confirmed, 39 not reproduced (8.8s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:550:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

Baseline updated: tools\tests_baseline.json (commit it with the change)
## Verdict
ALL GREEN in 206s
