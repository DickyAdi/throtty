from datetime import timedelta
from time import time


from ....domain.interfaces.storage import StorageInterface
from ....domain.interfaces.rate_limit import RateLimitAlgorithm
from ....domain.models import RateLimitResult


class SlidingWindowLog(RateLimitAlgorithm):
    def __init__(self, storage: StorageInterface):
        self._storage = storage

    async def is_allowed(
        self, key: str, limit: int, window: timedelta
    ) -> RateLimitResult:
        now = time()
        window_seconds = window.total_seconds()
        curr_window = int(now / window_seconds)
        window_start = now - window_seconds

        await self._storage.remove_before(key=key, timestamp=window_start)

        await self._storage.add_timestamp(
            key=key, timestamp=now, ttl=int(window_seconds)
        )
        count = await self._storage.count_in_range(key=key, start=window_start, end=now)

        allowed = count < limit
        remaining_token = max(0, limit - count)
        reset_at = (curr_window + 1) * window_seconds
        retr_after = int(reset_at - now)

        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining_token,
            reset_at=reset_at,
            retry_after=retr_after,
        )
