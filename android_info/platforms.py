import abc
import os.path
import platform
import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO

import aiohttp
from dataclasses_json import DataClassJsonMixin
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element

from .consts import JVM_BASIC_SIGNATURE_MAPPING
from .repository import AndroidRepository


@dataclass(frozen=True)
class JvmAPI(abc.ABC):
    class_name: str


@dataclass(frozen=True)
class JvmMethod(JvmAPI, DataClassJsonMixin):
    name: str
    args: tuple[str]
    return_value: str

    def __repr__(self) -> str:
        return f"{self.class_name} {self.return_value} {self.name} ({', '.join(self.args)})"

    @staticmethod
    @lru_cache
    def _jvm_type_to_signature(type_name: str) -> str:
        is_array = "[]" in type_name
        # noinspection RegExpRedundantEscape
        type_name = re.sub(r"<.*>|\[\]", "", type_name)
        if type_name in JVM_BASIC_SIGNATURE_MAPPING:
            signature_name = JVM_BASIC_SIGNATURE_MAPPING[type_name]
        else:
            signature_name = f"L{type_name.replace('.', '/')};"
        if is_array:
            signature_name = "[" + signature_name
        return signature_name

    @property
    def signature(self) -> str:
        args_signatures = [self._jvm_type_to_signature(i) for i in self.args]
        return_signature = self._jvm_type_to_signature(self.return_value)
        return f"({''.join(args_signatures)}){return_signature}"


@dataclass(frozen=True)
class JvmField(JvmAPI, DataClassJsonMixin):
    field_name: str

    def __repr__(self) -> str:
        return f"{self.class_name} {self.field_name}"


@dataclass(frozen=True)
class AndroidAPIPermission(DataClassJsonMixin):
    api: JvmAPI
    permissions: tuple[str]
    any_of: bool


@dataclass(frozen=True)
class AndroidMethodPermission(DataClassJsonMixin):
    class_name: str
    method_name: str
    method_signature: str
    permissions: tuple[str]
    any_of: bool


class AndroidPlatformAPIPermissions:
    # Stable channel
    _DEFAULT_CHANNEL = "channel-0"

    _ANNOTATION_ITEM_XPATH = "/root/item[annotation[contains(@name,'RequiresPermission')]]"
    _ANNOTATION_ITEM_VAL_XPATH = "annotation[contains(@name,'RequiresPermission')]/val"

    def __init__(self, client: aiohttp.ClientSession, platform_tmp_dir: str):
        self._repo: AndroidRepository = AndroidRepository(client)
        self._platform_tmp_dir: str = platform_tmp_dir
        self._annotation_pattern: re.Pattern = re.compile(r"android-.*/data/annotations.zip")
        self._method_name_pattern: re.Pattern = re.compile(r"^(.*?)\s(.*?)\s(.*?)\((.*?)\)\s?(\d+)?$")
        self._field_name_pattern: re.Pattern = re.compile(r"^(.*?)\s(.*?)$")

    @lru_cache
    async def _get_platform_zip_archive(self, api: int):
        pkg = await self._repo.get_latest_package(f"platforms;android-{api}", self._DEFAULT_CHANNEL)
        archives = pkg["archives"]["archive"]
        if isinstance(archives, dict):
            return archives["complete"]["url"]
        elif isinstance(archives, list):
            if len(archives) == 1:
                return archives[0]["complete"]["url"]
            elif len(archives) == 0:
                raise ValueError(f"No archives available!")
            else:
                os_name = platform.system()
                if os_name == "Windows":
                    return next(filter(lambda x: x["host-os"] == "windows", archives))["complete"]["url"]
                elif os_name == "Linux":
                    return next(filter(lambda x: x["host-os"] == "linux", archives))["complete"]["url"]
                elif os_name == "Darwin":
                    return next(filter(lambda x: x["host-os"] == "macosx", archives))["complete"]["url"]
                else:
                    raise ValueError(f"Unsupported system: {os_name}")
        else:
            raise ValueError(f"Unknown archives format: {archives}")

    async def _download_platform_zip(self, archive_name: str) -> str:
        return await self._repo.download_archive(archive_name, self._platform_tmp_dir)

    async def _get_platform_zip_path(self, api: int) -> str:
        archive_name = await self._get_platform_zip_archive(api)
        local_path = os.path.join(self._platform_tmp_dir, archive_name)
        if os.path.isfile(local_path):
            return local_path
        else:
            return await self._download_platform_zip(archive_name)

    def _build_android_api_permission(self, name: str, permissions: list[str], any_of: bool) -> AndroidAPIPermission:
        method_matcher = self._method_name_pattern.fullmatch(name)
        if method_matcher is None:
            field_matcher = self._field_name_pattern.fullmatch(name)
            if field_matcher is not None:
                return AndroidAPIPermission(
                    api=JvmField(
                        class_name=field_matcher.group(1),
                        field_name=field_matcher.group(2),
                    ),
                    permissions=tuple(permissions),
                    any_of=any_of
                )
        elif method_matcher.group(5) is None:
            method_args = [
                i.strip()
                for i in (method_matcher.group(4).split(",") if "," in method_matcher.group(4) else [method_matcher.group(4)])
                if len(i.strip()) > 0
            ]
            return AndroidAPIPermission(
                api=JvmMethod(
                    class_name=method_matcher.group(1),
                    name=method_matcher.group(3),
                    args=tuple(method_args),
                    return_value=method_matcher.group(2),
                ),
                permissions=tuple(permissions),
                any_of=any_of
            )
        raise ValueError(f"Unknown jvm api format: {name}")

    def _extract_permission_annotations(self, xml_bytes: bytes) -> list[AndroidAPIPermission]:
        tree: _Element = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))
        method_elements: list[_Element] = tree.xpath(self._ANNOTATION_ITEM_XPATH)
        result: list[AndroidAPIPermission] = []
        if method_elements is not None:
            for method_element in method_elements:
                method_name = method_element.attrib["name"]
                annotation_elements: list[_Element] = method_element.xpath(self._ANNOTATION_ITEM_VAL_XPATH)
                if annotation_elements is not None and len(annotation_elements) > 0:
                    permissions_text: str = annotation_elements[0].attrib["val"].strip("{} ")
                    permissions = [
                        p.strip().strip("\"")
                        for p in (permissions_text.split(",") if "," in permissions_text else [permissions_text])
                    ]
                    any_of = annotation_elements[0].attrib["name"] == "anyOf"
                    api_permission = self._build_android_api_permission(method_name, permissions, any_of)
                    result.append(api_permission)
        return result

    async def get_api_permissions(self, api: int) -> list[AndroidAPIPermission]:
        if api < 26:
            raise ValueError("Only support API level >= 26")
        platform_zip_path = await self._get_platform_zip_path(api)
        result: set[AndroidAPIPermission] = set()
        with zipfile.ZipFile(platform_zip_path) as p_f:
            annotation_zip_file = next(filter(lambda x: self._annotation_pattern.fullmatch(x.filename), p_f.infolist()))
            with zipfile.ZipFile(BytesIO(p_f.read(annotation_zip_file))) as a_f:
                for annotation_file in a_f.infolist():
                    if os.path.basename(annotation_file.filename) == "annotations.xml":
                        xml_bytes = a_f.read(annotation_file.filename)
                        result.update(self._extract_permission_annotations(xml_bytes))
        return sorted(result, key=lambda x: repr(x))

    async def get_method_permissions(self, api: int) -> list[AndroidMethodPermission]:
        api_permissions = await self.get_api_permissions(api)
        return [
            AndroidMethodPermission(
                class_name=i.api.class_name,
                method_name=i.api.name,
                method_signature=i.api.signature,
                permissions=i.permissions,
                any_of=i.any_of
            )
            for i in api_permissions
            if isinstance(i.api, JvmMethod)
        ]
