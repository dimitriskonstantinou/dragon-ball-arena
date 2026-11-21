"""
In-memory sliding-window rate limiter (SEC-3): "at most N events per key in
the last W seconds". Thread-safe (Socket.IO/HTTP requests run in parallel
threads) and bounded in memory: each key keeps at most N timestamps, and keys
with no event inside the window are swept away, so many distinct keys (e.g.
an attacker rotating IPs) can't grow it without limit.

Single-process by design, like the rest of the live state; it moves to Redis
together with GAMES when the server is scaled out (DEPLOY_PLAN Stage 10).
"""
import threading
import time
from collections import deque


class SlidingWindowLimiter:
    SWEEP_EVERY = 1000  # hits between sweeps of idle keys

    def __init__(self, max_events, window_seconds, clock=time.time):
        self.max_events = max_events
        self.window = window_seconds
        self.clock = clock
        self._events = {}
        self._lock = threading.Lock()
        self._hits_since_sweep = 0

    def _recent(self, key, now):
        events = self._events.get(key)
        if events is None:
            return None
        while events and events[0] <= now - self.window:
            events.popleft()
        if not events:
            del self._events[key]
            return None
        return events

    def retry_after(self, key):
        """0 if `key` may act now, else whole seconds until it may again."""
        with self._lock:
            now = self.clock()
            events = self._recent(key, now)
            if events is None or len(events) < self.max_events:
                return 0
            return max(1, int(events[0] + self.window - now + 0.999))

    def hit(self, key):
        """Records one event for `key`."""
        with self._lock:
            now = self.clock()
            events = self._recent(key, now)
            if events is None:
                events = self._events[key] = deque(maxlen=self.max_events)
            events.append(now)
            self._hits_since_sweep += 1
            if self._hits_since_sweep >= self.SWEEP_EVERY:
                self._hits_since_sweep = 0
                for k in list(self._events):
                    self._recent(k, now)

    def tracked_keys(self):
        with self._lock:
            return len(self._events)
