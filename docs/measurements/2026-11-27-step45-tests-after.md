# tests.py (full) -- 2026-11-27 20:47 -- git 6e535e4 + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.5s |
| content | ok | 59 | 0 | 0 | 0.7s |
| config | ok | 110 | 0 | 0 | 16.6s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 8.3s |
| smoke | ok | 226 | 0 | 0 | 12.8s |
| browser | ok | 46 | 0 | 0 | 44.2s |
| postgres | ok | 17 | 0 | 0 | 11.9s |
| smoke_postgres | ok | 226 | 0 | 0 | 12.5s |
| container | ok | 34 | 0 | 0 | 92.0s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8636 bytes (baseline 8606)
engine: 0.314 ms per turn with 18 ticking statuses (baseline 0.272)
exploit probe: 1 confirmed, 39 not reproduced (8.6s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:592:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

Baseline updated: tools\tests_baseline.json (commit it with the change)
## Verdict
ALL GREEN in 214s
