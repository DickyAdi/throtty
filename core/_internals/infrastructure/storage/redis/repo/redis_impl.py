from typing import Optional
import json

from .....domain.models import BucketState, WindowData
from .....domain.interfaces.storage import StorageInterface
from ..redis import ThrottyRedis


class RedisStorage(StorageInterface):
    def __init__(self, redis: ThrottyRedis):
        self.storage = redis

    async def increment_windows(self, key: str, window: int, ttl: int) -> int:
        window_key = f"{key}:{window}"
        async with self.storage.get_redis() as redis:
            async with redis.pipeline() as pipe:
                await pipe.incr(window_key)
                await pipe.expire(window_key, ttl)
                res = await pipe.execute()
        return res[0]

    async def get_window_counts(
        self, key: str, current_window: int, previous_window: int
    ) -> WindowData:
        curr_key = f"{key}:{current_window}"
        prev_key = f"{key}:{previous_window}"

        async with self.storage.get_redis() as redis:
            async with redis.pipeline() as pipe:
                await pipe.get(curr_key)
                await pipe.get(prev_key)
                res = await pipe.execute()

            return WindowData(
                current_count=int(res[0] or 0),
                previous_count=int(res[1] or 0),
                current_window=current_window,
            )

    async def add_timestamp(self, key: str, timestamp: float, ttl: int) -> None:
        async with self.storage.get_redis() as redis:
            async with redis.pipeline() as pipe:
                await pipe.zadd(key, {str(timestamp): timestamp})
                await pipe.expire(key, ttl)
                await pipe.execute()

    async def count_in_range(self, key: str, start: float, end: float) -> int:
        async with self.storage.get_redis() as redis:
            return await redis.zcount(key, start, end)

    async def remove_before(self, key: str, timestamp: float):
        async with self.storage.get_redis() as redis:
            await redis.zremrangebyscore(key, 0, timestamp)

    async def get_bucket_state(self, key: str) -> Optional[BucketState]:
        async with self.storage.get_redis() as redis:
            data = await redis.get(key)
            if not data:
                return None

            state_dict = json.loads(data)
            return BucketState(
                latest_refill=float(state_dict["latest_refill"]),
                tokens=float(state_dict["tokens"]),
            )

    async def update_bucket_state(self, key: str, state: BucketState, ttl: int) -> None:
        async with self.storage.get_redis() as redis:
            data = json.dumps(
                {"tokens": state.tokens, "latest_refill": state.latest_refill}
            )
            await redis.setex(key, ttl, data)
