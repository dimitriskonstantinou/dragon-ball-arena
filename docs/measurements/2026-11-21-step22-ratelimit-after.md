# Measurement - 2026-11-21 13:06
git: 54358c3 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 181 | 0 | 0.26s |
| content | ok | 53 | 0 | 0.36s |
| config | ok | 45 | 0 | 4.13s |
| rate_limit | ok | 10 | 0 | 0.07s |
| smoke | ok | 117 | 0 | 5.70s |
| browser | ok | 34 | 0 | 31.21s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                441     61    86%
config.py              72      0   100%
content_loader.py     132      5    96%
content_schema.py     154      7    95%
game_engine.py        553     49    91%
models.py              78      0   100%
rate_limit.py          44      0   100%
seed_db.py              9      9     0%
---------------------------------------
TOTAL                1483    131    91%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:76:47: f-string is missing placeholders
    backend\test_integration_smoke.py:379:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 672 | 28370 |
| backend\config.py | 147 | 6726 |
| backend\content_loader.py | 193 | 8264 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 933 | 43114 |
| backend\models.py | 143 | 6124 |
| backend\rate_limit.py | 63 | 2243 |
| backend\seed_db.py | 25 | 881 |
| backend\test_browser_e2e.py | 425 | 20446 |
| backend\test_config.py | 171 | 9556 |
| backend\test_content.py | 263 | 13158 |
| backend\test_game_engine.py | 1195 | 62763 |
| backend\test_integration_smoke.py | 936 | 52049 |
| backend\test_rate_limit.py | 86 | 2912 |
| frontend\app.js | 664 | 26116 |
| frontend\index.html | 117 | 5669 |
| frontend\style.css | 133 | 8389 |
| **total** | **6518** | **308143** |

Frontend first-load (html+css+js): 39.2 KB own code + 43.2 KB vendored libraries = 82.4 KB, all from our own server

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
update-state payload (sample 3v3): 11654 bytes
update-state payload actually sent per player (view_for): 8420 bytes

