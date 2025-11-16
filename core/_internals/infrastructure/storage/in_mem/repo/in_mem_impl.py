from collections import defaultdict
from sortedcontainers import SortedList
import asyncio
from typing import Optional

from .....domain.interfaces.storage import StorageInterface
from .....domain.models import BucketState, WindowData


class InMemStorage(StorageInterface):
    def __init__(self):
        self._windows: dict[str, int] = {}
        self._timestamps: dict[str, SortedList] = defaultdict(SortedList)
        self._buckets: dict[str, BucketState] = {}
        self._lock = asyncio.Lock()

    async def increment_windows(self, key: str, window: int, ttl: int) -> int:
        async with self._lock:
            window_key = f"{key}:{window}"
            self._windows[window_key] = self._windows.get(window_key, 0) + 1
            return self._windows[window_key]

    async def get_window_counts(
        self, key: str, current_window: int, previous_window: int
    ) -> WindowData:
        async with self._lock:
            curr_key = f"{key}:{current_window}"
            prev_key = f"{key}:{previous_window}"
            return WindowData(
                current_count=self._windows.get(curr_key, 0),
                previous_count=self._windows.get(prev_key, 0),
                current_window=current_window,
            )

    async def add_timestamp(self, key: str, timestamp: float, ttl: int) -> None:
        async with self._lock:
            self._timestamps[key].add(timestamp)

    async def count_in_range(self, key: str, start: float, end: float) -> int:
        async with self._lock:
            timestamps = self._timestamps.get(key, SortedList())
            start_idx = timestamps.bisect_left(start)
            end_idx = timestamps.bisect_right(end)
            return end_idx - start_idx

    async def remove_before(self, key: str, timestamp: float) -> None:
        async with self._lock:
            if key in self._timestamps:
                timestamps = self._timestamps[key]
                idx = timestamps.bisect_left(timestamp)
                del timestamps[:idx]

    async def get_bucket_state(self, key: str) -> Optional[BucketState]:
        async with self._lock:
            return self._buckets.get(key)

    async def update_bucket_state(self, key: str, state: BucketState, ttl: int) -> None:
        async with self._lock:
            self._buckets[key] = state
