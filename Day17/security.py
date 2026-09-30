import secrets
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from config import settings


_requests_by_client: dict[str, deque[float]] = defaultdict(deque)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    # Original app had no authentication. In production, set APP_API_KEY to require this header.
    if settings.app_api_key and not secrets.compare_digest(x_api_key or "", settings.app_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


def rate_limit(request: Request) -> None:
    # Original app allowed unlimited paid OpenAI calls. This adds a simple per-process guard.
    now = time.time()
    client = request.client.host if request.client else "unknown"
    window = _requests_by_client[client]

    while window and now - window[0] > 60:
        window.popleft()

    if len(window) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    window.append(now)
