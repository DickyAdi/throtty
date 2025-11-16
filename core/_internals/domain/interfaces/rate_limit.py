from abc import ABC, abstractmethod
from datetime import timedelta

from ...domain.models import RateLimitResult


class RateLimitAlgorithm(ABC):
    @abstractmethod
    async def is_allowed(
        self, key: str, limit: int, window: timedelta
    ) -> RateLimitResult:
        pass
