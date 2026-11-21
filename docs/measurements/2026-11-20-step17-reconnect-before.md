# Measurement - 2026-11-20 21:44
git: 5c18e1b (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 177 | 0 | 0.36s |
| content | ok | 53 | 0 | 0.55s |
| smoke | ok | 80 | 0 | 4.16s |
| browser | ok | 21 | 0 | 30.12s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                360     59    84%
content_loader.py     132      5    96%
content_schema.py     154      7    95%
game_engine.py        550     50    91%
models.py              78      0   100%
seed_db.py              9      9     0%
---------------------------------------
TOTAL                1283    130    90%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:71:47: f-string is missing placeholders
    backend\test_integration_smoke.py:298:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 561 | 23004 |
| backend\content_loader.py | 193 | 8264 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 926 | 42846 |
| backend\models.py | 143 | 6124 |
| backend\seed_db.py | 25 | 881 |
| backend\test_browser_e2e.py | 335 | 15367 |
| backend\test_content.py | 263 | 13158 |
| backend\test_game_engine.py | 1184 | 62254 |
| backend\test_integration_smoke.py | 719 | 38456 |
| frontend\app.js | 658 | 25847 |
| frontend\index.html | 115 | 5367 |
| frontend\style.css | 131 | 8163 |
| **total** | **5605** | **261094** |

Frontend first-load (html+css+js, excl. CDN socket.io): 38.5 KB

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
update-state payload (sample 3v3): 11647 bytes
update-state payload actually sent per player (view_for): 8413 bytes

