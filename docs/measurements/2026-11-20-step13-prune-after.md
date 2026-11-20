# Measurement - 2026-11-20 20:55
git: 857ef22 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 167 | 0 | 0.33s |
| content | ok | 53 | 0 | 0.48s |
| smoke | ok | 59 | 0 | 1.90s |
| browser | ok | 14 | 0 | 14.84s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                285     50    82%
content_loader.py     132      5    96%
content_schema.py     154      7    95%
game_engine.py        536     50    91%
models.py              78      0   100%
seed_db.py              9      9     0%
---------------------------------------
TOTAL                1194    121    90%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:67:47: f-string is missing placeholders
    backend\test_integration_smoke.py:294:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 447 | 17882 |
| backend\content_loader.py | 193 | 8264 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 902 | 41751 |
| backend\models.py | 143 | 6124 |
| backend\seed_db.py | 25 | 881 |
| backend\test_browser_e2e.py | 300 | 13111 |
| backend\test_content.py | 263 | 13158 |
| backend\test_game_engine.py | 1145 | 59833 |
| backend\test_integration_smoke.py | 482 | 26310 |
| frontend\app.js | 638 | 25024 |
| frontend\index.html | 114 | 5331 |
| frontend\style.css | 129 | 8040 |
| **total** | **5133** | **237072** |

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
update-state payload (sample 3v3): 11653 bytes
update-state payload actually sent per player (view_for): 8419 bytes

