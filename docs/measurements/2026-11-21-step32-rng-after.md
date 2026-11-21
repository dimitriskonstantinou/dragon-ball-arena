# Measurement - 2026-11-21 18:57
git: 628fb96 (uncommitted changes)

## Tests
| Suite | Result | PASS | FAIL | Time |
|---|---|---|---|---|
| engine | ok | 229 | 0 | 0.30s |
| content | ok | 53 | 0 | 0.41s |
| config | ok | 53 | 0 | 7.62s |
| rate_limit | ok | 10 | 0 | 0.07s |
| migrations | ok | 17 | 0 | 7.80s |
| smoke | ok | 158 | 0 | 8.45s |
| browser | ok | 39 | 0 | 36.32s |

## Coverage (backend, tests excluded)
```
Name                Stmts   Miss  Cover
---------------------------------------
app.py                531     63    88%
config.py              78      0   100%
content_loader.py     132      5    96%
content_schema.py     154      7    95%
game_engine.py        616     44    93%
models.py              83      0   100%
rate_limit.py          44      0   100%
seed_db.py              8      8     0%
---------------------------------------
TOTAL                1646    127    92%
```

## Lint (pyflakes)
2 issue(s)
    backend\test_integration_smoke.py:76:47: f-string is missing placeholders
    backend\test_integration_smoke.py:525:19: f-string is missing placeholders

## Code size
| File | Lines | Bytes |
|---|---|---|
| backend\app.py | 821 | 35613 |
| backend\config.py | 163 | 7336 |
| backend\content_loader.py | 193 | 8264 |
| backend\content_schema.py | 352 | 11363 |
| backend\game_engine.py | 1061 | 49832 |
| backend\models.py | 155 | 6839 |
| backend\rate_limit.py | 63 | 2243 |
| backend\seed_db.py | 24 | 890 |
| backend\test_browser_e2e.py | 479 | 23738 |
| backend\test_config.py | 186 | 10621 |
| backend\test_content.py | 263 | 13158 |
| backend\test_game_engine.py | 1594 | 85690 |
| backend\test_integration_smoke.py | 1129 | 64824 |
| backend\test_migrations.py | 238 | 11422 |
| backend\test_rate_limit.py | 86 | 2912 |
| frontend\app.js | 690 | 27371 |
| frontend\index.html | 117 | 5669 |
| frontend\style.css | 134 | 8506 |
| **total** | **7748** | **376291** |

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
update-state payload (sample 3v3): 11774 bytes
update-state payload actually sent per player (view_for): 8600 bytes

