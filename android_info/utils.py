import re
from functools import lru_cache
from itertools import zip_longest
from typing import Optional

from .consts import ANDROID_MANIFEST_NS


@lru_cache
def android_attrib(name: str) -> str:
    return f"{{{ANDROID_MANIFEST_NS['android']}}}{name}"


class VersionCompare:
    _INSTANCE: Optional['VersionCompare'] = None

    @staticmethod
    def instance() -> 'VersionCompare':
        if VersionCompare._INSTANCE is None:
            VersionCompare._INSTANCE = VersionCompare()
        return VersionCompare._INSTANCE

    def __init__(self):
        self._version_pattern: re.Pattern = re.compile(r"(\d+)([a-zA-Z]*)")

    def compare(self, v1: str, v2: str) -> int:
        if v1 == v2:
            return 0

        m1 = self._version_pattern.findall(v1)
        m2 = self._version_pattern.findall(v2)

        for p1, p2 in zip_longest(m1, m2):
            c1, s1 = p1 if p1 is not None else (0, "")
            c2, s2 = p2 if p2 is not None else (0, "")
            c1, c2 = int(c1), int(c2)

            if c1 < c2:
                return -1
            elif c1 > c2:
                return 1
            elif s1 < s2:
                return -1
            elif s1 > s2:
                return 1

        return 0
