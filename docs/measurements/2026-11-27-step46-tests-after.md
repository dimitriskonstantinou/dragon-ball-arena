# tests.py (full) -- 2026-11-27 23:41 -- git 23bdbf2 + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.8s |
| content | ok | 59 | 0 | 0 | 1.0s |
| config | ok | 110 | 0 | 0 | 24.1s |
| rate_limit | ok | 10 | 0 | 0 | 0.5s |
| migrations | ok | 17 | 0 | 0 | 12.9s |
| smoke | ok | 234 | 0 | 0 | 14.2s |
| web | ok | 8 | 0 | 0 | 6.4s |
| browser | ok | 50 | 0 | 0 | 50.1s |
| postgres | ok | 17 | 0 | 0 | 21.4s |
| smoke_postgres | ok | 234 | 0 | 0 | 14.4s |
| container | ok | 37 | 0 | 0 | 123.4s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8636 bytes (baseline 8636)
engine: 0.307 ms per turn with 18 ticking statuses (baseline 0.314)
exploit probe: 1 confirmed, 39 not reproduced (11.3s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:627:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

Baseline updated: tools\tests_baseline.json (commit it with the change)
## Verdict
ALL GREEN in 288s
