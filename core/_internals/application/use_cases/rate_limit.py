from datetime import timedelta
from typing import Optional

from ...domain.interfaces.storage import StorageInterface
from ...domain.interfaces.rate_limit import RateLimitAlgorithm
from ...domain.services.algorithm import (
    SlidingWindowCounter,
    SlidingWindowLog,
    TokenBucket,
)
from ...domain.models.rate_limit_result import RateLimitResult


class CheckRateLimitUC:
    def __init__(
        self, storage: StorageInterface, algo: Optional[str] = "slidingwindow_counter"
    ):
        alghs = {
            "slidingwindow_counter": SlidingWindowCounter(storage=storage),
            "slidingwindow_log": SlidingWindowLog(storage=storage),
            "token_bucket": TokenBucket(storage=storage),
        }
        if algo not in alghs:
            raise ValueError(
                f"Algorithm not yet supported. Please choose between one of these {list(alghs.keys())}"
            )
        self.flow: RateLimitAlgorithm = alghs[algo]

    async def execute(self, key: str, limit: int, window: timedelta) -> RateLimitResult:
        return await self.flow.is_allowed(key=key, limit=limit, window=window)
