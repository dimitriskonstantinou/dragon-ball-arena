# Measurement - 2026-11-02 23:48
git: 55d4cbe (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 128 | 0 | 0.05s |
| smoke | ok | 25 | 0 | 1.21s |

## Coverage (backend, tests excluded)
```
Name             Stmts   Miss  Cover
------------------------------------
app.py             251     64    75%
characters.py        1      0   100%
game_engine.py     502     56    89%
models.py           83      0   100%
seed_db.py          25     25     0%
------------------------------------
TOTAL              862    145    83%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:67:47: f-string is missing placeholders
    backend\test_integration_smoke.py:213:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 390 | 14251 |
| backend\characters.py | 335 | 18627 |
| backend\game_engine.py | 837 | 38550 |
| backend\models.py | 154 | 6401 |
| backend\seed_db.py | 50 | 1789 |
| backend\test_game_engine.py | 932 | 47527 |
| backend\test_integration_smoke.py | 248 | 12547 |
| frontend\app.js | 644 | 25258 |
| frontend\index.html | 114 | 5331 |
| frontend\style.css | 129 | 8040 |
| **total** | **3833** | **178321** |

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
update-state payload (sample 3v3): 11339 bytes
update-state payload actually sent per player (view_for): 11313 bytes

