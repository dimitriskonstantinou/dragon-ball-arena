# Step 44: sign-up/login bursts on Render's free size (simulated in Docker, 2026-11-27)

App 0.1 CPU / 512 MB (production image, gunicorn + gevent, staging settings), PostgreSQL 16 0.1 CPU / 256 MB. 20 bots play
(10-30 s per action, `tools/loadtest.py`) for 240 s; from second ~85: 100 sign-ups, then 100 logins, 32 at a time. One run each.

| | Before (66d8a5c) | Connection released only | After (connection released + hashing beside the loop) |
|---|---|---|---|
| Sign-ups 201 / 500 | 91 / 9 | 82 / 18 | **100 / 0** |
| Logins 200 / 401 / 500 (401 = its sign-up had failed) | 89 / 9 / 2 | 77 / 17 / 6 | **100 / 0 / 0** |
| Sign-up wait p50 / max | 29.4 / 48.2 s | 23.8 / 47.5 s | 42.7 / 50.2 s |
| Login wait p50 / max | 27.0 / 46.0 s | 35.7 / 59.5 s | 37.5 / 46.2 s |
| Players: turns in 240 s | 48 | 53 | **114** |
| Players: move answered p50 / p95 / p99 / max | 2,404 / 8,451 / 13,099 / 13,099 ms | 463 / 7,055 / 10,264 / 12,636 ms | **183 / 766 / 1,004 / 1,188 ms** |
| Players dropped / lost replies | 16 / 1 | 19 / 0 | **0 / 0** |
| Server log: ERROR / pool timeouts | 22 / 11 | 49 / 25 | **0 / 0** |

Why: the hashing (scrypt, ~0.7 s on 0.1 CPU) ran in the single gevent loop, which then serves nobody else; requests that held a
database connection meanwhile timed out the pool. In the production container (full CPU), 12 sign-ups at once: health check
answered after up to 1,446 ms before, less than one sign-up (245 ms) after. Not measured: the live site (no burst sent to it).
