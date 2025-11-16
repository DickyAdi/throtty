import re
from datetime import timedelta
from redis.asyncio import Redis, ConnectionPool
from typing import Optional, Callable, TypedDict, Union, Literal

from ._internals.infrastructure.throtty import ThrottyCore
from ._internals.domain.models.rate_limit_result import RateLimitResult
import json


class RateLimitRules(TypedDict):
    path: str
    pattern: re.Pattern
    limit: int
    window: int
    key_func: Optional[Callable[..., str]] = None


class ThrottyMiddleware:
    """ASGI middleware for rate limiting requests based on configured rules.

    This middleware intercepts incoming HTTP requests, checks if they match any rate limiting rules,
    and enforces the limits by either allowing the request to proceed or returning a 429 status code
    with rate limit information in the response headers.

    The middleware:
    - Matches incoming request paths against configured rate limit rules
    - Extracts client identifiers using custom key functions or defaults to client IP
    - Checks rate limits using the configured Throtty engine
    - Returns 429 responses when limits are exceeded with X-RateLimit-* headers
    - Passes through requests that don't match any rules or are within limits

    This class is automatically installed when calling `Throtty.install(app)` and should not
    be instantiated directly by users.

    Args:
        app: The ASGI application to wrap
        throtty (Throtty): The Throtty instance containing rate limit rules and configuration
    """

    def __init__(self, app, throtty: "Throtty"):
        self.app = app
        self.throtty = throtty

    async def __call__(self, scope, receive, send, *args, **kwargs):
        """Process incoming ASGI requests and enforce rate limiting.

        This method is called for each incoming request. It checks if the request is HTTP,
        finds matching rate limit rules, extracts the client key, checks the rate limit,
        and either allows the request or returns a 429 response.

        Args:
            scope: ASGI connection scope containing request information
            receive: ASGI receive callable for reading request body
            send: ASGI send callable for writing response
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        rule = self.throtty._find_match_rule(path)
        headers = self._decode_headers(scope["headers"])
        host = scope.get("client", "default")[0]
        if rule:
            if rule["key_func"]:
                key = rule["key_func"](host, headers)
            elif self.throtty.key_extractor:
                key = self.throtty.key_extractor(host, headers)
            else:
                key = f"ip:{host}"
            result = await self.throtty.engine.execute(
                key=key, limit=rule["limit"], window=rule["window"]
            )
            if not result.allowed:
                await self.send_json_response(
                    scope=scope,
                    receive=receive,
                    send=send,
                    status=429,
                    rate_limit_result=result,
                )
                return

        return await self.app(scope, receive, send)

    def _decode_headers(self, scope: list) -> dict:
        """Decode ASGI headers from bytes to strings.

        Args:
            scope (list): List of header tuples in bytes format from ASGI scope

        Returns:
            dict: Dictionary of decoded headers with string keys and values
        """
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in scope}

    async def send_json_response(
        self,
        scope,
        receive,
        send,
        status: int,
        rate_limit_result: RateLimitResult,
        content: Optional[str] = None,
        headers: Optional[dict] = None,
    ) -> None:
        """Send a JSON response with rate limit information.

        Constructs and sends an HTTP response with rate limit headers including:
        - X-RateLimit-Limit: Maximum number of requests allowed
        - X-RateLimit-Remaining: Number of requests remaining in current window
        - X-RateLimit-Reset-At: Timestamp when the rate limit resets
        - Retry-After: Seconds until the client can retry

        Args:
            scope: ASGI connection scope
            receive: ASGI receive callable
            send: ASGI send callable for writing response
            status (int): HTTP status code to return
            rate_limit_result (RateLimitResult): Rate limit execution result containing limit information
            content (Optional[str], optional): Custom response body content. Defaults to "Rate limit exceeded".
            headers (Optional[dict], optional): Additional headers to include in the response. Defaults to None.

        Returns:
            None
        """
        list_headers = [
            [b"content-type", b"application/json"],
            [b"X-RateLimit-Limit", str(rate_limit_result.limit).encode("utf-8")],
            [
                b"X-RateLimit-Remaining",
                str(rate_limit_result.remaining).encode("utf-8"),
            ],
            [b"X-RateLimit-Reset-At", str(rate_limit_result.reset_at).encode("utf-8")],
            [b"Retry-After", str(rate_limit_result.retry_after).encode("utf-8")],
        ]

        if headers:
            for key, val in headers.items():
                list_headers.append([key.lower().encode(), str(val).encode()])

        await send(
            {"type": "http.response.start", "status": status, "headers": list_headers}
        )

        content = "Rate limit exceeded" if not content else content
        body = json.dumps(content).encode("utf-8")
        await send({"type": "http.response.body", "body": body})


class Throtty:
    """Throtty application class to integrate rate limiting to ASGI applications such as FastAPI.

        Throtty is a singleton-based rate limiter that provides flexible rate limiting capabilities
        for ASGI applications. It supports multiple storage backends (in-memory or Redis), various
        rate limiting algorithms, and flexible rule configuration with regex pattern matching.

        Features:
        - Singleton pattern ensures single instance across application
        - In-memory storage by default, with optional Redis backend for distributed systems
        - Multiple rate limiting algorithms: sliding window counter, sliding window log, token bucket
        - Flexible path matching with regex support and wildcard patterns
        - Custom key extraction for fine-grained rate limiting (per user, API key, etc.)
        - Automatic middleware installation for seamless integration

        Storage Options:
        - In-memory: Default, suitable for single-server deployments
        - Redis: Recommended for distributed/multi-server deployments

        Usage:
    ```python
        from fastapi import FastAPI
        from throtty import Throtty, rule

        # Initialize with in-memory storage
        limiter = Throtty()

        # Or with Redis
        limiter = Throtty(redis_dsn="redis://localhost:6379")

        app = FastAPI()
        limiter.install(app)

        @app.get("/hello_world")
        @rule("/hello_world", "10/60;100/3600")
        async def hw():
            return {"message": "hey im not rate limited"}
    ```
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs) -> "Throtty":
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _get_instance(cls) -> "Throtty":
        """Get the singleton instance of Throtty.

        Returns:
            Throtty: The singleton Throtty instance, or None if not yet initialized
        """
        return cls._instance

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
        """Initialize the Throtty rate limiter as a singleton instance.

        By default, Throtty uses in-memory storage suitable for single-server deployments.
        For distributed systems or persistent rate limiting across restarts, configure Redis
        storage using one of three methods: Redis client instance, connection pool, or DSN string.

        Storage Priority (when multiple options provided):
        1. redis (Redis client instance)
        2. redis_pool (ConnectionPool instance)
        3. redis_dsn (connection string)

        Algorithm Options:
        - slidingwindow_counter: Efficient, slight inaccuracy at window boundaries (default)
        - slidingwindow_log: Most accurate, higher memory usage
        - token_bucket: Smooth rate limiting, allows bursts

        Args:
            redis (Optional[Redis], optional): Pre-configured Redis client instance from your
                application. Use this if you already have a Redis client initialized.
                Defaults to None.
            redis_pool (Optional[ConnectionPool], optional): Pre-configured Redis connection pool.
                Use this to share connection pools across your application. Defaults to None.
            redis_dsn (Optional[str], optional): Redis connection string in format
                "redis://[[username]:[password]]@host:port/database".
                Example: "redis://localhost:6379/0". Defaults to None.
            max_connections (Optional[int], optional): Maximum number of connections in the Redis
                connection pool. Only applies when using redis_dsn. Defaults to 10.
            algorithm (Optional[Literal], optional): Rate limiting algorithm to use. Choose based
                on your accuracy and performance requirements. Defaults to "slidingwindow_counter".

        Note:
            Due to singleton pattern, only the first initialization sets the configuration.
            Subsequent instantiations return the same instance with original configuration.

        Example:
        ```python
            # In-memory storage
            limiter = Throtty()

            # Redis with DSN
            limiter = Throtty(redis_dsn="redis://localhost:6379/0")

            # Redis with existing client
            from redis import Redis
            redis_client = Redis(host='localhost', port=6379, db=0)
            limiter = Throtty(redis=redis_client)

            # Custom algorithm
            limiter = Throtty(algorithm="token_bucket")
        ```
        """
        if not self._initialized:
            self.engine = ThrottyCore(
                redis=redis,
                redis_pool=redis_pool,
                redis_dsn=redis_dsn,
                max_connections=max_connections,
                algorithm=algorithm,
            )
            self.rules: list[RateLimitRules] = []
            self.key_extractor = None
            self._initialized = True

    def add_rule(
        self, path: str, limit: int, window: int, key_func: Optional[Callable] = None
    ):
        """Add a rate limiting rule for a specific endpoint path.

        Rules are matched against incoming request paths using regex patterns. The first matching
        rule is applied to each request. Ensure paths are specific enough to match intended endpoints.

        Path Matching Patterns:
        - Exact match: "/api/users" matches only "/api/users"
        - Wildcard: "/api/*" matches "/api/users", "/api/posts", etc.
        - Regex: "^/api/v[0-9]+/.*" matches "/api/v1/users", "/api/v2/posts", etc.

        Args:
            path (str): Endpoint path to rate limit. Supports three formats:
                - Exact string: Matches the exact path
                - Wildcard with *: Converts to regex (e.g., "/v1/*" → "^/v1/.*$")
                - Regex starting with ^: Used as-is for custom patterns
            limit (int): Maximum number of requests allowed within the time window.
                Must be a positive integer.
            window (int): Time window duration in seconds. Requests are counted within
                this rolling window. Common values: 60 (1 min), 3600 (1 hour), 86400 (1 day).
            key_func (Optional[Callable], optional): Custom function to extract unique identifiers
                from requests. Function signature: (host: str, headers: dict) -> str.
                If None, uses global key_extractor or defaults to client IP. Defaults to None.

        Raises:
            ValueError: If Throtty instance is not properly initialized before adding rules.

        Example:
        ```python
            limiter = Throtty()

            # Exact path match: 100 requests per minute
            limiter.add_rule("/api/users", limit=100, window=60)

            # Wildcard: all v1 endpoints share 1000 req/hour
            limiter.add_rule("/api/v1/*", limit=1000, window=3600)

            # Regex: version-specific limits
            limiter.add_rule("^/api/v[2-9]/.*", limit=2000, window=3600)

            # Custom key function: rate limit by API key instead of IP
            def extract_api_key(host, headers):
                return f"apikey:{headers.get('x-api-key', 'anonymous')}"

            limiter.add_rule("/api/premium", limit=10000, window=3600, key_func=extract_api_key)
        ```
        """
        if not self._initialized:
            raise ValueError("Throtty must be initialized in order to register a rule")
        window = timedelta(seconds=window)

        if path.startswith("^"):
            pattern = re.compile(path)
        elif "*" in path:
            regex_path = path.replace("*", ".*")
            pattern = re.compile(f"^{regex_path}$")
        else:
            pattern = re.compile(f"^{re.escape(path)}$")

        self.rules.append(
            {
                "path": path,
                "pattern": pattern,
                "limit": limit,
                "window": window,
                "key_func": key_func,
            }
        )

    def rule(self, path: str, str_rule: str, key_func: Optional[Callable]):
        """Decorator to add rate limiting rules using a compact string format.

        This is a decorator wrapper around add_rule() that provides a more concise syntax
        for defining multiple rate limits on a single endpoint. Particularly useful when
        you need both short-term and long-term limits (e.g., 10/minute AND 100/hour).

        Rule String Format:
        - Single rule: "limit/window" (e.g., "10/60" = 10 requests per 60 seconds)
        - Multiple rules: "limit1/window1;limit2/window2" (separated by semicolons)
        - All rules must pass for request to be allowed

        Args:
            path (str): Endpoint path to rate limit. Supports exact match, wildcards (*),
                and regex patterns (starting with ^). Same as add_rule().
            str_rule (str): Rate limit specification in "limit/window" format. Multiple limits
                can be chained with semicolons. Examples:
                - "10/60": 10 requests per 60 seconds
                - "100/3600": 100 requests per hour
                - "10/60;100/3600": 10 per minute AND 100 per hour (both enforced)
            key_func (Optional[Callable], optional): Custom key extraction function with signature
                (host: str, headers: dict) -> str. Defaults to None.

        Returns:
            Callable: A decorator function that returns the original function unchanged.
                The decorator only registers the rule; it doesn't modify function behavior.

        Example:
        ```python
            from throtty import Throtty, rule

            limiter = Throtty()
            app = FastAPI()
            limiter.install(app)

            # Simple rate limit: 10 requests per minute
            @app.get("/api/basic")
            @rule("/api/basic", "10/60")
            async def basic_endpoint():
                return {"status": "ok"}

            # Multiple limits: 10/min AND 100/hour
            @app.get("/api/multi")
            @rule("/api/multi", "10/60;100/3600")
            async def multi_limit():
                return {"status": "ok"}

            # With custom key function
            def by_user_id(host, headers):
                return f"user:{headers.get('x-user-id', 'anonymous')}"

            @app.get("/api/user-limited")
            @rule("/api/user-limited", "100/3600", key_func=by_user_id)
            async def user_endpoint():
                return {"status": "ok"}
        ```
        """
        rules = [tuple(group.split("/")) for group in str_rule.split(";")]
        for limit, window in rules:
            self.add_rule(
                path=path, limit=int(limit), window=int(window), key_func=key_func
            )

        def decorator(func):
            return func

        return decorator

    def _find_match_rule(self, path: str) -> Union[RateLimitRules, None]:
        """Find the first rate limiting rule matching the given request path.

        Rules are evaluated in the order they were added. The first rule whose regex pattern
        matches the path is returned. If no rules match, returns None and the request proceeds
        without rate limiting.

        Args:
            path (str): The request path to match against configured rules (e.g., "/api/users")

        Returns:
            Union[RateLimitRules, None]: The matching rule dictionary containing pattern, limit,
                window, and key_func, or None if no rules match.

        Note:
            This is an internal method used by the middleware. Users typically don't call this directly.
        """
        for rule in self.rules:
            if not rule["pattern"].match(path):
                continue
            return rule
        return None

    def _decode_headers(self, scope: str) -> dict:
        """Decode ASGI request headers from bytes to UTF-8 strings.

        ASGI provides headers as a list of byte tuples. This helper converts them to a
        dictionary with string keys and values for easier manipulation.

        Args:
            scope (str): ASGI scope dictionary containing request metadata, specifically
                the "headers" field with byte-encoded header tuples

        Returns:
            dict: Dictionary of header names to values, both as UTF-8 decoded strings

        Note:
            This is an internal utility method used by the middleware.
        """
        return {k.decode("utf-8"): v.decode("utf-8") for k, v in scope["headers"]}

    def set_key_extractor(self, func: Callable[..., str]) -> None:
        """Set a global key extraction function for all rate limiting rules.

        The key extractor determines how to identify unique clients for rate limiting purposes.
        By default, Throtty uses the client's IP address. Use this method to implement custom
        identification logic (e.g., by user ID, API key, session token).

        The global extractor applies to all rules unless a specific rule defines its own key_func,
        which takes precedence.

        Function Signature:
            func(host: str, headers: dict) -> str

        Priority Order:
        1. Rule-specific key_func (highest priority)
        2. Global key_extractor (set via this method)
        3. Default IP-based key: "ip:{client_ip}" (fallback)

        Args:
            func (Callable[..., str]): Key extraction function that takes the client host/IP
                and request headers dict, returning a unique string identifier for rate limiting.

        Example:
        ```python
            limiter = Throtty()

            # Rate limit by API key from header
            def extract_api_key(host, headers):
                api_key = headers.get('x-api-key', 'anonymous')
                return f"apikey:{api_key}"

            limiter.set_key_extractor(extract_api_key)

            # Rate limit by user ID with fallback to IP
            def extract_user(host, headers):
                user_id = headers.get('x-user-id')
                if user_id:
                    return f"user:{user_id}"
                return f"ip:{host}"

            limiter.set_key_extractor(extract_user)

            # Rate limit by combination of factors
            def extract_composite(host, headers):
                user = headers.get('x-user-id', 'anonymous')
                endpoint = headers.get('x-endpoint-category', 'general')
                return f"{user}:{endpoint}"

            limiter.set_key_extractor(extract_composite)
        ```
        """
        self.key_extractor = func

    def install(self, app):
        """Install Throtty middleware into the ASGI application to enable rate limiting.

        This method must be called to activate rate limiting. It adds ThrottyMiddleware to the
        application's middleware stack, which will intercept and check all incoming requests
        against configured rules.

        The middleware is added to the beginning of the middleware chain, ensuring rate limiting
        occurs before other middleware and route handlers.

        Args:
            app (Any): ASGI application instance with an `add_middleware` method. Compatible with
                FastAPI, Starlette, and other ASGI frameworks that follow this convention.

        Raises:
            NotImplementedError: If the provided application doesn't have an `add_middleware`
                method, indicating it's not compatible with Throtty's middleware system.

        Example:
        ```python
            from fastapi import FastAPI
            from throtty import Throtty

            # Create and configure limiter
            limiter = Throtty(redis_dsn="redis://localhost:6379")
            limiter.add_rule("/api/*", limit=100, window=60)

            # Create app and install middleware
            app = FastAPI()
            limiter.install(app)  # Must call this to activate rate limiting

            @app.get("/api/users")
            async def get_users():
                return {"users": []}
        ```
        """
        if hasattr(app, "add_middleware"):
            app.add_middleware(ThrottyMiddleware, throtty=self)
        else:
            raise NotImplementedError("Not implemented")


def rule(path: str, str_rule: str, key_func: Optional[Callable] = None):
    """Decorator function to add rate limiting rules with compact string syntax.

    This is a standalone decorator that provides syntactic sugar for the Throtty.rule() method.
    It allows you to apply rate limits directly to route handlers without explicitly accessing
    the Throtty instance.

    Requirements:
    - Throtty must be instantiated before using this decorator
    - The decorator must be applied after the route decorator (closer to the function)

    Rule String Format:
    - Single: "limit/window_seconds" (e.g., "10/60")
    - Multiple: "limit1/window1;limit2/window2" (e.g., "10/60;100/3600")

    Args:
        path (str): Endpoint path to rate limit. Supports exact paths, wildcards with *,
            and regex patterns starting with ^. Should match the route path.
        str_rule (str): Rate limit specification in "limit/window" format. Multiple limits
            separated by semicolons are all enforced (logical AND).
            Examples:
            - "10/60": Max 10 requests per 60 seconds
            - "100/3600": Max 100 requests per hour
            - "10/60;100/3600": Both 10/min AND 100/hour must be satisfied
        key_func (Optional[Callable], optional): Custom key extraction function with signature
            (host: str, headers: dict) -> str for per-user or per-key limiting. Defaults to None.

    Raises:
        RuntimeError: If this decorator is used before initializing a Throtty instance anywhere
            in the application. Always instantiate Throtty first.

    Returns:
        Callable: Decorator function that returns the wrapped function unchanged. The decorator
            only registers the rate limiting rule without modifying function behavior.

    Example:
    ```python
        from fastapi import FastAPI
        from throtty import Throtty, rule

        # Initialize Throtty FIRST (required!)
        limiter = Throtty()
        app = FastAPI()
        limiter.install(app)

        # Basic usage: 10 requests per minute
        @app.get("/api/limited")
        @rule("/api/limited", "10/60")
        async def limited_endpoint():
            return {"message": "rate limited endpoint"}

        # Multiple limits: both must be satisfied
        @app.post("/api/strict")
        @rule("/api/strict", "5/60;50/3600")  # 5/min AND 50/hour
        async def strict_endpoint():
            return {"message": "strictly limited"}

        # Custom key function for per-user limits
        def by_user(host, headers):
            return f"user:{headers.get('authorization', 'anonymous')}"

        @app.get("/api/user-limit")
        @rule("/api/user-limit", "100/3600", key_func=by_user)
        async def user_limited():
            return {"message": "per-user rate limit"}

        # Wildcard path matching
        @app.get("/api/v1/users")
        @app.get("/api/v1/posts")
        @rule("/api/v1/*", "1000/3600")  # Applies to all /api/v1/* routes
        async def v1_endpoints():
            return {"message": "v1 endpoint"}
    ```

    Note:
        - Must call Throtty() before using @rule decorator
        - Apply @rule AFTER @app.get/post/etc. (closer to function definition)
        - Path in @rule should match the route path for proper enforcement
        - All limits in a semicolon-separated rule must pass (AND logic)
    """
    instance = Throtty._get_instance()
    if instance is None or not getattr(instance, "_initialized", False):
        raise RuntimeError("@rule was used before Throtty was initialized.")
    return instance.rule(path=path, str_rule=str_rule, key_func=key_func)
