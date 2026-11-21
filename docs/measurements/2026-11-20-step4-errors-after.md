# Measurement - 2026-11-20 19:29
git: 45dba7a (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 136 | 0 | 0.07s |
| smoke | ok | 29 | 0 | 1.57s |

## Coverage (backend, tests excluded)
```
Name             Stmts   Miss  Cover
------------------------------------
app.py             266     65    76%
characters.py        1      0   100%
game_engine.py     509     57    89%
models.py           83      0   100%
seed_db.py          25     25     0%
------------------------------------
TOTAL              884    147    83%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:67:47: f-string is missing placeholders
    backend\test_integration_smoke.py:213:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 413 | 15457 |
| backend\characters.py | 335 | 18627 |
| backend\game_engine.py | 857 | 40315 |
| backend\models.py | 154 | 6401 |
| backend\seed_db.py | 50 | 1789 |
| backend\test_game_engine.py | 970 | 50791 |
| backend\test_integration_smoke.py | 282 | 15088 |
| frontend\app.js | 644 | 25258 |
| frontend\index.html | 114 | 5331 |
| frontend\style.css | 129 | 8040 |
| **total** | **3948** | **187097** |

Frontend first-load (html+css+js, excl. CDN socket.io): 37.7 KB

## Assets (backend/photos)
26 files, 2037 KB total
extension != real format: 26
skill icons > 256px (rendered at 32px): 21, 1840 KB

## Roster / content integrity
5 characters, 20 skills
images referenced but missing: 0 
images on disk but unreferenced: 0 
descriptions with hardcoded cost text: 20
update-state payload (sample 3v3): 11338 bytes
update-state payload actually sent per player (view_for): 11312 bytes

