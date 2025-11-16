# ruff: noqa

import pytest
from unittest.mock import MagicMock, AsyncMock
import json

from core.limiter import Throtty, ThrottyMiddleware, rule
from core._internals.domain.models.rate_limit_result import RateLimitResult
import core.limiter as throtty_mod


class MockThrottyCore:
    def __init__(self, *args, **kwargs):
        self.init_args = kwargs

    async def execute(self, key, limit, window):
        self.execute_args = dict(key=key, limit=limit, window=window)
        return RateLimitResult(
            allowed=True, limit=limit, remaining=float(5), reset_at=float(100)
        )


class MockThrottyCoreBlocked:
    def __init__(self, *args, **kwargs):
        self.init_args = kwargs

    async def execute(self, key, limit, window):
        return RateLimitResult(
            allowed=False,
            limit=10,
            remaining=float(0),
            reset_at=float(100),
            retry_after=60,
        )


class MockApp:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True


def test_throtty_singleton():
    """Test that Throtty follows singleton pattern"""
    throtty1 = Throtty()
    throtty2 = Throtty()

    assert throtty1 is throtty2
    assert Throtty._get_instance() is throtty1


def test_throtty_init(monkeypatch):
    """Test Throtty initialization"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    # Reset singleton for test
    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty(algorithm="token_bucket")

    assert isinstance(throtty.engine, MockThrottyCore)
    assert throtty.engine.init_args.get("algorithm") == "token_bucket"
    assert throtty.rules == []
    assert throtty.key_extractor is None


def test_add_rule_simple_path(monkeypatch):
    """Test adding a rule with simple path"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    throtty.add_rule("/api/users", limit=10, window=60)

    assert len(throtty.rules) == 1
    assert throtty.rules[0]["path"] == "/api/users"
    assert throtty.rules[0]["limit"] == 10
    assert throtty.rules[0]["pattern"].match("/api/users")
    assert not throtty.rules[0]["pattern"].match("/api/posts")


def test_add_rule_wildcard_path(monkeypatch):
    """Test adding a rule with wildcard path"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    throtty.add_rule("/api/*", limit=20, window=120)

    assert len(throtty.rules) == 1
    assert throtty.rules[0]["pattern"].match("/api/users")
    assert throtty.rules[0]["pattern"].match("/api/posts")
    assert not throtty.rules[0]["pattern"].match("/v2/users")


def test_add_rule_regex_path(monkeypatch):
    """Test adding a rule with regex path"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    throtty.add_rule("^/api/v[0-9]+/.*", limit=30, window=180)

    assert len(throtty.rules) == 1
    assert throtty.rules[0]["pattern"].match("/api/v1/users")
    assert throtty.rules[0]["pattern"].match("/api/v2/posts")
    assert not throtty.rules[0]["pattern"].match("/api/users")


def test_add_rule_with_key_func(monkeypatch):
    """Test adding a rule with custom key function"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    def custom_key(host, headers):
        return f"user:{headers.get('user-id', 'anonymous')}"

    throtty = Throtty()
    throtty.add_rule("/api/users", limit=10, window=60, key_func=custom_key)

    assert len(throtty.rules) == 1
    assert throtty.rules[0]["key_func"] == custom_key


def test_add_rule_not_initialized():
    """Test that adding rule fails if not initialized"""
    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty.__new__(Throtty)
    throtty._initialized = False

    with pytest.raises(ValueError):
        throtty.add_rule("/api/test", limit=10, window=60)


def test_rule_decorator(monkeypatch):
    """Test rule decorator"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()

    @throtty.rule("/api/login", "5/60;10/300", key_func=None)
    def login_handler():
        pass

    assert len(throtty.rules) == 2
    assert throtty.rules[0]["limit"] == 5
    assert throtty.rules[0]["window"].total_seconds() == 60
    assert throtty.rules[1]["limit"] == 10
    assert throtty.rules[1]["window"].total_seconds() == 300


def test_global_rule_decorator(monkeypatch):
    """Test global rule decorator"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()

    @rule("/api/test", "3/60")
    def test_handler():
        pass

    assert len(throtty.rules) == 1


def test_global_rule_not_initialized():
    """Test that global rule fails if Throtty not initialized"""
    Throtty._instance = None

    with pytest.raises(RuntimeError):

        @rule("/api/test", "3/60")
        def test_handler():
            pass


def test_find_match_rule(monkeypatch):
    """Test finding matching rule"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    throtty.add_rule("/api/users", limit=10, window=60)
    throtty.add_rule("/api/*", limit=20, window=120)

    rule = throtty._find_match_rule("/api/users")
    assert rule is not None
    assert rule["limit"] == 10

    rule = throtty._find_match_rule("/api/posts")
    assert rule is not None
    assert rule["limit"] == 20

    rule = throtty._find_match_rule("/v2/users")
    assert rule is None


def test_set_key_extractor(monkeypatch):
    """Test setting key extractor"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    def custom_extractor(host, headers):
        return f"custom:{host}"

    throtty = Throtty()
    throtty.set_key_extractor(custom_extractor)

    assert throtty.key_extractor == custom_extractor


@pytest.mark.asyncio
async def test_middleware_allowed_request(monkeypatch):
    """Test middleware with allowed request"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    throtty.add_rule("/api/users", limit=10, window=60)

    mock_app = MockApp()
    middleware = ThrottyMiddleware(mock_app, throtty)

    scope = {
        "type": "http",
        "path": "/api/users",
        "client": ("127.0.0.1", 8000),
        "headers": [(b"host", b"localhost")],
    }

    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    assert mock_app.called == True


@pytest.mark.asyncio
async def test_middleware_blocked_request(monkeypatch):
    """Test middleware with blocked request"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCoreBlocked)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    throtty.add_rule("/api/users", limit=10, window=60)

    mock_app = MockApp()
    middleware = ThrottyMiddleware(mock_app, throtty)

    scope = {
        "type": "http",
        "path": "/api/users",
        "client": ("127.0.0.1", 8000),
        "headers": [(b"host", b"localhost")],
    }

    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    assert mock_app.called == False
    assert send.call_count == 2

    # Check response
    start_call = send.call_args_list[0][0][0]
    assert start_call["status"] == 429
    assert any(b"X-RateLimit-Limit" in h for h in start_call["headers"])


@pytest.mark.asyncio
async def test_middleware_no_matching_rule(monkeypatch):
    """Test middleware with no matching rule"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    throtty.add_rule("/api/users", limit=10, window=60)

    mock_app = MockApp()
    middleware = ThrottyMiddleware(mock_app, throtty)

    scope = {
        "type": "http",
        "path": "/other/path",
        "client": ("127.0.0.1", 8000),
        "headers": [(b"host", b"localhost")],
    }

    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    assert mock_app.called == True


@pytest.mark.asyncio
async def test_middleware_non_http(monkeypatch):
    """Test middleware with non-HTTP request"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    throtty = Throtty()
    mock_app = MockApp()
    middleware = ThrottyMiddleware(mock_app, throtty)

    scope = {"type": "websocket"}
    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    assert mock_app.called == True


@pytest.mark.asyncio
async def test_middleware_custom_key_func(monkeypatch):
    """Test middleware with custom key function"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    def custom_key(host, headers):
        return f"user:{headers.get('user-id', 'anonymous')}"

    throtty = Throtty()
    throtty.add_rule("/api/users", limit=10, window=60, key_func=custom_key)

    mock_app = MockApp()
    middleware = ThrottyMiddleware(mock_app, throtty)

    scope = {
        "type": "http",
        "path": "/api/users",
        "client": ("127.0.0.1", 8000),
        "headers": [(b"user-id", b"12345")],
    }

    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    assert mock_app.called == True


@pytest.mark.asyncio
async def test_middleware_global_key_extractor(monkeypatch):
    """Test middleware with global key extractor"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    def global_extractor(host, headers):
        return f"global:{host}"

    throtty = Throtty()
    throtty.set_key_extractor(global_extractor)
    throtty.add_rule("/api/users", limit=10, window=60)

    mock_app = MockApp()
    middleware = ThrottyMiddleware(mock_app, throtty)

    scope = {
        "type": "http",
        "path": "/api/users",
        "client": ("127.0.0.1", 8000),
        "headers": [(b"host", b"localhost")],
    }

    receive = AsyncMock()
    send = AsyncMock()

    await middleware(scope, receive, send)

    assert mock_app.called == True


def test_install_with_middleware_support(monkeypatch):
    """Test installing middleware on supported app"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    class MockAppWithMiddleware:
        def __init__(self):
            self.middlewares = []

        def add_middleware(self, middleware_class, **kwargs):
            self.middlewares.append((middleware_class, kwargs))

    throtty = Throtty()
    app = MockAppWithMiddleware()
    throtty.install(app)

    assert len(app.middlewares) == 1
    assert app.middlewares[0][0] == ThrottyMiddleware


def test_install_without_middleware_support(monkeypatch):
    """Test installing middleware on unsupported app"""
    monkeypatch.setattr(throtty_mod, "ThrottyCore", MockThrottyCore)

    Throtty._instance = None
    Throtty._initialized = False

    class MockAppWithoutMiddleware:
        pass

    throtty = Throtty()
    app = MockAppWithoutMiddleware()

    with pytest.raises(NotImplementedError):
        throtty.install(app)
