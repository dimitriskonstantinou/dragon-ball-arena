# Load test -- 2026-11-24 00:24 -- git 114108b

Server: production image (gunicorn + gevent, 1 worker), production settings, PostgreSQL 16, JSON logs; limited to **1 CPU / 1g RAM**. Bots: tools/loadtest.py in a separate container, waiting 10-30 s before each turn. 180 s measured per level after a 90 s ramp. Generator CPU near 100% (one process) would mean the latencies measure the bots, not the server.

Registration burst: 4000 accounts in 343.7 s = **11.6/s** (0 failures) -- password hashing is deliberately slow.

| Bots | Connected (start / end) | Turns/s | Commit p50 / p95 / p99 / max (ms) | Queue p95 | CPU avg / max | RAM start -> end (max) MB | Server errors seen by bots | Lost acks | Unanswered commits | Drops | Generator CPU | Matches started / ended |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2000 | 2000 / 2000 | 48.4 | 3.2 / 7.6 / 82.4 / 358.4 | 8.0 | 29% / 55% | 300.7 -> 301.9 (315.0) | 0 | 0 | 0 | 0 | 10% | 0 / 0 |
| 4000 | 4000 / 4000 | 96.1 | 3.9 / 46.6 / 774.7 / 1543.1 | 135.4 | 51% / 95% | 515.5 -> 529.8 (529.8) | 0 | 0 | 0 | 0 | 21% | 0 / 0 |

Refused actions (rule refusals, expected occasionally): {'Piccolo (Saiyan Saga) is stunned and cannot act!': 98, 'Raditz (Saiyan Saga) is stunned and cannot act!': 78, 'Tien (Saiyan Saga) is stunned and cannot act!': 95, 'Yamcha (Saiyan Saga) is stunned and cannot act!': 102, 'Goku (Saiyan Saga) is stunned and cannot act!': 83}
Server log: 68999 lines, 0 at ERROR level.

Note: measured on the uncommitted Step 37 working tree (114108b + `worker_connections = 5000`).
This is the repeated run with fixed bots; the bots' first version stopped playing after re-joining old matches.
