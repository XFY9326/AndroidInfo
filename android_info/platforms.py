import abc
import dataclasses
import os.path
import platform
import re
import zipfile
from functools import lru_cache
from io import BytesIO

import aiohttp
import dataclasses_json
from dataclasses_json import DataClassJsonMixin
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element

from .consts import JVM_BASIC_SIGNATURE_MAPPING
from .repository import AndroidRepository


@dataclasses.dataclass(frozen=True)
class _JvmAPI(abc.ABC):
    class_name: str

    @abc.abstractmethod
    def to_android_api(self) -> 'AndroidAPI':
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class _JvmMethod(_JvmAPI):
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

    def to_android_api(self) -> 'AndroidAPIMethod':
        return AndroidAPIMethod(
            class_name=self.class_name,
            name=self.name,
            signature=self.signature,
        )


@dataclasses.dataclass(frozen=True)
class _JvmField(_JvmAPI):
    name: str

    def __repr__(self) -> str:
        return f"{self.class_name} {self.name}"

    def to_android_api(self) -> 'AndroidAPIField':
        return AndroidAPIField(
            class_name=self.class_name,
            name=self.name,
        )


@dataclasses.dataclass(frozen=True)
class _JvmAPIPermission:
    api: _JvmAPI
    permissions: tuple[str]
    any_of: bool

    def to_android_api(self) -> 'AndroidAPIPermission':
        return AndroidAPIPermission(
            api=self.api.to_android_api(),
            permissions=self.permissions,
            any_of=self.any_of,
        )


@dataclasses.dataclass(frozen=True)
class AndroidAPI(DataClassJsonMixin):
    class_name: str
    name: str
    api_type: str = dataclasses.field(init=False, default="unknown", metadata=dataclasses_json.config(field_name="type"))

    @staticmethod
    def api_type_decoder(content: any) -> 'AndroidAPI':
        if isinstance(content, dict) and "type" in content:
            if content["type"] == "method":
                return AndroidAPIMethod.from_dict(content)
            elif content["type"] == "field":
                return AndroidAPIField.from_dict(content)
            elif content["type"] == "unknown":
                return AndroidAPI.from_dict(content)
        raise NotImplementedError(f"Unsupported api type: {content}")


@dataclasses.dataclass(frozen=True)
class AndroidAPIMethod(AndroidAPI, DataClassJsonMixin):
    signature: str
    api_type: str = dataclasses.field(init=False, default="method", metadata=dataclasses_json.config(field_name="type"))


@dataclasses.dataclass(frozen=True)
class AndroidAPIField(AndroidAPI, DataClassJsonMixin):
    api_type: str = dataclasses.field(init=False, default="field", metadata=dataclasses_json.config(field_name="type"))


@dataclasses.dataclass(frozen=True)
class AndroidAPIPermission(DataClassJsonMixin):
    api: AndroidAPI = dataclasses.field(metadata=dataclasses_json.config(decoder=AndroidAPI.api_type_decoder))
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

    def _build_android_api_permission(self, name: str, permissions: list[str], any_of: bool) -> _JvmAPIPermission:
        method_matcher = self._method_name_pattern.fullmatch(name)
        if method_matcher is None:
            field_matcher = self._field_name_pattern.fullmatch(name)
            if field_matcher is not None:
                return _JvmAPIPermission(
                    api=_JvmField(
                        class_name=field_matcher.group(1),
                        name=field_matcher.group(2),
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
            return _JvmAPIPermission(
                api=_JvmMethod(
                    class_name=method_matcher.group(1),
                    name=method_matcher.group(3),
                    args=tuple(method_args),
                    return_value=method_matcher.group(2),
                ),
                permissions=tuple(permissions),
                any_of=any_of
            )
        raise ValueError(f"Unknown jvm api format: {name}")

    def _extract_permission_annotations(self, xml_bytes: bytes) -> list[_JvmAPIPermission]:
        tree: _Element = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))
        method_elements: list[_Element] = tree.xpath(self._ANNOTATION_ITEM_XPATH)
        result: list[_JvmAPIPermission] = []
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
        result: set[_JvmAPIPermission] = set()
        with zipfile.ZipFile(platform_zip_path) as p_f:
            annotation_zip_file = next(filter(lambda x: self._annotation_pattern.fullmatch(x.filename), p_f.infolist()))
            with zipfile.ZipFile(BytesIO(p_f.read(annotation_zip_file))) as a_f:
                for annotation_file in a_f.infolist():
                    if os.path.basename(annotation_file.filename) == "annotations.xml":
                        xml_bytes = a_f.read(annotation_file.filename)
                        result.update(self._extract_permission_annotations(xml_bytes))
        return [i.to_android_api() for i in sorted(result, key=lambda x: repr(x))]
