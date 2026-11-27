# Measurement - 2026-11-27 20:42
git: 6e535e4 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 229 | 0 | 0.28s |
| content | ok | 53 | 0 | 0.40s |
| config | ok | 110 | 0 | 13.87s |
| rate_limit | ok | 10 | 0 | 0.07s |
| migrations | ok | 17 | 0 | 8.61s |
| smoke | ok | 220 | 0 | 12.53s |
| browser | ok | 46 | 0 | 45.07s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                703     82    88%
config.py             113      0   100%
content_loader.py     132      5    96%
content_schema.py     154      7    95%
game_engine.py        616     44    93%
logging_setup.py       64      7    89%
models.py              83      0   100%
rate_limit.py          56      3    95%
seed_db.py              8      8     0%
---------------------------------------
TOTAL                1929    156    92%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:575:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 1099 | 51502 |
| backend\config.py | 242 | 11534 |
| backend\content_loader.py | 193 | 8264 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 1061 | 49840 |
| backend\gunicorn.conf.py | 35 | 1581 |
| backend\logging_setup.py | 126 | 5604 |
| backend\models.py | 155 | 6839 |
| backend\rate_limit.py | 82 | 2893 |
| backend\seed_db.py | 24 | 890 |
| backend\test_browser_e2e.py | 632 | 30968 |
| backend\test_config.py | 398 | 26053 |
| backend\test_content.py | 263 | 13158 |
| backend\test_game_engine.py | 1594 | 85690 |
| backend\test_integration_smoke.py | 1578 | 90148 |
| backend\test_migrations.py | 238 | 11422 |
| backend\test_postgres.py | 240 | 10888 |
| backend\test_rate_limit.py | 86 | 2912 |
| frontend\app.js | 704 | 28317 |
| frontend\index.html | 117 | 5669 |
| frontend\style.css | 134 | 8506 |
| **total** | **9353** | **464041** |

Frontend first-load (html+css+js): 41.5 KB own code + 43.2 KB vendored libraries = 84.7 KB, all from our own server

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
update-state payload (sample 3v3): 11780 bytes
update-state payload actually sent per player (view_for): 8606 bytes

