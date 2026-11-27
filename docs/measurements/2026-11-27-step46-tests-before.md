# tests.py (full) -- 2026-11-27 23:22 -- git 23bdbf2

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.6s |
| content | ok | 59 | 0 | 0 | 0.7s |
| config | ok | 110 | 0 | 0 | 19.8s |
| rate_limit | ok | 10 | 0 | 0 | 0.4s |
| migrations | ok | 17 | 0 | 0 | 12.3s |
| smoke | ok | 226 | 0 | 0 | 15.2s |
| browser | ok | 46 | 0 | 0 | 45.6s |
| postgres | ok | 17 | 0 | 0 | 17.8s |
| smoke_postgres | ok | 226 | 0 | 0 | 15.4s |
| container | ok | 34 | 0 | 0 | 117.7s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8636 bytes (baseline 8636)
engine: 0.369 ms per turn with 18 ticking statuses (baseline 0.314)
exploit probe: 1 confirmed, 39 not reproduced (12.7s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:592:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
ALL GREEN in 266s
