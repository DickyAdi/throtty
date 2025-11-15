# ruff: noqa

import pytest
from unittest.mock import MagicMock

from core._internals.infrastructure.throtty.core import ThrottyCore
from core._internals.domain.exceptions import RedisError
from core._internals.domain.enums import StorageType
import core._internals.infrastructure.throtty.core as throtty_core_mod


class MockThrottyRedis:
    def __init__(self, *, redis=None, pool=None, dsn=None, max_connections=10):
        self.init_args = dict(
            redis=redis, pool=pool, dsn=dsn, max_connections=max_connections
        )
        self.is_closed = False

    async def close_redis(self):
        self.is_closed()


class MockInMem:
    def __init__(self):
        self.initialized = False


class MockRedis:
    def __init__(self, *args, **kwargs):
        self.init = False
        self.connection_pool = "Mock"


def test_core_default_inmem_init(monkeypatch):
    monkeypatch.setattr(
        throtty_core_mod,
        "InMemStorage",
        MockInMem,
    )
    core = ThrottyCore()

    assert core._storage == StorageType.in_mem
    print(f"[DEBUG] {type(core._storage_instance)}")
    assert isinstance(core._storage_instance, MockInMem)
    assert hasattr(core, "flow")


def test_core_redis_instance_init(monkeypatch):
    monkeypatch.setattr(throtty_core_mod, "ThrottyRedis", MockThrottyRedis)
    monkeypatch.setattr(throtty_core_mod, "Redis", MockRedis)
    mock_redis = MockRedis()
    core = ThrottyCore(redis=mock_redis)

    assert core._storage == StorageType.redis
    assert isinstance(core._storage_instance, MockThrottyRedis)
    assert hasattr(core, "flow")


def test_core_redis_dsn_init(monkeypatch):
    monkeypatch.setattr(throtty_core_mod, "ThrottyRedis", MockThrottyRedis)
    mock_dsn = "redis://localhost:6379"
    core = ThrottyCore(redis_dsn=mock_dsn)

    assert core._storage == StorageType.redis
    assert isinstance(core._storage_instance, MockThrottyRedis)
    assert hasattr(core, "flow")


def test_core_redis_pool_init(monkeypatch):
    monkeypatch.setattr(throtty_core_mod, "ThrottyRedis", MockThrottyRedis)
    monkeypatch.setattr(throtty_core_mod, "ConnectionPool", MockRedis)

    mock_pool = MockRedis()
    core = ThrottyCore(redis_pool=mock_pool)

    assert core._storage == StorageType.redis
    assert isinstance(core._storage_instance, MockThrottyRedis)
    assert hasattr(core, "flow")


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
