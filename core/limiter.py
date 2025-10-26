from datetime import timedelta
from functools import wraps
from redis.asyncio import Redis, ConnectionPool
from typing import Optional

from _internals.infrastructure.storage.redis import ThrottyRedis
from _internals.infrastructure.storage.in_mem import InMemStorage
from _internals.domain.enums import StorageType
from _internals.application.use_cases.rate_limit import CheckRateLimitUC
from throtty.core._internals.domain.exceptions.exception import RedisError


class Throtty:
    _storage: StorageType = None
    _storage_instance = None

    def __init__(
        self,
        redis: Optional[Redis] = None,
        redis_pool: Optional[ConnectionPool] = None,
        redis_dsn: Optional[str] = None,
        max_connections: Optional[int] = 10,
        algorithm: Optional[str] = "slidingwindow_counter",
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
                raise ValueError(f"Expected type of {type(Redis)}. Got {type(redis)}")
            self._storage = StorageType.redis
            self._storage_instance = ThrottyRedis(
                redis=redis, max_connections=max_connections
            )
        if redis_pool:
            if not isinstance(redis_pool, ConnectionPool):
                raise ValueError(
                    f"Expected type of {type(ConnectionPool)}. Got {type(redis_pool)}"
                )
            self._storage = StorageType.redis
            self._storage_instance = ThrottyRedis(
                pool=redis_pool, max_connections=max_connections
            )
        if not redis and not redis_dsn and not redis_pool:
            self._storage = StorageType.in_mem
            self._storage_instance = InMemStorage()
        self.flow = CheckRateLimitUC(storage=self._storage_instance, algo=algorithm)

    async def limit(self, method):
        @wraps(method)
        async def wrapper(
            key: str, limit: int = 100, window: timedelta = timedelta(seconds=60)
        ):
            return await self.flow.execute(key=key, limit=limit, window=window)

        return wrapper
