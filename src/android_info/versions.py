import dataclasses
import re
from functools import cmp_to_key
from typing import Optional, Union

import aiohttp
from bs4 import BeautifulSoup
from dataclasses_json import DataClassJsonMixin

from .consts import API_LEVEL_MAPPING
from .utils import VersionCompare


@dataclasses.dataclass(frozen=True)
class AndroidBuildTag(DataClassJsonMixin):
    tag: str
    version: str
    revision: str
    is_security: bool

    @staticmethod
    def parse(tag: str) -> 'AndroidBuildTag':
        matcher = re.match(r"android(-security)?-(.*)_r(.*)", tag)
        if matcher is not None:
            return AndroidBuildTag(
                tag=matcher.group(0),
                version=matcher.group(2),
                revision=matcher.group(3),
                is_security=matcher.group(1) is not None,
            )
        else:
            raise ValueError(f"Not a valid android build tag: {tag}")

    def match_version(self, version: str) -> bool:
        return VersionCompare.instance().compare(self.version, version) == 0

    def compare_version(self, version: str) -> int:
        return VersionCompare.instance().compare(self.version, version)

    def __str__(self) -> str:
        return self.tag

    @property
    def short_version(self) -> str:
        return f"{self.version}_{self.revision}"

    def __eq__(self, o: object) -> bool:
        if isinstance(o, AndroidBuildTag):
            return VersionCompare.instance().compare(self.short_version, o.short_version) == 0
        return False

    def __ne__(self, o: object) -> bool:
        return not self.__eq__(o)

    def __hash__(self) -> int:
        return hash(self.tag)

    def __lt__(self, other: object) -> bool:
        if isinstance(other, AndroidBuildTag):
            return VersionCompare.instance().compare(self.short_version, other.short_version) < 0
        else:
            raise NotImplementedError

    def __le__(self, other: object) -> bool:
        if isinstance(other, AndroidBuildTag):
            return VersionCompare.instance().compare(self.short_version, other.short_version) <= 0
        else:
            raise NotImplementedError

    def __gt__(self, other: object) -> bool:
        return not self.__le__(other)

    def __ge__(self, other: object) -> bool:
        return not self.__lt__(other)


@dataclasses.dataclass(frozen=True)
class AndroidBuildVersion(AndroidBuildTag):
    name: Optional[str]
    build_id: str
    security_patch_level: Optional[str]

    @staticmethod
    def from_tag(
            tag: Union[str, AndroidBuildTag],
            build_id: str,
            name: Optional[str] = None,
            security_patch_level: Optional[str] = None
    ) -> 'AndroidBuildVersion':
        if isinstance(tag, str):
            build_tag = AndroidBuildTag.parse(tag)
        elif isinstance(tag, AndroidBuildTag):
            build_tag = tag
        else:
            raise TypeError("Tag type error!")
        return AndroidBuildVersion(
            tag=build_tag.tag,
            version=build_tag.version,
            revision=build_tag.revision,
            is_security=build_tag.is_security,
            name=name,
            build_id=build_id,
            security_patch_level=security_patch_level
        )


@dataclasses.dataclass
class AndroidAPILevel(DataClassJsonMixin):
    name: Optional[str]
    version_range: str
    versions: list[str]
    api: int

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
        self._regex_api_ndk: re.Pattern = re.compile(r"API level (\d+)(, NDK (\d+))?")
        self._build_versions: Optional[list[AndroidBuildVersion]] = None
        self._api_levels: Optional[list[AndroidAPILevel]] = None
        self._version_compare: VersionCompare = VersionCompare.instance()
        self._checked_api_mappings: Optional[dict[int, list[str]]] = None

    async def _fetch_docs(self) -> BeautifulSoup:
        async with self._client.get(self._BASE_URL) as response:
            return BeautifulSoup(await response.text(), self._BS4_PARSER)

    @staticmethod
    def _get_build_versions(soup: BeautifulSoup) -> list[AndroidBuildVersion]:
        def _transform_empty_str(text: str) -> Optional[str]:
            return text if len(text) > 0 else None

        table_body = soup.find(id="source-code-tags-and-builds").find_next("tbody")
        build_id_elements = table_body.select("tr > td:nth-child(1)")
        tag_elements = table_body.select("tr > td:nth-child(2)")
        name_elements = table_body.select("tr > td:nth-child(3)")
        security_patch_elements = table_body.select("tr > td:nth-child(5)")
        tags = [i.text.strip() for i in tag_elements]
        return [
            AndroidBuildVersion.from_tag(
                tag=tag,
                name=_transform_empty_str(e2.text.strip()),
                build_id=e3.text.strip(),
                security_patch_level=_transform_empty_str(e4.text.strip()),
            )
            for tag, e2, e3, e4 in zip(tags, name_elements, build_id_elements, security_patch_elements)
        ]

    @staticmethod
    def _get_honeycomb_build_versions(soup: BeautifulSoup) -> list[AndroidBuildVersion]:
        section_title = soup.find(id="honeycomb-gpl-modules")
        table_body = section_title.find_next("tbody")
        build_id_elements = table_body.select("tr > td:nth-child(1)")
        tag_elements = table_body.select("tr > td:nth-child(2)")
        tags = [i.text.strip() for i in tag_elements]
        return [
            AndroidBuildVersion.from_tag(
                tag=tag,
                name="Honeycomb",
                build_id=e2.text.strip(),
                security_patch_level=None,
            )
            for tag, e2 in zip(tags, build_id_elements)
        ]

    def _get_api_levels(self, soup: BeautifulSoup, api_level_mappings: dict[int, list[str]]) -> list[AndroidAPILevel]:
        def _parse_codename(codename: str) -> Optional[str]:
            return codename if "no codename" not in codename else None

        # Missing API 20 in android docs
        def _generate_kitkat_wear() -> AndroidAPILevel:
            return AndroidAPILevel(
                name="KitKat Wear",
                version_range="4.4w",
                versions=api_level_mappings[20] if 20 in api_level_mappings else [],
                api=20
            )

        def _parse_api_version(api_ndk_text: str) -> int:
            matcher = self._regex_api_ndk.match(api_ndk_text)
            return int(matcher.group(1))

        section_title = soup.find(id="source-code-tags-and-builds")
        table_body = section_title.find_previous("tbody")
        codename_elements = table_body.select("tr > td:nth-child(1)")
        version_elements = table_body.select("tr > td:nth-child(2)")
        api_version_elements = table_body.select("tr > td:nth-child(3)")
        api_versions = [_parse_api_version(e.text.strip()) for e in api_version_elements]
        api_levels = [
            AndroidAPILevel(
                name=_parse_codename(e1.text.strip()),
                version_range=e2.text.strip(),
                versions=api_level_mappings[api] if api in api_level_mappings else [],
                api=api
            )
            for e1, e2, api in zip(codename_elements, version_elements, api_versions)
        ]
        api_levels.append(_generate_kitkat_wear())
        return sorted(api_levels, key=lambda x: x.api, reverse=True)

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
            self._api_levels = self._get_api_levels(soup, api_mappings)

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
