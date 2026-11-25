# Live measurements of the DEV site -- 2026-11-24

Site: https://dragon-ball-arena-dev.onrender.com (Render free plan, Frankfurt, commit 15dee9d). Measured from the dev PC
with two throwaway accounts in headless Chromium, plus Render's log (sent by the user). Nothing was changed on the site.
Not measured: waking up from sleep (the site was awake), several real networks, more than two players.

## What works
HTTPS (http redirects), a full match saved to PostgreSQL (12 turns, 0 server errors, 0 drops), commit -> new state 61 / 67 ms
(p50 / p95), `/healthz` 0.12-0.14 s, login cookie flags, foreign origin refused, five probed paths 404, text files brotli.

## Leaving a match: when does the server notice? (seconds, 3 tries each)
| How the player leaves | Today | With a page goodbye (`pagehide` -> `socket.disconnect()`, injected) |
|---|---|---|
| reload | 10.07 / 10.07 / 10.08, back in the match: **0 of 3** | 10.07 / 10.08 / 10.07, back in the match: **0 of 3** |
| close the tab | 10.07 / 10.07 / 10.08 | **0.06 / 0.06 / 0.06** |
| go to another page | 10.07 / 10.07 / 10.07 | 10.07 / 10.07 / 10.07 |
| kill the browser | 10.07 / 10.07 / 10.07 | 10.07 / 10.07 / 10.07 |

Constant 10.07 s: a fixed wait somewhere before our server (it doesn't happen without Render in front).
Reload, staying on the page: connected again after 0.5 s, loses at 40.3 s. (The account's old connection counts as
connected for 10 s, so the new one isn't put back; then the old one's late goodbye starts the 30 s countdown.)
Network drop (the page's websocket closed, page stays open): reconnected after 1.8 s, every action answered "You are not in
a match.", loses at 40.7 s, the screen still showing the match.
Reproduced locally without any network: second connection of the account first, then the first one's disconnect.
A silently lost network is noticed by the ping (25 + 20 s, from the settings; not measured).

## Login limit
7 wrong logins with faked X-Forwarded-For: 7 x 401. 7 without: 401 401 429 401 401 401 401. 40 in a row: the first 14 and the 20th were 401, the other
25 were 429 -> about 3 different addresses are counted (3 x 5 = 15), then logins from everyone behind them are refused.
Render's log: accounts created with `ip=10.193.210.240` (an internal address), `Connected: ... ip=127.0.0.1`.
Unknown: at which position of X-Forwarded-For (or in which header) the real address is.

## Logs
Access log lines (`gunicorn.access`) although `accesslog = None`: reproduced with our image without any Render setting (4 lines for
4 requests), so it is our own setup: gunicorn also writes the access log when `logconfig_dict` is set. They contain full
connection ids of polling requests and one line per health check (every 5 s). `WEB_CONCURRENCY=4`: still 1 worker.
`GUNICORN_CMD_ARGS="--workers 4"` would override our 1 worker (nobody sets it today).
A refused foreign origin is logged at ERROR (engineio), a false alarm.

## Caching
Every file, images included, is `Cache-Control: no-cache`, `cf-cache-status: DYNAMIC`: re-checked with the 0.1-CPU server on
every page load. `photos/` is 2,037 KB (21 skill icons larger than 256 px, shown at 32 px: 1,840 KB; AST-1).

## Local state
`python tests.py --container`: ALL GREEN including PostgreSQL and the container (2026-11-24-step41-tests-container-before.md):
Windows allows psycopg again, so the baseline can be updated with the next step.

# After Step 41, live (commit 24c6f93, 2026-11-24 23:17)
Reload 10 of 10 back and able to play: 0.94 0.92 0.42 0.92 0.91 0.92 0.94 0.93 0.92 0.93 s; 12 s later the opponent had seen nothing.
Network drop (websocket closed) 10 of 10 able to play, reconnected after 1.05-1.94 s; 42 s later the opponent had seen nothing.
Second tab did not take the connected seat; when the first tab closed it had the match after 0.09 s.
Really leaving: opponent told after 0.1 s, match over after 31.0 s. No browser errors. Desktop Chromium only.
