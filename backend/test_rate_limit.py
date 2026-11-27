"""
Tests for rate_limit.SlidingWindowLimiter (SEC-3). Run with: python test_rate_limit.py
Uses a fake clock, so no sleeping.
"""
import threading

from rate_limit import SlidingWindowLimiter

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_window():
    clock = Clock()
    lim = SlidingWindowLimiter(3, 60, clock=clock)
    for _ in range(3):
        check("allowed while under the limit", lim.retry_after('ip') == 0)
        lim.hit('ip')
        clock.t += 10
    wait = lim.retry_after('ip')
    check("refused once the limit is reached, with the wait until the oldest event leaves the window",
          wait == 30, wait)                       # first hit at 1000, now 1030, window 60 -> 30 s
    clock.t += 29
    check("still refused 1 s before that", lim.retry_after('ip') == 1, lim.retry_after('ip'))
    clock.t += 1
    check("allowed again exactly when the oldest event ages out (sliding, not fixed buckets)",
          lim.retry_after('ip') == 0, lim.retry_after('ip'))
    check("other keys (IPs) are independent", lim.retry_after('other') == 0)


def test_memory_is_bounded():
    clock = Clock()
    lim = SlidingWindowLimiter(5, 60, clock=clock)
    for _ in range(1000):
        lim.hit('busy')
    check("a key keeps at most max_events timestamps", len(lim._events['busy']) == 5, len(lim._events['busy']))
    for i in range(SlidingWindowLimiter.SWEEP_EVERY):
        lim.hit(f'ip{i}')                         # many different keys (e.g. rotating IPs)
    clock.t += 61
    lim.hit('late')                               # triggers no sweep yet...
    for i in range(SlidingWindowLimiter.SWEEP_EVERY):
        lim.hit('late2')                          # ...this crosses the sweep threshold
    check("keys with nothing left in the window are swept away", lim.tracked_keys() <= 2, lim.tracked_keys())


def test_thread_safety():
    lim = SlidingWindowLimiter(100_000, 60, clock=Clock())
    def worker():
        for _ in range(500):
            lim.hit('shared')
            lim.retry_after('shared')
    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("40 threads hitting one key at once record an exact count", len(lim._events['shared']) == 40 * 500,
          len(lim._events['shared']))


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_')]

if __name__ == '__main__':
    for t in TESTS:
        print(f"{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print(f"All {len(TESTS)} test functions passed.")
