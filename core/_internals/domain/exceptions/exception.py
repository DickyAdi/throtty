class ThrottyError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return f"{self.__class__.__name__}:{self.message}"


class UnsupportedStorage(ThrottyError):
    def __init__(self):
        super().__init__(message="Unsupported storage.")


class RedisError(ThrottyError):
    def __init__(self, message):
        super().__init__(message)


class RateLimitExceeded(ThrottyError):
    def __init__(self):
        super().__init__(message="Rate limit exceeded")
