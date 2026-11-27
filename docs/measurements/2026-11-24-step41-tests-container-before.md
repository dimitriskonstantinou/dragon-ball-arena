# tests.py (full) -- 2026-11-24 22:25 -- git 15dee9d + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.5s |
| content | ok | 53 | 0 | 0 | 0.6s |
| config | ok | 90 | 0 | 0 | 9.1s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 8.5s |
| smoke | ok | 194 | 0 | 0 | 10.2s |
| browser | ok | 39 | 0 | 0 | 35.7s |
| postgres | ok | 17 | 0 | 0 | 13.4s |
| smoke_postgres | ok | 194 | 0 | 0 | 11.3s |
| container | ok | 28 | 0 | 0 | 77.3s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.340 ms per turn with 18 ticking statuses (baseline 0.255)
exploit probe: 1 confirmed, 37 not reproduced (8.7s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
  WARN  config: 19 new check(s) -- run --update-baseline to keep them
  WARN  smoke: 31 new check(s) -- run --update-baseline to keep them
  WARN  smoke_postgres: 31 new check(s) -- run --update-baseline to keep them
ALL GREEN in 188s
