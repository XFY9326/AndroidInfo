import os.path
from dataclasses import dataclass
from typing import Optional

import aiofiles
import aiohttp
from dataclasses_json import DataClassJsonMixin
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element

from .consts import ANDROID_MANIFEST_NS
from .source_code import AndroidSourceCodePath, AndroidGoogleSource
from .utils import android_attrib


@dataclass(frozen=True)
class PermissionComment(DataClassJsonMixin):
    deprecated: bool
    system_api: bool
    test_api: bool
    hide: bool


@dataclass(frozen=True)
class AndroidPermissionGroup(DataClassJsonMixin):
    name: str
    description: Optional[str]
    label: Optional[str]
    priority: Optional[int]
    comment: PermissionComment

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AndroidPermissionGroup):
            return self.name == other.name
        return False


@dataclass(frozen=True)
class AndroidPermission(DataClassJsonMixin):
    name: str
    description: Optional[str]
    label: Optional[str]
    group: Optional[AndroidPermissionGroup]
    protection_levels: tuple[str]
    permission_flags: tuple[str]
    priority: Optional[int]
    comment: PermissionComment

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AndroidPermission):
            return self.name == other.name
        return False


@dataclass(frozen=True)
class AndroidPermissions(DataClassJsonMixin):
    groups: dict[str, AndroidPermissionGroup]
    permissions: dict[str, AndroidPermission]

    def list_groups(self) -> list[AndroidPermissionGroup]:
        return [i for _, i in sorted(self.groups.items(), key=lambda x: x[0])]

    def list_permissions(self) -> list[AndroidPermission]:
        return [i for _, i in sorted(self.permissions.items(), key=lambda x: x[0])]


@dataclass(frozen=True)
class _RawPermissionGroup:
    name: str
    description: Optional[str]
    label: Optional[str]
    priority: Optional[str]
    comment: PermissionComment

    def get_priority(self) -> Optional[int]:
        return int(self.priority) if self.priority is not None else 0

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _RawPermissionGroup):
            return self.name == other.name
        return False


@dataclass(frozen=True)
class _RawPermission:
    name: str
    description: Optional[str]
    label: Optional[str]
    group: Optional[str]
    protection_level: Optional[str]
    permission_flags: Optional[str]
    priority: Optional[str]
    comment: PermissionComment

    @staticmethod
    def _divide(text: Optional[str], symbol: str = "|") -> tuple[str]:
        if text is None:
            return tuple()
        elif symbol in text:
            return tuple(text.split(symbol))
        else:
            return tuple([text])

    def get_protection_levels(self) -> tuple[str]:
        return self._divide(self.protection_level)

    def get_permission_flags(self) -> tuple[str]:
        return self._divide(self.permission_flags)

    def get_priority(self) -> Optional[int]:
        return int(self.priority) if self.priority is not None else 0

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _RawPermission):
            return self.name == other.name
        return False


class _AndroidCoreResString:
    _ID_START = "@string/"
    _PERMISSION_STRING_MANIFEST = AndroidSourceCodePath("platform/frameworks/base", "core/res/res/values/strings.xml")

    def __init__(self, client: aiohttp.ClientSession, refs: str, tmp_dir: Optional[str], use_tmp: bool = False):
        self._source: AndroidGoogleSource = AndroidGoogleSource(client)
        self._refs = refs
        self._tmp_dir: Optional[str] = tmp_dir
        self._use_tmp: bool = use_tmp
        self._res_strings: Optional[dict[str, str]] = None

    async def _get_source_code(self) -> str:
        local_path = os.path.join(
            self._tmp_dir,
            self._refs.replace("/", "_"),
            os.path.basename(self._PERMISSION_STRING_MANIFEST.path)
        )
        if self._tmp_dir is not None and self._use_tmp and os.path.isfile(local_path):
            async with aiofiles.open(local_path, "r", encoding="utf-8") as f:
                return await f.read()
        else:
            res_strings = await self._source.get_source_code(self._PERMISSION_STRING_MANIFEST, self._refs)
            if self._tmp_dir is not None:
                if not os.path.isdir(os.path.dirname(local_path)):
                    os.makedirs(os.path.dirname(local_path))
                async with aiofiles.open(local_path, "w", encoding="utf-8") as f:
                    await f.write(res_strings)
            return res_strings

    async def _get_content(self) -> dict[str, str]:
        manifest = await self._get_source_code()
        tree: _Element = etree.fromstring(manifest.encode("utf-8"))
        return {
            string_element.attrib["name"]: string_element.text
            for string_element in tree.xpath("/resources/string[@name]")
        }

    async def get_res_strings(self) -> dict[str, str]:
        if self._res_strings is None:
            self._res_strings = await self._get_content()
        return self._res_strings

    async def get_string(self, res_id: str) -> Optional[str]:
        string_dict = await self.get_res_strings()
        if res_id.startswith(self._ID_START):
            key = res_id[len(self._ID_START):]
            if key in string_dict:
                return string_dict[key]
        raise ValueError(f"Unknown string res id: {res_id}")


class _AndroidCoreManifest:
    _PERMISSION_MANIFEST = AndroidSourceCodePath("platform/frameworks/base", "core/res/AndroidManifest.xml")

    def __init__(self, client: aiohttp.ClientSession, refs: str, tmp_dir: Optional[str], use_tmp: bool = False):
        self._source: AndroidGoogleSource = AndroidGoogleSource(client)
        self._refs = refs
        self._tmp_dir: Optional[str] = tmp_dir
        self._use_tmp: bool = use_tmp
        self._permission_groups: Optional[dict[str, _RawPermissionGroup]] = None
        self._permissions: Optional[dict[str, _RawPermission]] = None

    async def _get_source_code(self) -> str:
        local_path = os.path.join(
            self._tmp_dir,
            self._refs.replace("/", "_"),
            os.path.basename(self._PERMISSION_MANIFEST.path)
        )
        if self._tmp_dir is not None and self._use_tmp and os.path.isfile(local_path):
            async with aiofiles.open(local_path, "r", encoding="utf-8") as f:
                return await f.read()
        else:
            android_manifest = await self._source.get_source_code(self._PERMISSION_MANIFEST, self._refs)
            if self._tmp_dir is not None:
                if not os.path.isdir(os.path.dirname(local_path)):
                    os.makedirs(os.path.dirname(local_path))
                async with aiofiles.open(local_path, "w", encoding="utf-8") as f:
                    await f.write(android_manifest)
            return android_manifest

    async def _get_content(self) -> tuple[dict[str, _RawPermissionGroup], dict[str, _RawPermission]]:
        def _get_android_attrib(element, key: str) -> Optional[str]:
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
            else:
                return PermissionComment(
                    deprecated=False,
                    system_api=False,
                    test_api=False,
                    hide=False
                )

        manifest = await self._get_source_code()
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
                group=_get_android_attrib(e, "group"),
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

    def __init__(self, client: aiohttp.ClientSession, refs: str, permissions_tmp_dir: Optional[str] = None, use_tmp: bool = False):
        self._manifest: _AndroidCoreManifest = _AndroidCoreManifest(client, refs, permissions_tmp_dir, use_tmp)
        self._res_string: _AndroidCoreResString = _AndroidCoreResString(client, refs, permissions_tmp_dir, use_tmp)
        self._permissions: Optional[AndroidPermissions] = None

    async def _parse_raw_text(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        elif text.startswith("@"):
            return await self._res_string.get_string(text)
        else:
            return text

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
                group=permission_groups[i.group] if i.group is not None else None,
                protection_levels=i.get_protection_levels(),
                permission_flags=i.get_permission_flags(),
                priority=i.get_priority(),
                comment=i.comment
            )
            for k, i in (await self._manifest.get_permissions()).items()
        }
        return AndroidPermissions(permission_groups, permissions)

    async def get_permissions(self) -> AndroidPermissions:
        if self._permissions is None:
            self._permissions = await self._get_content()
        return self._permissions
