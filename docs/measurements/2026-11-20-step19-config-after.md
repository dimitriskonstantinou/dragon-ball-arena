# Measurement - 2026-11-20 22:09
git: 9ded4c9 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 181 | 0 | 0.25s |
| content | ok | 53 | 0 | 0.37s |
| config | ok | 25 | 0 | 2.52s |
| smoke | ok | 102 | 0 | 4.10s |
| browser | ok | 34 | 0 | 30.63s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                419     65    84%
config.py              55      0   100%
content_loader.py     132      5    96%
content_schema.py     154      7    95%
game_engine.py        553     49    91%
models.py              78      0   100%
seed_db.py              9      9     0%
---------------------------------------
TOTAL                1400    135    90%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:71:47: f-string is missing placeholders
    backend\test_integration_smoke.py:298:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 639 | 27215 |
| backend\config.py | 103 | 3954 |
| backend\content_loader.py | 193 | 8264 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 933 | 43114 |
| backend\models.py | 143 | 6124 |
| backend\seed_db.py | 25 | 881 |
| backend\test_browser_e2e.py | 419 | 20010 |
| backend\test_config.py | 114 | 5462 |
| backend\test_content.py | 263 | 13158 |
| backend\test_game_engine.py | 1195 | 62763 |
| backend\test_integration_smoke.py | 855 | 46744 |
| frontend\app.js | 664 | 26116 |
| frontend\index.html | 116 | 5465 |
| frontend\style.css | 133 | 8389 |
| **total** | **6147** | **289022** |

Frontend first-load (html+css+js, excl. CDN socket.io): 39.0 KB

## Assets (backend/photos)
26 files, 2037 KB total
extension != real format: 26
skill icons > 256px (rendered at 32px): 21, 1840 KB

## Roster / content integrity
5 characters, 20 skills
content files: 5 characters in backend/content/ (loaded + validated: 5)
images referenced but missing: 0 
images on disk but unreferenced: 0 
descriptions with hardcoded cost text: 20
update-state payload (sample 3v3): 11649 bytes
update-state payload actually sent per player (view_for): 8415 bytes

