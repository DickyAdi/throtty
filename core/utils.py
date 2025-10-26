from urllib.parse import urlparse
from _internals import SUPPORTED_STORAGE_PATT

from exception import UnsupportedStorage


def detect_storage(dsn: str):
    if not isinstance(dsn, str):
        raise ValueError(
            f"Storage must be a url string of supported storage. Got type {type(dsn)}"
        )

    scheme = urlparse(dsn).scheme
    if _match := SUPPORTED_STORAGE_PATT["redis"].search(scheme):
        return "redis"
    raise UnsupportedStorage()
