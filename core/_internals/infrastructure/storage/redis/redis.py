from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ConnectionError
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from asyncio import Semaphore


class ThrottyRedis:
    def __init__(
        self,
        redis: Optional[Redis] = None,
        pool: Optional[ConnectionPool] = None,
        dsn: Optional[str] = None,
        max_connections: int = 10,
    ):
        self._owns_connection = False
        self._semaphore: Semaphore = Semaphore(value=max_connections)

        if redis:
            self._redis = redis
            self._pool = redis.connection_pool
        elif pool:
            self._redis = Redis.from_pool(connection_pool=pool)
            self._pool = pool
        elif dsn:
            self._pool = ConnectionPool.from_url(
                url=dsn,
                max_connections=max_connections,
                socket_connect_timeout=5,
                socker_keepalive=True,
                health_check_interval=30,
            )
            self._redis = Redis.from_pool(self._pool)
            self._owns_connection = True

    @property
    def redis(self) -> Redis:
        return self._redis

    @asynccontextmanager
    async def get_redis(self) -> AsyncGenerator[Redis, None]:
        async with self._semaphore:
            try:
                yield self._redis
            except ConnectionError as e:
                raise ConnectionError from e
            finally:
                pass

    async def close_redis(self):
        if self._owns_connection and self._redis and self._pool:
            await self._redis.close()
            await self._pool.disconnect()
