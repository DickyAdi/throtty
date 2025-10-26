from dataclasses import dataclass


@dataclass
class BucketState:
    latest_refill: float
    tokens: float
