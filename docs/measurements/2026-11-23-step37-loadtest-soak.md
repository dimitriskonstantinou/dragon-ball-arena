# Load test -- 2026-11-24 00:06 -- git 114108b

Server: production image (gunicorn + gevent, 1 worker), production settings, PostgreSQL 16, JSON logs; limited to **1 CPU / 1g RAM**. Bots: tools/loadtest.py in a separate container, waiting 2-4 s before each turn. 1800 s measured per level after a 30 s ramp. Generator CPU near 100% (one process) would mean the latencies measure the bots, not the server.

Registration burst: 500 accounts in 43.4 s = **11.5/s** (0 failures) -- password hashing is deliberately slow.

| Bots | Connected (start / end) | Turns/s | Commit p50 / p95 / p99 / max (ms) | Queue p95 | CPU avg / max | RAM start -> end (max) MB | Server errors | Lost acks | Unanswered commits | Drops | Generator CPU | Matches started / ended |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 500 | 500 / 500 | 65.2 | 3.2 / 8.3 / 27.6 / 243.6 | 7.8 | 35% / 63% | 145.5 -> 146.4 (160.7) | 0 | 0 | 0 | 0 | 12% | 5054 / 5058 |

RAM per minute (MB, average) at 500 bots: 145.9, 146.6, 146.8, 146.4, 146.4, 146.2, 146.4, 146.2, 146.2, 146.4, 146.5, 146.1, 146.4, 146.8, 146.5, 146.7, 146.5, 146.1, 146.6, 146.6, 146.5, 146.8, 146.9, 146.8, 146.6, 146.3, 146.7, 146.5, 146.4, 146.7

Refused actions (rule refusals, expected occasionally): {'Yamcha (Saiyan Saga) is stunned and cannot act!': 451, 'Tien (Saiyan Saga) is stunned and cannot act!': 418, 'Raditz (Saiyan Saga) is stunned and cannot act!': 417, 'Piccolo (Saiyan Saga) is stunned and cannot act!': 383, 'Goku (Saiyan Saga) is stunned and cannot act!': 340}
Server log: 144763 lines, 0 at ERROR level.

Note: measured on the uncommitted Step 37 working tree (114108b + `worker_connections = 5000`).
