import re
from dataclasses import dataclass
from functools import cmp_to_key
from itertools import zip_longest
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Manually written due to lack of documentation
API_LEVEL_MAPPING: dict[int, list[str]] = {
    1: ["1.0"],
    2: ["1.1"],
    3: ["1.5"],
    4: ["1.6"],
    5: ["2.0"],
    6: ["2.0.1"],
    7: ["2.1"],
    8: ["2.2", "2.2.1", "2.2.2", "2.2.3"],
    9: ["2.3", "2.3.1", "2.3.2"],
    10: ["2.3.3", "2.3.4", "2.3.5", "2.3.6", "2.3.7"],
    11: ["3.0"],
    12: ["3.1"],
    13: ["3.2", "3.2.1", "3.2.2", "3.2.4", "3.2.6"],
    14: ["4.0.1", "4.0.2"],
    15: ["4.0.3", "4.0.4"],
    16: ["4.1.1", "4.1.2"],
    17: ["4.2", "4.2.1", "4.2.2"],
    18: ["4.3", "4.3.1"],
    19: ["4.4", "4.4.1", "4.4.2", "4.4.3", "4.4.4"],
    20: ["4.4w"],
    21: ["5.0.0", "5.0.1", "5.0.2", "5.1.0"],
    22: ["5.1.1"],
    23: ["6.0.0", "6.0.1"],
    24: ["7.0.0"],
    25: ["7.1.0", "7.1.1", "7.1.2"],
    26: ["8.0.0"],
    27: ["8.1.0"],
    28: ["9.0.0"],
    29: ["10.0.0"],
    30: ["11.0.0"],
    31: ["12.0.0"],
    32: ["12.1.0"],
    33: ["13.0.0"],
    34: ["14.0.0"]
}


class VersionCompare:
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


@dataclass
class AndroidBuildVersion:
    tag: str
    name: Optional[str]
    version: str
    revision: str
    is_security: bool
    build_id: str
    security_patch_level: Optional[str]

    def __post_init__(self):
        self._version_compare: VersionCompare = VersionCompare()

    def match_version(self, version: str) -> bool:
        return self._version_compare.compare(self.version, version) == 0

    def compare_version(self, version: str) -> int:
        return self._version_compare.compare(self.version, version)

    def __str__(self) -> str:
        return self.tag

    @property
    def short_version(self) -> str:
        return f"{self.version}_{self.revision}"

    def __eq__(self, o: object) -> bool:
        if isinstance(o, AndroidBuildVersion):
            return self._version_compare.compare(self.short_version, o.short_version) == 0
        return False

    def __ne__(self, o: object) -> bool:
        return not self.__eq__(o)

    def __hash__(self) -> int:
        return hash(self.name)

    def __lt__(self, other: object) -> bool:
        if isinstance(other, AndroidBuildVersion):
            return self._version_compare.compare(self.short_version, other.short_version) < 0
        else:
            raise NotImplementedError

    def __le__(self, other: object) -> bool:
        if isinstance(other, AndroidBuildVersion):
            return self._version_compare.compare(self.short_version, other.short_version) <= 0
        else:
            raise NotImplementedError

    def __gt__(self, other: object) -> bool:
        return not self.__le__(other)

    def __ge__(self, other: object) -> bool:
        return not self.__lt__(other)


@dataclass
class AndroidAPILevel:
    name: Optional[str]
    version_range: str
    api: int
    ndk: Optional[int]

    def __str__(self) -> str:
        if self.name is not None:
            return self.name
        else:
            return f"API: {self.api}"

    def __eq__(self, o: object) -> bool:
        if isinstance(o, AndroidAPILevel):
            return self.api == o.api
        return False

    def __ne__(self, o: object) -> bool:
        return not self.__eq__(o)

    def __hash__(self) -> int:
        return hash(self.api)

    def __lt__(self, other: object) -> bool:
        if isinstance(other, AndroidAPILevel):
            return self.api < other.api
        else:
            raise NotImplementedError

    def __le__(self, other: object) -> bool:
        if isinstance(other, AndroidAPILevel):
            return self.api <= other.api
        else:
            raise NotImplementedError

    def __gt__(self, other: object) -> bool:
        return not self.__le__(other)

    def __ge__(self, other: object) -> bool:
        return not self.__lt__(other)


class AndroidBuildNumbers:
    _BS4_PARSER = "lxml"
    _BASE_URL = "https://source.android.com/docs/setup/about/build-numbers"

    def __init__(self):
        self._version_tag_regex: re.Pattern = re.compile(r"android(-security)?-(.*)_r(.*)")
        self._api_ndk_regex: re.Pattern = re.compile(r"API level (\d+)(, NDK (\d+))?")
        self._build_versions: Optional[list[AndroidBuildVersion]] = None
        self._api_levels: Optional[list[AndroidAPILevel]] = None
        self._version_compare: VersionCompare = VersionCompare()

    def _fetch_docs(self) -> BeautifulSoup:
        with requests.get(self._BASE_URL) as response:
            return BeautifulSoup(response.content, self._BS4_PARSER)

    def _get_build_versions(self, soup: BeautifulSoup) -> list[AndroidBuildVersion]:
        def _transform_empty_str(text: str) -> Optional[str]:
            return text if len(text) > 0 else None

        table_body = soup.find(id="build").find_next("tbody")
        build_id_elements = table_body.select("tr > td:nth-child(1)")
        tag_elements = table_body.select("tr > td:nth-child(2)")
        name_elements = table_body.select("tr > td:nth-child(3)")
        security_patch_elements = table_body.select("tr > td:nth-child(5)")
        tag_matchers = [self._version_tag_regex.match(i.text.strip()) for i in tag_elements]
        return [
            AndroidBuildVersion(
                tag=matcher.group(0),
                name=_transform_empty_str(e2.text.strip()),
                version=matcher.group(2),
                revision=matcher.group(3),
                is_security=matcher.group(1) is not None,
                build_id=e3.text.strip(),
                security_patch_level=_transform_empty_str(e4.text.strip()),
            )
            for matcher, e2, e3, e4 in zip(tag_matchers, name_elements, build_id_elements, security_patch_elements)
        ]

    def _get_honeycomb_build_versions(self, soup: BeautifulSoup) -> list[AndroidBuildVersion]:
        section_title = soup.find(id="honeycomb-gpl-modules")
        table_body = section_title.find_next("tbody")
        build_id_elements = table_body.select("tr > td:nth-child(1)")
        tag_elements = table_body.select("tr > td:nth-child(2)")
        tag_matchers = [self._version_tag_regex.match(i.text.strip()) for i in tag_elements]
        return [
            AndroidBuildVersion(
                tag=matcher.group(0),
                name="Honeycomb",
                version=matcher.group(2),
                revision=matcher.group(3),
                is_security=matcher.group(1) is not None,
                build_id=e2.text.strip(),
                security_patch_level=None,
            )
            for matcher, e2 in zip(tag_matchers, build_id_elements)
        ]

    @staticmethod
    def _api_level_ndk_fix(api_levels: list[AndroidAPILevel]) -> list[AndroidAPILevel]:
        api_levels = sorted(api_levels)
        current_ndk: Optional[int] = None
        for api_level in api_levels:
            if api_level.ndk is not None:
                current_ndk = api_level.ndk
            else:
                api_level.ndk = current_ndk
        return api_levels

    def _get_api_levels(self, soup: BeautifulSoup) -> list[AndroidAPILevel]:
        def _parse_codename(codename: str) -> Optional[str]:
            return codename if "no codename" not in codename else None

        # Missing API 20 in android docs
        def _generate_kitkat_wear() -> AndroidAPILevel:
            return AndroidAPILevel(
                name="KitKat Wear",
                version_range="4.4w",
                api=20,
                ndk=None
            )

        def _parse_api_ndk(api_ndk_text: str) -> tuple[int, Optional[int]]:
            matcher = self._api_ndk_regex.match(api_ndk_text)
            api_level = int(matcher.group(1))
            ndk_level = matcher.group(3)
            ndk_level = int(ndk_level) if ndk_level is not None else None
            return api_level, ndk_level

        section_title = soup.find(id="platform-code-names-versions-api-levels-and-ndk-releases")
        table_body = section_title.find_next("tbody")
        codename_elements = table_body.select("tr > td:nth-child(1)")
        version_elements = table_body.select("tr > td:nth-child(2)")
        api_ndk_elements = table_body.select("tr > td:nth-child(3)")
        api_ndk = [_parse_api_ndk(e.text.strip()) for e in api_ndk_elements]
        api_levels = [
            AndroidAPILevel(name=_parse_codename(e1.text.strip()), version_range=e2.text.strip(), api=api, ndk=ndk)
            for e1, e2, (api, ndk) in zip(codename_elements, version_elements, api_ndk)
        ]
        api_levels.append(_generate_kitkat_wear())
        return api_levels

    def _prepare(self):
        if self._build_versions is None or self._build_versions is None:
            soup = self._fetch_docs()
            self._build_versions = sorted(self._get_build_versions(soup) + self._get_honeycomb_build_versions(soup))
            self._api_levels = self._api_level_ndk_fix(self._get_api_levels(soup))

    def list_build_versions(self) -> list[AndroidBuildVersion]:
        self._prepare()
        assert self._build_versions is not None
        return self._build_versions

    def list_api_levels(self) -> list[AndroidAPILevel]:
        self._prepare()
        assert self._api_levels is not None
        return self._api_levels

    def get_build_versions(self, version: str) -> list[AndroidBuildVersion]:
        self._prepare()
        assert self._build_versions is not None
        version = version.strip()
        if len(version) == 0:
            raise ValueError("Empty version!")
        return [i for i in self._build_versions if i.match_version(version)]

    @staticmethod
    def _get_latest_build_version(build_versions: list[AndroidBuildVersion], is_security: Optional[bool] = None) -> Optional[AndroidBuildVersion]:
        if len(build_versions) == 0:
            return None
        build_versions = build_versions if is_security is None else [i for i in build_versions if i.is_security == is_security]
        build_versions = sorted(build_versions, reverse=True)
        return build_versions[0]

    def get_latest_build_version(self, version: str, is_security: Optional[bool] = None) -> Optional[AndroidBuildVersion]:
        build_versions = self.get_build_versions(version)
        return self._get_latest_build_version(build_versions, is_security)

    def get_api_level(self, api: int) -> Optional[AndroidAPILevel]:
        self._prepare()
        assert self._api_levels is not None
        if api <= 0:
            raise ValueError("Non positive API level!")
        filtered_result = [i for i in self._api_levels if i.api == api]
        return filtered_result[0] if len(filtered_result) > 0 else None

    def list_android_versions(self) -> list[str]:
        self._prepare()
        assert self._build_versions is not None
        return sorted(set([i.version for i in self._build_versions]), key=cmp_to_key(self._version_compare.compare))

    def get_android_version_api_level(self, version: str) -> AndroidAPILevel:
        for api, versions in API_LEVEL_MAPPING.items():
            if version in set(versions):
                return self.get_api_level(api)
        raise ValueError(f"Unknown android version: {version}")

    def get_api_build_versions(self, api: int) -> list[AndroidBuildVersion]:
        if api not in API_LEVEL_MAPPING:
            raise ValueError(f"Unknown API level: {api}")
        android_versions = API_LEVEL_MAPPING[api]
        return [build for version in android_versions for build in self.get_build_versions(version)]

    def get_latest_api_build_version(self, api: int, is_security: Optional[bool] = None) -> Optional[AndroidBuildVersion]:
        build_versions = self.get_api_build_versions(api)
        return self._get_latest_build_version(build_versions, is_security)

    def get_api_mappings(self, check_missing: bool = True) -> dict[int, list[str]]:
        if check_missing:
            android_versions = self.list_android_versions()
            exists_versions = set([j for i in API_LEVEL_MAPPING.values() for j in i])
            missing_versions = set(android_versions) - exists_versions
            if len(missing_versions) > 0:
                raise ValueError(f"Missing version: {missing_versions}")
        return API_LEVEL_MAPPING
