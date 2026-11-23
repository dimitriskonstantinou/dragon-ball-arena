# Load test -- 2026-11-23 23:09 -- git 114108b

Server: production image (gunicorn + gevent, 1 worker), production settings, PostgreSQL 16, JSON logs; limited to **1 CPU / 1g RAM**. Bots: tools/loadtest.py in a separate container, waiting 2-4 s before each turn. 90 s measured per level after a 60 s ramp. Generator CPU near 100% (one process) would mean the latencies measure the bots, not the server.

Registration burst: 2000 accounts in 173.1 s = **11.6/s** (0 failures) -- password hashing is deliberately slow.

| Bots | Connected (start / end) | Turns/s | Commit p50 / p95 / p99 / max (ms) | Queue p95 | CPU avg / max | RAM start -> end (max) MB | Server errors | Lost acks | Unanswered commits | Drops | Generator CPU | Matches started / ended |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 500 | 500 / 500 | 65.0 | 3.6 / 9.5 / 33.1 / 163.8 | 9.0 | 38% / 58% | 145.8 -> 146.2 (146.7) | 0 | 0 | 0 | 0 | 13% | 270 / 274 |
| 1000 | 1000 / 1000 | 129.2 | 5.9 / 106.5 / 265.6 / 684.1 | 108.9 | 71% / 100% | 201.7 -> 203.3 (217.3) | 0 | 0 | 0 | 0 | 24% | 515 / 523 |
| 1500 | 1500 / 1500 | 184.3 | 40.0 / 352.7 / 499.1 / 1435.1 | 335.8 | 91% / 98% | 259.2 -> 261.6 (262.0) | 0 | 0 | 0 | 0 | 31% | 724 / 736 |
| 2000 | 2000 / 2000 | 188.8 | 137.2 / 705.1 / 1023.1 / 2634.5 | 750.2 | 94% / 103% | 316.6 -> 318.9 (331.8) | 0 | 0 | 0 | 0 | 31% | 702 / 703 |

Refused actions (rule refusals, expected occasionally): {'Piccolo (Saiyan Saga) is stunned and cannot act!': 188, 'Yamcha (Saiyan Saga) is stunned and cannot act!': 208, 'Raditz (Saiyan Saga) is stunned and cannot act!': 181, 'Tien (Saiyan Saga) is stunned and cannot act!': 181, 'Goku (Saiyan Saga) is stunned and cannot act!': 152}
Server log: 162173 lines, 11 at ERROR level.
    {"ts": "2026-11-23T21:07:01.690Z", "level": "ERROR", "logger": "app", "msg": "Unhandled error in find-match: user=494 room=769d4853 role=p2 sid=0VPbVs payload=['goku_saiyan_saga', 'piccolo_saiyan_saga', 'yamcha_saiyan_saga']", "exc": "Traceback (most recent call last):\n  File \"/app/backend/app.py\
    {"ts": "2026-11-23T21:07:03.417Z", "level": "ERROR", "logger": "app", "msg": "Unhandled error in find-match: user=892 room=2dc9e808 role=p2 sid=FA9Y_6 payload=['piccolo_saiyan_saga', 'goku_saiyan_saga', 'yamcha_saiyan_saga']", "exc": "Traceback (most recent call last):\n  File \"/app/backend/app.py\
    {"ts": "2026-11-23T21:09:54.441Z", "level": "ERROR", "logger": "app", "msg": "Unhandled error in find-match: user=1539 room=c1deaba8 role=p2 sid=gIIRxW payload=['goku_saiyan_saga', 'yamcha_saiyan_saga', 'raditz_saiyan_saga']", "exc": "Traceback (most recent call last):\n  File \"/app/backend/app.py\
    {"ts": "2026-11-23T21:09:54.445Z", "level": "ERROR", "logger": "app", "msg": "Unhandled error in find-match: user=1712 room=c1a93b29 role=p2 sid=_gfMsD payload=['goku_saiyan_saga', 'yamcha_saiyan_saga', 'tien_saiyan_saga']", "exc": "Traceback (most recent call last):\n  File \"/app/backend/app.py\",
    {"ts": "2026-11-23T21:09:54.480Z", "level": "ERROR", "logger": "app", "msg": "Unhandled error in find-match: user=1359 room=b7343bd1 role=p2 sid=Sz0PWl payload=['yamcha_saiyan_saga', 'piccolo_saiyan_saga', 'goku_saiyan_saga']", "exc": "Traceback (most recent call last):\n  File \"/app/backend/app.py

Note: measured on the uncommitted Step 37 working tree (114108b + `worker_connections = 5000`).
The 11 ERROR lines are BE-12 (`KeyError` in `join_room`, reproduced afterwards); the five shown came while bots disconnected in bulk. "Server errors" in the table counts only what bots saw.
