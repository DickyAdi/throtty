from dataclasses import dataclass


@dataclass
class WindowData:
    current_count: int
    previous_count: int
    current_window: int
