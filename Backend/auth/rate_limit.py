import time
import threading
from typing import Dict, List


class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter for brute-force protection.
    Tracks timestamps of failed attempts within window_seconds.
    """
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._attempts: Dict[str, List[float]] = {}

    def is_rate_limited(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            timestamps = self._attempts.get(key, [])
            cutoff = now - self.window_seconds
            valid = [t for t in timestamps if t > cutoff]
            self._attempts[key] = valid
            return len(valid) >= self.max_attempts

    def record_failure(self, key: str):
        now = time.time()
        with self._lock:
            timestamps = self._attempts.get(key, [])
            cutoff = now - self.window_seconds
            valid = [t for t in timestamps if t > cutoff]
            valid.append(now)
            self._attempts[key] = valid

    def reset(self, key: str):
        with self._lock:
            if key in self._attempts:
                del self._attempts[key]

    def clear(self):
        with self._lock:
            self._attempts.clear()


# Default singleton instance: 5 attempts per 5 minutes
login_rate_limiter = SlidingWindowRateLimiter(max_attempts=5, window_seconds=300)
