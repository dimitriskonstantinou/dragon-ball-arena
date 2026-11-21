# tests.py (full) -- 2026-11-21 19:04 -- git 45698e9

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.5s |
| content | ok | 53 | 0 | 0 | 0.7s |
| config | ok | 53 | 0 | 0 | 7.7s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 8.8s |
| smoke | ok | 158 | 0 | 0 | 9.3s |
| browser | ok | 39 | 0 | 0 | 35.4s |
| runner_gates | ok | 18 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.302 ms per turn with 18 ticking statuses (baseline 0.286)
exploit probe: 1 confirmed, 35 not reproduced (7.6s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:76:47: f-string is missing placeholders
    backend\test_integration_smoke.py:525:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
ALL GREEN in 74s
