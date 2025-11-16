# ruff: noqa

import pytest
from unittest.mock import MagicMock

from core._internals.infrastructure.throtty.core import ThrottyCore
from core._internals.domain.exceptions import RedisError
from core._internals.domain.enums import StorageType
from core._internals.domain.models.rate_limit_result import RateLimitResult
import core._internals.infrastructure.throtty.core as throtty_core_mod


class MockThrottyRedis:
    def __init__(self, *, redis=None, pool=None, dsn=None, max_connections=10):
        self.init_args = dict(
            redis=redis, pool=pool, dsn=dsn, max_connections=max_connections
        )
        self.is_closed = False

    async def close_redis(self):
        self.is_closed = True


class MockUCTrue:
    def __init__(self, storage, algo):
        self.input_args = dict(storage=storage, algo=algo)

    async def execute(self, key, limit, window):
        self.execute_args = dict(key=key, limit=limit, window=window)
        return RateLimitResult(
            allowed=True, limit=limit, remaining=float(10), reset_at=float(10)
        )


class MockInMem:
    def __init__(self):
        self.initialized = False
        self._should_not_close = True

    async def close_redis(self):
        self._should_not_close = False


class MockRedis:
    def __init__(self, *args, **kwargs):
        self.init = False
        self.connection_pool = "Mock"


mock_key = "ip:127.0.0.1"
mock_limit = 10
mock_window = 60


@pytest.mark.asyncio
async def test_core_default_inmem_init(monkeypatch):
    monkeypatch.setattr(
        throtty_core_mod,
        "InMemStorage",
        MockInMem,
    )
    monkeypatch.setattr(throtty_core_mod, "CheckRateLimitUC", MockUCTrue)

    core = ThrottyCore()
    await core.close()
    res = await core.execute(key=mock_key, limit=mock_limit, window=mock_window)

    assert core._storage == StorageType.in_mem
    assert isinstance(core._storage_instance, MockInMem)
    assert hasattr(core, "flow")
    assert core._storage_instance._should_not_close == True
    assert isinstance(core.flow, MockUCTrue)
    assert core.flow.input_args.get("algo") == "slidingwindow_counter"
    assert isinstance(core.flow.input_args.get("storage"), MockInMem)
    assert res is not None
    assert res.allowed == True
    assert res.limit == mock_limit


@pytest.mark.asyncio
async def test_core_redis_instance_init(monkeypatch):
    monkeypatch.setattr(throtty_core_mod, "ThrottyRedis", MockThrottyRedis)
    monkeypatch.setattr(throtty_core_mod, "Redis", MockRedis)
    monkeypatch.setattr(throtty_core_mod, "CheckRateLimitUC", MockUCTrue)

    mock_redis = MockRedis()
    core = ThrottyCore(redis=mock_redis)
    await core.close()
    res = await core.execute(key=mock_key, limit=mock_limit, window=mock_window)

    assert core._storage == StorageType.redis
    assert isinstance(core._storage_instance, MockThrottyRedis)
    assert hasattr(core, "flow")
    assert core._storage_instance.is_closed == True
    assert isinstance(core.flow, MockUCTrue)
    assert core.flow.input_args.get("algo") == "slidingwindow_counter"
    assert isinstance(core.flow.input_args.get("storage"), MockThrottyRedis)
    assert res is not None
    assert res.allowed == True
    assert res.limit == mock_limit


@pytest.mark.asyncio
async def test_core_redis_dsn_init(monkeypatch):
    monkeypatch.setattr(throtty_core_mod, "ThrottyRedis", MockThrottyRedis)
    monkeypatch.setattr(throtty_core_mod, "CheckRateLimitUC", MockUCTrue)

    mock_dsn = "redis://localhost:6379"
    core = ThrottyCore(redis_dsn=mock_dsn)
    await core.close()
    res = await core.execute(key=mock_key, limit=mock_limit, window=mock_window)

    assert core._storage == StorageType.redis
    assert isinstance(core._storage_instance, MockThrottyRedis)
    assert hasattr(core, "flow")
    assert core._storage_instance.is_closed == True
    assert isinstance(core.flow, MockUCTrue)
    assert core.flow.input_args.get("algo") == "slidingwindow_counter"
    assert isinstance(core.flow.input_args.get("storage"), MockThrottyRedis)
    assert res is not None
    assert res.allowed == True
    assert res.limit == mock_limit


@pytest.mark.asyncio
async def test_core_redis_pool_init(monkeypatch):
    monkeypatch.setattr(throtty_core_mod, "ThrottyRedis", MockThrottyRedis)
    monkeypatch.setattr(throtty_core_mod, "ConnectionPool", MockRedis)
    monkeypatch.setattr(throtty_core_mod, "CheckRateLimitUC", MockUCTrue)

    mock_pool = MockRedis()
    core = ThrottyCore(redis_pool=mock_pool)
    await core.close()
    res = await core.execute(key=mock_key, limit=mock_limit, window=mock_window)

    assert core._storage == StorageType.redis
    assert isinstance(core._storage_instance, MockThrottyRedis)
    assert hasattr(core, "flow")
    assert core._storage_instance.is_closed == True
    assert isinstance(core.flow, MockUCTrue)
    assert core.flow.input_args.get("algo") == "slidingwindow_counter"
    assert isinstance(core.flow.input_args.get("storage"), MockThrottyRedis)
    assert res is not None
    assert res.allowed == True
    assert res.limit == mock_limit


def test_core_init_all_types_redis(monkeypatch):
    monkeypatch.setattr(throtty_core_mod, "Redis", MockRedis)
    monkeypatch.setattr(throtty_core_mod, "ThrottyRedis", MockThrottyRedis)
    monkeypatch.setattr(throtty_core_mod, "ConnectionPool", MockRedis)

    mock_dsn = "redis://localhost:6379"
    mock_redis = MagicMock()
    mock_pool = MagicMock()

    with pytest.raises(RedisError):
        _core = ThrottyCore(redis=mock_redis, redis_pool=mock_pool, redis_dsn=mock_dsn)


def test_core_redis_client_wrong_type():
    mock_client = "not-a-client"

    with pytest.raises(TypeError):
        _core = ThrottyCore(redis=mock_client)


def test_core_redis_pool_wrong_type():
    mock_pool = "not-a-pool"

    with pytest.raises(TypeError):
        _core = ThrottyCore(redis_pool=mock_pool)


def test_core_redis_dsn_not_a_dsn():
    mock_dsn = "not-a-dsn"

    with pytest.raises(ValueError):
        _core = ThrottyCore(redis_dsn=mock_dsn)
