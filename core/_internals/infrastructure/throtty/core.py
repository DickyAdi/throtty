from redis.asyncio import Redis, ConnectionPool
from typing import Optional, Literal

from ...._internals.infrastructure.storage.redis import ThrottyRedis
from ...._internals.infrastructure.storage.in_mem import InMemStorage
from ...._internals.domain.enums import StorageType
from ...._internals.application.use_cases.rate_limit import CheckRateLimitUC
from ...._internals.domain.exceptions.exception import (
    RedisError,
)


class ThrottyCore:
    _storage: StorageType = None
    _storage_instance = None

    def __init__(
        self,
        redis: Optional[Redis] = None,
        redis_pool: Optional[ConnectionPool] = None,
        redis_dsn: Optional[str] = None,
        max_connections: Optional[int] = 10,
        algorithm: Optional[
            Literal["slidingwindow_counter", "slidingwindow_log", "token_bucket"]
        ] = "slidingwindow_counter",
    ):
        if redis and redis_dsn and redis_pool:
            raise RedisError(
                message="Cannot initiate internal redis if external redis is also provided. Choose only 1 between dsn, pool, or redis"
            )
        if redis_dsn:
            self._storage = StorageType.redis
            self._storage_instance = ThrottyRedis(
                dsn=redis_dsn, max_connections=max_connections
            )
        if redis:
            if not isinstance(redis, Redis):
                raise TypeError(f"Expected type of {type(Redis)}. Got {type(redis)}")
            self._storage = StorageType.redis
            self._storage_instance = ThrottyRedis(
                redis=redis, max_connections=max_connections
            )
        if redis_pool:
            if not isinstance(redis_pool, ConnectionPool):
                raise TypeError(
                    f"Expected type of {type(ConnectionPool)}. Got {type(redis_pool)}"
                )
            self._storage = StorageType.redis
            self._storage_instance = ThrottyRedis(
                pool=redis_pool, max_connections=max_connections
            )
        if not self._storage and not self._storage_instance:
            self._storage = StorageType.in_mem
            self._storage_instance = InMemStorage()
        self.flow = CheckRateLimitUC(storage=self._storage_instance, algo=algorithm)

    async def execute(self, key: str, limit: int, window: int):
        return await self.flow.execute(key=key, limit=limit, window=window)

    async def close(self) -> None:
        if self._storage == StorageType.redis:
            await self._storage_instance.close_redis()
