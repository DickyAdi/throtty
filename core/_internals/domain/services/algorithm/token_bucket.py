from datetime import timedelta
from time import time

from ....domain.interfaces.storage import StorageInterface
from ....domain.models.bucket import BucketState
from ....domain.interfaces.rate_limit import RateLimitAlgorithm
from ....domain.models import RateLimitResult


class TokenBucket(RateLimitAlgorithm):
    def __init__(self, storage: StorageInterface):
        self._storage = storage

    async def is_allowed(
        self, key: str, limit: int, window: timedelta
    ) -> RateLimitResult:
        now = time()
        window_seconds = window.total_seconds()
        refill_rate = limit / window_seconds

        state = await self._storage.get_bucket_state(key=key)
        if not state:
            state = BucketState(tokens=float(limit), latest_refill=now)
        elapsed = now - state.latest_refill
        tokens_to_add = elapsed * refill_rate

        state.tokens = min(limit, state.tokens + tokens_to_add)
        state.latest_refill = now

        if state.tokens >= 1.0:
            state.tokens -= 1.0
            allowed = True
        else:
            allowed = False

        remaining_token = state.tokens
        await self._storage.update_bucket_state(
            key=key, state=state, ttl=int(window_seconds * 2)
        )

        if not allowed:
            tokens_needed = 1.0 - state.tokens
            retry_after = max(1, int(tokens_needed / refill_rate))
        else:
            retry_after = 0

        reset_at = now + (limit - state.tokens) / refill_rate

        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining_token,
            reset_at=reset_at,
            retry_after=retry_after,
        )
