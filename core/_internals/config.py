import re

SUPPORTED_STORAGE_PATT: dict[re.Pattern] = {"redis": re.compile(r"redis")}
