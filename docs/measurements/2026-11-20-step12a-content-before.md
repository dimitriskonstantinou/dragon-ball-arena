# Measurement - 2026-11-20 20:20
git: 196d6d0

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 167 | 0 | 0.08s |
| smoke | ok | 44 | 0 | 1.46s |

## Coverage (backend, tests excluded)
```
Name             Stmts   Miss  Cover
------------------------------------
app.py             269     51    81%
characters.py        1      0   100%
game_engine.py     533     52    90%
models.py           83      0   100%
seed_db.py          25     25     0%
------------------------------------
TOTAL              911    128    86%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:67:47: f-string is missing placeholders
    backend\test_integration_smoke.py:216:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 414 | 15541 |
| backend\characters.py | 337 | 18850 |
| backend\game_engine.py | 895 | 41516 |
| backend\models.py | 154 | 6401 |
| backend\seed_db.py | 50 | 1789 |
| backend\test_game_engine.py | 1145 | 59766 |
| backend\test_integration_smoke.py | 372 | 20437 |
| frontend\app.js | 638 | 25024 |
| frontend\index.html | 114 | 5331 |
| frontend\style.css | 129 | 8040 |
| **total** | **4248** | **202695** |

Frontend first-load (html+css+js, excl. CDN socket.io): 37.5 KB

## Assets (backend/photos)
26 files, 2037 KB total
extension != real format: 26
skill icons > 256px (rendered at 32px): 21, 1840 KB

## Roster / content integrity
5 characters, 20 skills
images referenced but missing: 0 
images on disk but unreferenced: 0 
descriptions with hardcoded cost text: 20
update-state payload (sample 3v3): 11648 bytes
update-state payload actually sent per player (view_for): 8414 bytes

