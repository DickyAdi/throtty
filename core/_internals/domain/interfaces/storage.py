from abc import ABC, abstractmethod
from typing import Optional

from ..models import WindowData, BucketState


class StorageInterface(ABC):
    @abstractmethod
    async def increment_windows(self, key: str, window: int, ttl: int) -> int:
        pass

    @abstractmethod
    async def get_window_counts(
        self, key: str, current_window: int, previous_window: int
    ) -> WindowData:
        pass

    @abstractmethod
    async def add_timestamp(self, key: str, timestamp: float, ttl: int) -> None:
        pass

    @abstractmethod
    async def count_in_range(self, key: str, start: float, end: float) -> int:
        pass

    @abstractmethod
    async def remove_before(self, key: str, timestamp: float) -> None:
        pass

    @abstractmethod
    async def get_bucket_state(self, key: str) -> Optional[BucketState]:
        pass

    @abstractmethod
    async def update_bucket_state(self, key: str, state: BucketState, ttl: int) -> None:
        pass
