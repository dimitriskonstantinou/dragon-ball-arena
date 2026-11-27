# tests.py (full) -- 2026-11-24 22:54 -- git 15dee9d + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.5s |
| content | ok | 53 | 0 | 0 | 0.6s |
| config | ok | 90 | 0 | 0 | 10.0s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 9.8s |
| smoke | ok | 217 | 0 | 0 | 11.8s |
| browser | ok | 46 | 0 | 0 | 44.6s |
| postgres | ok | 17 | 0 | 0 | 14.9s |
| smoke_postgres | ok | 217 | 0 | 0 | 15.8s |
| container | ok | 28 | 0 | 0 | 90.6s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.296 ms per turn with 18 ticking statuses (baseline 0.255)
exploit probe: 1 confirmed, 38 not reproduced (7.8s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

Baseline updated: tools\tests_baseline.json (commit it with the change)
## Verdict
ALL GREEN in 213s
