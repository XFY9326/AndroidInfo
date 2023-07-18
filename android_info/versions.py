import re
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup
from dataclasses_json import DataClassJsonMixin

from .consts import API_LEVEL_MAPPING
from .utils import VersionCompare


@dataclass
class AndroidBuildVersion(DataClassJsonMixin):
    tag: str
    name: Optional[str]
    version: str
    revision: str
    is_security: bool
    build_id: str
    security_patch_level: Optional[str]

    def __post_init__(self):
        self._version_compare: VersionCompare = VersionCompare.instance()

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
class AndroidAPILevel(DataClassJsonMixin):
    name: Optional[str]
    version_range: str
    versions: tuple[str]
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


class AndroidVersions:
    _BS4_PARSER = "lxml"
    _BASE_URL = "https://source.android.com/docs/setup/about/build-numbers"

    def __init__(self, client: aiohttp.ClientSession):
        self._client: aiohttp.ClientSession = client
        self._version_tag_regex: re.Pattern = re.compile(r"android(-security)?-(.*)_r(.*)")
        self._api_ndk_regex: re.Pattern = re.compile(r"API level (\d+)(, NDK (\d+))?")
        self._build_versions: Optional[list[AndroidBuildVersion]] = None
        self._api_levels: Optional[list[AndroidAPILevel]] = None
        self._version_compare: VersionCompare = VersionCompare.instance()
        self._checked_api_mappings: Optional[dict[int, list[str]]] = None

    async def _fetch_docs(self) -> BeautifulSoup:
        async with self._client.get(self._BASE_URL, raise_for_status=True) as response:
            return BeautifulSoup(await response.text(), self._BS4_PARSER)

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

    def _get_api_levels(self, soup: BeautifulSoup, api_level_mappings: dict[int, list[str]]) -> list[AndroidAPILevel]:
        def _parse_codename(codename: str) -> Optional[str]:
            return codename if "no codename" not in codename else None

        # Missing API 20 in android docs
        def _generate_kitkat_wear() -> AndroidAPILevel:
            return AndroidAPILevel(
                name="KitKat Wear",
                version_range="4.4w",
                versions=tuple(api_level_mappings[20] if 20 in api_level_mappings else []),
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
            AndroidAPILevel(
                name=_parse_codename(e1.text.strip()),
                version_range=e2.text.strip(),
                versions=tuple(api_level_mappings[api] if api in api_level_mappings else []),
                api=api,
                ndk=ndk
            )
            for e1, e2, (api, ndk) in zip(codename_elements, version_elements, api_ndk)
        ]
        api_levels.append(_generate_kitkat_wear())
        return api_levels

    async def _list_android_versions(self, build_versions: list[AndroidBuildVersion]) -> list[str]:
        return sorted(set([i.version for i in build_versions]), key=cmp_to_key(self._version_compare.compare))

    async def get_api_mappings(self, build_versions: list[AndroidBuildVersion]) -> dict[int, list[str]]:
        if self._checked_api_mappings is None:
            android_versions = await self._list_android_versions(build_versions)
            exists_versions = set([j for i in API_LEVEL_MAPPING.values() for j in i])
            missing_versions = set(android_versions) - exists_versions
            if len(missing_versions) > 0:
                raise ValueError(f"Missing version: {missing_versions}")
            self._checked_api_mappings = API_LEVEL_MAPPING
        return self._checked_api_mappings

    async def _prepare(self):
        if self._build_versions is None or self._build_versions is None:
            soup = await self._fetch_docs()
            self._build_versions = sorted(self._get_build_versions(soup) + self._get_honeycomb_build_versions(soup))
            api_mappings = await self.get_api_mappings(self._build_versions)
            self._api_levels = self._api_level_ndk_fix(self._get_api_levels(soup, api_mappings))

    async def list_build_versions(self) -> list[AndroidBuildVersion]:
        await self._prepare()
        assert self._build_versions is not None
        return self._build_versions

    async def list_api_levels(self) -> list[AndroidAPILevel]:
        await self._prepare()
        assert self._api_levels is not None
        return self._api_levels

    async def get_build_versions(self, version: str) -> list[AndroidBuildVersion]:
        await self._prepare()
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

    async def get_latest_build_version(self, version: str, is_security: Optional[bool] = None) -> Optional[AndroidBuildVersion]:
        build_versions = await self.get_build_versions(version)
        return self._get_latest_build_version(build_versions, is_security)

    async def get_api_level(self, api: int) -> Optional[AndroidAPILevel]:
        await self._prepare()
        assert self._api_levels is not None
        if api <= 0:
            raise ValueError("Non positive API level!")
        for api_level in self._api_levels:
            if api_level.api == api:
                return api_level
        return None

    async def list_android_versions(self) -> list[str]:
        await self._prepare()
        assert self._build_versions is not None
        return await self._list_android_versions(self._build_versions)

    async def get_android_version_api_level(self, version: str) -> AndroidAPILevel:
        for api_level in await self.list_api_levels():
            if version in set(api_level.versions):
                return api_level
        raise ValueError(f"Unknown android version: {version}")

    async def get_api_build_versions(self, api: int) -> list[AndroidBuildVersion]:
        api_level = await self.get_api_level(api)
        return [build for version in api_level.versions for build in (await self.get_build_versions(version))]

    async def get_latest_api_build_version(self, api: int, is_security: Optional[bool] = None) -> Optional[AndroidBuildVersion]:
        build_versions = await self.get_api_build_versions(api)
        return self._get_latest_build_version(build_versions, is_security)
