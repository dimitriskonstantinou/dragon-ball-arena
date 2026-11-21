# Measurement - 2026-11-21 23:17
git: de4bcae (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 229 | 0 | 0.32s |
| content | ok | 53 | 0 | 0.54s |
| config | ok | 67 | 0 | 10.61s |
| rate_limit | ok | 10 | 0 | 0.09s |
| migrations | ok | 17 | 0 | 9.89s |
| smoke | ok | 163 | 0 | 9.22s |
| browser | ok | 39 | 0 | 37.86s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                612     75    88%
config.py             101      0   100%
content_loader.py     132      5    96%
content_schema.py     154      7    95%
game_engine.py        616     44    93%
logging_setup.py       51     12    76%
models.py              83      0   100%
rate_limit.py          44      0   100%
seed_db.py              8      8     0%
---------------------------------------
TOTAL                1801    151    92%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 949 | 43286 |
| backend\config.py | 216 | 9820 |
| backend\content_loader.py | 193 | 8264 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 1061 | 49832 |
| backend\gunicorn.conf.py | 31 | 1253 |
| backend\logging_setup.py | 104 | 4288 |
| backend\models.py | 155 | 6839 |
| backend\rate_limit.py | 63 | 2243 |
| backend\seed_db.py | 24 | 890 |
| backend\test_browser_e2e.py | 498 | 24921 |
| backend\test_config.py | 224 | 13396 |
| backend\test_content.py | 263 | 13158 |
| backend\test_game_engine.py | 1594 | 85690 |
| backend\test_integration_smoke.py | 1197 | 68780 |
| backend\test_migrations.py | 238 | 11422 |
| backend\test_postgres.py | 240 | 10888 |
| backend\test_rate_limit.py | 86 | 2912 |
| frontend\app.js | 690 | 27371 |
| frontend\index.html | 117 | 5669 |
| frontend\style.css | 134 | 8506 |
| **total** | **8429** | **410791** |

Frontend first-load (html+css+js): 40.6 KB own code + 43.2 KB vendored libraries = 83.7 KB, all from our own server

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
update-state payload (sample 3v3): 11781 bytes
update-state payload actually sent per player (view_for): 8607 bytes

