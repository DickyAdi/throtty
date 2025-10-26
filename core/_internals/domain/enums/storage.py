from enum import Enum


class StorageType(str, Enum):
    redis = "redis"
    in_mem = "in-mem"
