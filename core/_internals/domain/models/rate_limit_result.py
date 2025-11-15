from dataclasses import dataclass
from typing import Optional

from ...domain.exceptions import RateLimitExceeded


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: float
    reset_at: float
    retry_after: Optional[int] = None

    def check(self) -> None:
        if not self.allowed:
            raise RateLimitExceeded()

    def dump(self) -> dict:
        return {k: str(v).encode("utf-8") for k, v in self.__dict__.items()}
