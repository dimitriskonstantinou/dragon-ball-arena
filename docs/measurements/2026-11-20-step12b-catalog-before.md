# Measurement - 2026-11-20 20:43
git: 8c7395b

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 167 | 0 | 0.40s |
| content | ok | 53 | 0 | 0.63s |
| smoke | ok | 45 | 0 | 2.29s |
| browser | ok | 14 | 0 | 15.18s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                275     51    81%
characters.py           2      0   100%
content_loader.py     127      5    96%
content_schema.py     154      7    95%
game_engine.py        533     50    91%
models.py              83      0   100%
seed_db.py             25     25     0%
---------------------------------------
TOTAL                1199    138    88%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:67:47: f-string is missing placeholders
    backend\test_integration_smoke.py:236:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 426 | 16687 |
| backend\characters.py | 11 | 416 |
| backend\content_loader.py | 181 | 7977 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 895 | 41516 |
| backend\models.py | 154 | 6401 |
| backend\seed_db.py | 50 | 1789 |
| backend\test_browser_e2e.py | 296 | 12885 |
| backend\test_content.py | 264 | 13173 |
| backend\test_game_engine.py | 1145 | 59766 |
| backend\test_integration_smoke.py | 392 | 21247 |
| frontend\app.js | 638 | 25024 |
| frontend\index.html | 114 | 5331 |
| frontend\style.css | 129 | 8040 |
| **total** | **5047** | **231615** |

Frontend first-load (html+css+js, excl. CDN socket.io): 37.5 KB

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
update-state payload (sample 3v3): 11652 bytes
update-state payload actually sent per player (view_for): 8418 bytes

