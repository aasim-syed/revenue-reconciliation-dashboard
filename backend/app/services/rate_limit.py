import time
from collections import defaultdict, deque

from fastapi import HTTPException

from .. import config

# In-memory sliding window per (ip, email). Fine for a single backend process;
# a multi-instance deployment would need a shared store (e.g. Redis) instead.
_attempts = defaultdict(deque)


def check_rate_limit(key):
    now = time.monotonic()
    attempts = _attempts[key]
    while attempts and now - attempts[0] > config.RATE_LIMIT_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= config.RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
    attempts.append(now)
