from datetime import timedelta
from time import time


from ....domain.interfaces.storage import StorageInterface
from ....domain.interfaces.rate_limit import RateLimitAlgorithm
from ....domain.models import RateLimitResult


class SlidingWindowCounter(RateLimitAlgorithm):
    def __init__(self, storage: StorageInterface):
        self._storage = storage

    async def is_allowed(
        self, key: str, limit: int, window: timedelta
    ) -> RateLimitResult:
        now = time()
        window_seconds = int(window.total_seconds())

        curr_window = int(now / window_seconds)
        prev_window = curr_window - 1

        data = await self._storage.get_window_counts(
            key=key, current_window=curr_window, previous_window=prev_window
        )

        curr_count = await self._storage.increment_windows(
            key=key, window=curr_window, ttl=window_seconds * 2
        )
        elapsed = now - (curr_window * window_seconds)
        weight = elapsed / window_seconds

        est_count = (data.previous_count * (1 - weight)) + curr_count

        remaining_token = max(0, limit - est_count)
        reset_at = (curr_window + 1) * window_seconds
        retry_after = int(reset_at - now)
        allowed = est_count <= limit

        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining_token,
            reset_at=reset_at,
            retry_after=retry_after,
        )
