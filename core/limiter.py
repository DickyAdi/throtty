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
    """Middleware for rate limiting"""

    def __init__(self, app, throtty: "Throtty"):
        self.app = app
        self.throtty = throtty

    async def __call__(self, scope, receive, send, *args, **kwargs):
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
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs) -> "Throtty":
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _get_instance(cls) -> "Throtty":
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
        rules = [tuple(group.split("/")) for group in str_rule.split(";")]
        for limit, window in rules:
            self.add_rule(
                path=path, limit=int(limit), window=int(window), key_func=key_func
            )

        def decorator(func):
            return func

        return decorator

    def _find_match_rule(self, path: str) -> Union[RateLimitRules, None]:
        for rule in self.rules:
            if not rule["pattern"].match(path):
                continue
            return rule
        return None

    def _decode_headers(self, scope: str) -> dict:
        return {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}

    def set_key_extractor(self, func: Callable[..., str]) -> None:
        self.key_extractor = func

    def install(self, app):
        if hasattr(app, "add_middleware"):
            app.add_middleware(ThrottyMiddleware, throtty=self)
        else:
            raise NotImplementedError("Not implemented")


def rule(path: str, str_rule: str, key_func: Optional[Callable] = None):
    instance = Throtty._get_instance()
    if instance is None or not getattr(instance, "_initialized", False):
        raise RuntimeError("@rule was used before Throtty was initialized.")
    return instance.rule(path=path, str_rule=str_rule, key_func=key_func)
