# Measurement - 2026-11-27 23:46
git: 23bdbf2 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 229 | 0 | 0.44s |
| content | ok | 59 | 0 | 0.70s |
| config | ok | 110 | 0 | 24.89s |
| rate_limit | ok | 10 | 0 | 0.11s |
| migrations | ok | 17 | 0 | 13.97s |
| smoke | ok | 234 | 0 | 16.37s |
| browser | ok | 50 | 0 | 47.70s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                738     84    89%
config.py             113      0   100%
content_loader.py     159      5    97%
content_schema.py     154      7    95%
game_engine.py        616     44    93%
logging_setup.py       64      7    89%
models.py              83      0   100%
rate_limit.py          56      3    95%
seed_db.py              8      8     0%
---------------------------------------
TOTAL                1991    158    92%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:627:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 1145 | 53656 |
| backend\config.py | 242 | 11534 |
| backend\content_loader.py | 230 | 9809 |
| backend\content_schema.py | 352 | 11414 |
| backend\game_engine.py | 1061 | 49840 |
| backend\gunicorn.conf.py | 35 | 1581 |
| backend\logging_setup.py | 126 | 5604 |
| backend\models.py | 155 | 6840 |
| backend\rate_limit.py | 82 | 2893 |
| backend\seed_db.py | 24 | 890 |
| backend\test_browser_e2e.py | 653 | 32375 |
| backend\test_config.py | 398 | 26053 |
| backend\test_content.py | 313 | 16392 |
| backend\test_game_engine.py | 1594 | 85690 |
| backend\test_integration_smoke.py | 1630 | 94032 |
| backend\test_migrations.py | 238 | 11422 |
| backend\test_postgres.py | 240 | 10888 |
| backend\test_rate_limit.py | 86 | 2912 |
| frontend\app.js | 704 | 28317 |
| frontend\index.html | 117 | 5669 |
| frontend\style.css | 134 | 8506 |
| **total** | **9559** | **476317** |

Frontend first-load (html+css+js): 41.5 KB own code + 43.2 KB vendored libraries = 84.7 KB, all from our own server
New interface (web/dist, /next/): 3 files, 257.6 KB, 79.8 KB gzip

## Assets (backend/photos)
26 files, 130 KB total
extension != real format: 0
skill icons > 256px (rendered at 32px): 0, 0 KB

## Roster / content integrity
5 characters, 20 skills
content files: 5 characters in backend/content/ (loaded + validated: 5)
images referenced but missing: 0 
images on disk but unreferenced: 0 
descriptions with hardcoded cost text: 20
update-state payload (sample 3v3): 11810 bytes
update-state payload actually sent per player (view_for): 8636 bytes

