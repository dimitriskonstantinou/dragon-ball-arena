# Measurement - 2026-11-27 20:51
git: 6e535e4 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 229 | 0 | 0.24s |
| content | ok | 59 | 0 | 0.39s |
| config | ok | 110 | 0 | 12.46s |
| rate_limit | ok | 10 | 0 | 0.07s |
| migrations | ok | 17 | 0 | 7.00s |
| smoke | ok | 226 | 0 | 11.40s |
| browser | ok | 46 | 0 | 45.55s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                722     84    88%
config.py             113      0   100%
content_loader.py     159      5    97%
content_schema.py     154      7    95%
game_engine.py        616     44    93%
logging_setup.py       64      7    89%
models.py              83      0   100%
rate_limit.py          56      3    95%
seed_db.py              8      8     0%
---------------------------------------
TOTAL                1975    158    92%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:592:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 1124 | 52590 |
| backend\config.py | 242 | 11534 |
| backend\content_loader.py | 230 | 9809 |
| backend\content_schema.py | 352 | 11414 |
| backend\game_engine.py | 1061 | 49840 |
| backend\gunicorn.conf.py | 35 | 1581 |
| backend\logging_setup.py | 126 | 5604 |
| backend\models.py | 155 | 6840 |
| backend\rate_limit.py | 82 | 2893 |
| backend\seed_db.py | 24 | 890 |
| backend\test_browser_e2e.py | 632 | 30968 |
| backend\test_config.py | 398 | 26053 |
| backend\test_content.py | 313 | 16392 |
| backend\test_game_engine.py | 1594 | 85690 |
| backend\test_integration_smoke.py | 1595 | 91469 |
| backend\test_migrations.py | 238 | 11422 |
| backend\test_postgres.py | 240 | 10888 |
| backend\test_rate_limit.py | 86 | 2912 |
| frontend\app.js | 704 | 28317 |
| frontend\index.html | 117 | 5669 |
| frontend\style.css | 134 | 8506 |
| **total** | **9482** | **471281** |

Frontend first-load (html+css+js): 41.5 KB own code + 43.2 KB vendored libraries = 84.7 KB, all from our own server

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
update-state payload (sample 3v3): 11811 bytes
update-state payload actually sent per player (view_for): 8637 bytes

