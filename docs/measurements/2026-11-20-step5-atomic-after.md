# Measurement - 2026-11-20 19:31
git: 9342276 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 147 | 0 | 0.09s |
| smoke | ok | 30 | 0 | 1.62s |

## Coverage (backend, tests excluded)
```
Name             Stmts   Miss  Cover
------------------------------------
app.py             266     65    76%
characters.py        1      0   100%
game_engine.py     524     57    89%
models.py           83      0   100%
seed_db.py          25     25     0%
------------------------------------
TOTAL              899    147    84%
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
| backend\game_engine.py | 878 | 41419 |
| backend\models.py | 154 | 6401 |
| backend\seed_db.py | 50 | 1789 |
| backend\test_game_engine.py | 1025 | 53442 |
| backend\test_integration_smoke.py | 289 | 15526 |
| frontend\app.js | 644 | 25258 |
| frontend\index.html | 114 | 5331 |
| frontend\style.css | 129 | 8040 |
| **total** | **4031** | **191290** |

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

