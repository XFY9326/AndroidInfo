import codecs
import dataclasses
import html
import re

import aiohttp
from dataclasses_json import DataClassJsonMixin
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element

from .consts import ANDROID_MANIFEST_NS
from .source_code import AndroidRemoteSourceCode, AndroidSourceCodePath
from .utils import android_attrib


@dataclasses.dataclass(frozen=True)
class PermissionComment(DataClassJsonMixin):
    deprecated: bool
    system_api: bool
    test_api: bool
    hide: bool

    def is_sdk(self) -> bool:
        return not (self.system_api or self.test_api or self.hide)


@dataclasses.dataclass(frozen=True)
class AndroidPermissionGroup(DataClassJsonMixin):
    name: str
    description: str | None
    label: str | None
    priority: int | None
    comment: PermissionComment

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AndroidPermissionGroup):
            return self.name == other.name
        return False

    def is_sdk(self) -> bool:
        return self.comment.is_sdk()


@dataclasses.dataclass(frozen=True)
class AndroidPermission(DataClassJsonMixin):
    name: str
    description: str | None
    label: str | None
    group: str | None
    protection_levels: list[str]
    permission_flags: list[str]
    priority: int | None
    comment: PermissionComment

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AndroidPermission):
            return self.name == other.name
        return False

    def is_sdk(self) -> bool:
        protect_levels = set(self.protection_levels)
        return self.comment.is_sdk() and all([
            i not in protect_levels
            for i in ["signature", "knownSigner", "signatureOrSystem", "privileged", "internal", "development"]
        ])


@dataclasses.dataclass(frozen=True)
class AndroidPermissions(DataClassJsonMixin):
    groups: dict[str, AndroidPermissionGroup]
    permissions: dict[str, AndroidPermission]

    def list_groups(self) -> list[AndroidPermissionGroup]:
        return [i for _, i in sorted(self.groups.items(), key=lambda x: x[0])]

    def list_permissions(self) -> list[AndroidPermission]:
        return [i for _, i in sorted(self.permissions.items(), key=lambda x: x[0])]


@dataclasses.dataclass(frozen=True)
class _RawPermissionGroup:
    name: str
    description: str | None
    label: str | None
    priority: str | None
    comment: PermissionComment

    def get_priority(self) -> int | None:
        return int(self.priority) if self.priority is not None else 0

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _RawPermissionGroup):
            return self.name == other.name
        return False


@dataclasses.dataclass(frozen=True)
class _RawPermission:
    name: str
    description: str | None
    label: str | None
    group: str | None
    protection_level: str | None
    permission_flags: str | None
    priority: str | None
    comment: PermissionComment

    @staticmethod
    def _divide(text: str | None, symbol: str = "|") -> list[str]:
        if text is None:
            return []
        elif symbol in text:
            return text.split(symbol)
        else:
            return [text]

    def get_protection_levels(self) -> list[str]:
        return self._divide(self.protection_level)

    def get_permission_flags(self) -> list[str]:
        return self._divide(self.permission_flags)

    def get_priority(self) -> int | None:
        return int(self.priority) if self.priority is not None else 0

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _RawPermission):
            return self.name == other.name
        return False


class _AndroidCoreResString:
    _ID_START = "@string/"
    _PROJECT_PATH = "platform/frameworks/base"

    def __init__(self, client: aiohttp.ClientSession, refs: str, download_dir: str | None, lang: str | None = None,
                 load_cache: bool = False):
        value_path = "values" if lang is None else f"values-{lang.strip()}"
        self._source: AndroidRemoteSourceCode = AndroidRemoteSourceCode(
            client, AndroidSourceCodePath(self._PROJECT_PATH, f"core/res/res/{value_path}/strings.xml"), download_dir
        )
        self._refs: str = refs
        self._load_cache: bool = load_cache
        self._res_strings: dict[str, str] | None = None

    async def _get_content(self) -> dict[str, str]:
        manifest = await self._source.get_content(self._refs, self._load_cache)
        tree: _Element = etree.fromstring(manifest.encode("utf-8"))
        return {
            string_element.attrib["name"]: string_element.text
            for string_element in tree.xpath("/resources/string[@name]")
        }

    async def get_res_strings(self) -> dict[str, str]:
        if self._res_strings is None:
            self._res_strings = await self._get_content()
        return self._res_strings

    async def get_string(self, res_id: str) -> str | None:
        string_dict = await self.get_res_strings()
        if res_id.startswith(self._ID_START):
            key = res_id[len(self._ID_START):]
            if key in string_dict:
                return string_dict[key]
        raise ValueError(f"Unknown string res id: {res_id}")


class _AndroidCoreManifest:
    _PERMISSION_MANIFEST = AndroidSourceCodePath("platform/frameworks/base", "core/res/AndroidManifest.xml")

    def __init__(self, client: aiohttp.ClientSession, refs: str, download_dir: str | None, load_cache: bool = False):
        self._source: AndroidRemoteSourceCode = AndroidRemoteSourceCode(
            client, self._PERMISSION_MANIFEST, download_dir
        )
        self._refs: str = refs
        self._load_cache: bool = load_cache
        self._permission_groups: dict[str, _RawPermissionGroup] | None = None
        self._permissions: dict[str, _RawPermission] | None = None

    async def _get_content(self) -> tuple[dict[str, _RawPermissionGroup], dict[str, _RawPermission]]:
        def _get_android_attrib(element, key: str) -> str | None:
            return element.attrib[android_attrib(key)] if android_attrib(key) in element.attrib else None

        def _get_comment_info(element) -> PermissionComment:
            prev_element = element.getprevious()
            if prev_element is not None:
                if hasattr(prev_element, "tag") and \
                        hasattr(prev_element, "text") and \
                        isinstance(prev_element.tag, type(etree.Comment)) and \
                        prev_element.text is not None:
                    return PermissionComment(
                        deprecated="@deprecated" in prev_element.text,
                        system_api="@SystemApi" in prev_element.text,
                        test_api="@TestApi" in prev_element.text,
                        hide="@hide" in prev_element.text
                    )
            return PermissionComment(
                deprecated=False,
                system_api=False,
                test_api=False,
                hide=False
            )

        manifest = await self._source.get_content(self._refs, self._load_cache)
        tree: _Element = etree.fromstring(manifest.encode("utf-8"))
        permission_groups = {
            e.attrib[android_attrib("name")]: _RawPermissionGroup(
                name=e.attrib[android_attrib("name")],
                description=_get_android_attrib(e, "description"),
                label=_get_android_attrib(e, "label"),
                priority=_get_android_attrib(e, "priority"),
                comment=_get_comment_info(e),
            )
            for e in tree.xpath("/manifest/permission-group[@android:name]", namespaces=ANDROID_MANIFEST_NS)
        }
        permissions = {
            e.attrib[android_attrib("name")]: _RawPermission(
                name=e.attrib[android_attrib("name")],
                description=_get_android_attrib(e, "description"),
                label=_get_android_attrib(e, "label"),
                group=_get_android_attrib(e, "permissionGroup"),
                protection_level=_get_android_attrib(e, "protectionLevel"),
                permission_flags=_get_android_attrib(e, "permissionFlags"),
                priority=_get_android_attrib(e, "priority"),
                comment=_get_comment_info(e)
            )
            for e in tree.xpath("/manifest/permission[@android:name]", namespaces=ANDROID_MANIFEST_NS)
        }
        return permission_groups, permissions

    async def _prepare(self):
        if self._permission_groups is None or self._permissions is None:
            self._permission_groups, self._permissions = await self._get_content()

    async def get_permission_groups(self) -> dict[str, _RawPermissionGroup]:
        await self._prepare()
        assert self._permission_groups is not None
        return self._permission_groups

    async def get_permissions(self) -> dict[str, _RawPermission]:
        await self._prepare()
        assert self._permissions is not None
        return self._permissions


class AndroidFrameworkPermissions:

    def __init__(self, client: aiohttp.ClientSession, refs: str, permissions_tmp_dir: str | None = None,
                 res_lang: str | None = None, load_cache: bool = False):
        self._manifest: _AndroidCoreManifest = _AndroidCoreManifest(client, refs, permissions_tmp_dir, load_cache)
        self._res_string: _AndroidCoreResString = _AndroidCoreResString(client, refs, permissions_tmp_dir, res_lang,
                                                                        load_cache)
        self._permissions: AndroidPermissions | None = None

    async def _parse_raw_text(self, text: str | None) -> str | None:
        def _clean_text(string: str) -> str:
            string = "\n".join([i.strip() for i in string.splitlines() if len(i.strip()) > 0])
            string = html.unescape(string)
            string = codecs.decode(string, "unicode-escape")
            string = re.sub(r"\s+", " ", string)
            return string

        if text is None:
            return None
        elif text.startswith("@"):
            return _clean_text(await self._res_string.get_string(text))
        else:
            return _clean_text(text)

    async def _get_content(self) -> AndroidPermissions:
        permission_groups = {
            k: AndroidPermissionGroup(
                name=i.name,
                description=await self._parse_raw_text(i.description),
                label=await self._parse_raw_text(i.label),
                priority=i.get_priority(),
                comment=i.comment
            )
            for k, i in (await self._manifest.get_permission_groups()).items()
        }
        permissions = {
            k: AndroidPermission(
                name=i.name,
                description=await self._parse_raw_text(i.description),
                label=await self._parse_raw_text(i.label),
                group=i.group,
                protection_levels=i.get_protection_levels(),
                permission_flags=i.get_permission_flags(),
                priority=i.get_priority(),
                comment=i.comment
            )
            for k, i in (await self._manifest.get_permissions()).items()
        }
        return AndroidPermissions(permission_groups, permissions)

    async def get_permissions(self, sdk: bool = False) -> AndroidPermissions:
        if self._permissions is None:
            self._permissions = await self._get_content()
        if sdk:
            return AndroidPermissions(
                groups={k: v for k, v in self._permissions.groups.items() if v.is_sdk()},
                permissions={k: v for k, v in self._permissions.permissions.items() if v.is_sdk()},
            )
        else:
            return self._permissions
