import abc
import dataclasses
import os
import re
import zipfile
from functools import lru_cache
from io import BytesIO
from typing import Optional

import aiofiles.os
import aiohttp
import dataclasses_json
from dataclasses_json import DataClassJsonMixin
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element

from .consts import JVM_CONSTRUCTOR_NAME, JVM_CONSTRUCTOR_RETURN
from .repository import AndroidRepository
from .sources import AndroidSources
from .utils import run_commands, jvm_type_to_signature, get_short_class_name

_PLATFORM_TOOLS_JAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs", "platform_tools.jar")


@dataclasses.dataclass(frozen=True)
class _RawAPI(abc.ABC):
    class_name: str

    @abc.abstractmethod
    def to_android_api(self, type_name: Optional[str] = None) -> 'AndroidAPI':
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class _RawMethod(_RawAPI):
    name: str
    args: list[str]
    return_value: str

    def __hash__(self):
        return hash(self.name) + hash(self.return_value) + hash(tuple(self.args))

    @property
    def is_constructor(self) -> bool:
        return self.name == JVM_CONSTRUCTOR_NAME

    def __repr__(self) -> str:
        if self.is_constructor:
            constructor_name = get_short_class_name(self.class_name)
            return f"{self.class_name} {constructor_name}({', '.join(self.args)})"
        else:
            return f"{self.class_name} {self.return_value} {self.name}({', '.join(self.args)})"

    def _get_signature(self) -> str:
        args_signatures = [jvm_type_to_signature(i) for i in self.args]
        return_signature = jvm_type_to_signature(self.return_value)
        return f"({''.join(args_signatures)}){return_signature}"

    def _get_dalvik_descriptor(self) -> str:
        class_signature = jvm_type_to_signature(self.class_name)
        return f"{class_signature}->{self.name}{self._get_signature()}"

    def to_android_api(self, type_name: Optional[str] = None) -> 'AndroidAPIMethod':
        return AndroidAPIMethod(
            class_name=self.class_name,
            name=self.name,
            args=self.args,
            return_value=self.return_value,
            signature=self._get_signature(),
            dalvik_descriptor=self._get_dalvik_descriptor()
        )


@dataclasses.dataclass(frozen=True)
class _RawField(_RawAPI):
    name: str

    def __repr__(self) -> str:
        return f"{self.class_name} {self.name}"

    def _get_dalvik_descriptor(self, type_name: str) -> str:
        class_signature = jvm_type_to_signature(self.class_name)
        return f"{class_signature}->{self.name}:{jvm_type_to_signature(type_name)}"

    def to_android_api(self, type_name: Optional[str] = None) -> 'AndroidAPIField':
        assert type_name is not None, "Type name in field can't be None"
        return AndroidAPIField(
            class_name=self.class_name,
            name=self.name,
            field_type=type_name,
            signature=jvm_type_to_signature(type_name),
            dalvik_descriptor=self._get_dalvik_descriptor(type_name)
        )


@dataclasses.dataclass(frozen=True)
class _RawAPIPermissionGroup:
    conditional: bool
    value: Optional[str]
    all_of: Optional[list[str]]
    any_of: Optional[list[str]]

    def __hash__(self):
        hash_code = hash(self.value) if self.value is not None else 0
        hash_code += hash(tuple(sorted(self.all_of))) if self.all_of is not None else 0
        hash_code += hash(tuple(sorted(self.any_of))) if self.any_of is not None else 0
        hash_code += hash(self.conditional)
        return hash_code

    def to_android_api(self) -> 'APIPermissionGroup':
        return APIPermissionGroup(
            conditional=self.conditional,
            value=self.value,
            all_of=self.all_of,
            any_of=self.any_of
        )


@dataclasses.dataclass(frozen=True)
class _RawAPIPermission:
    api: _RawAPI
    permission_groups: list[_RawAPIPermissionGroup]

    def to_android_api(self, type_name: Optional[str] = None) -> 'AndroidAPIPermission':
        return AndroidAPIPermission(
            api=self.api.to_android_api(type_name),
            permission_groups=[i.to_android_api() for i in self.permission_groups],
        )

    def __hash__(self):
        return hash(self.api) + hash(tuple(self.permission_groups))


@dataclasses.dataclass(frozen=True)
class AndroidAPI(abc.ABC):
    class_name: str
    name: str
    signature: str
    dalvik_descriptor: str
    api_type: str = dataclasses.field(init=False, default="unknown")

    @staticmethod
    def api_type_decoder(content: any) -> 'AndroidAPI':
        if isinstance(content, dict) and "type" in content:
            if content["type"] == "method":
                return AndroidAPIMethod.from_dict(content)
            elif content["type"] == "field":
                return AndroidAPIField.from_dict(content)
        raise NotImplementedError(f"Unsupported api type: {content}")


@dataclasses.dataclass(frozen=True)
class AndroidAPIMethod(AndroidAPI, DataClassJsonMixin):
    args: list[str]
    return_value: str
    api_type: str = dataclasses.field(init=False, default="method", metadata=dataclasses_json.config(field_name="type"))


@dataclasses.dataclass(frozen=True)
class AndroidAPIField(AndroidAPI, DataClassJsonMixin):
    field_type: str
    api_type: str = dataclasses.field(init=False, default="field", metadata=dataclasses_json.config(field_name="type"))


@dataclasses.dataclass(frozen=True)
class APIPermissionGroup(DataClassJsonMixin):
    conditional: bool
    value: Optional[str] = dataclasses.field(default=None, metadata=dataclasses_json.config(exclude=lambda x: x is None))
    all_of: Optional[list[str]] = dataclasses.field(default=None, metadata=dataclasses_json.config(exclude=lambda x: x is None))
    any_of: Optional[list[str]] = dataclasses.field(default=None, metadata=dataclasses_json.config(exclude=lambda x: x is None))


@dataclasses.dataclass(frozen=True)
class AndroidAPIPermission(DataClassJsonMixin):
    api: AndroidAPI = dataclasses.field(metadata=dataclasses_json.config(decoder=AndroidAPI.api_type_decoder))
    permission_groups: list[APIPermissionGroup]


class AndroidPlatform:
    # Stable channel
    _DEFAULT_CHANNEL = "channel-0"

    def __init__(self, client: aiohttp.ClientSession, download_dir: str):
        self._repo: AndroidRepository = AndroidRepository(client)
        self._download_dir: str = download_dir

    @lru_cache
    async def _get_platform_zip_archive(self, api: int):
        pkg_dict = await self._repo.get_latest_package(f"platforms;android-{api}", self._DEFAULT_CHANNEL)
        return self._repo.get_best_archive_url(pkg_dict)

    async def load_platform_zip(self, api: int) -> str:
        archive_name = await self._get_platform_zip_archive(api)
        local_path = os.path.join(self._download_dir, archive_name)
        if os.path.isfile(local_path):
            return local_path
        else:
            return await self._repo.download_archive(archive_name, self._download_dir)


class AndroidPlatformProviderAuthorities:
    _OUTPUT_DIVIDER = " -> "

    def __init__(self, client: aiohttp.ClientSession, download_dir: str):
        self._platform: AndroidPlatform = AndroidPlatform(client, download_dir)

    async def dump_platform_authority(self, api: int, output_dir: str, output_file_name: str):
        zip_path = await self._platform.load_platform_zip(api)
        zip_args = f"\"{zip_path}\""
        code, output, output_error = await run_commands(
            f"java -jar \"{_PLATFORM_TOOLS_JAR_PATH}\" authority-classes -o \"{output_dir}\" {zip_args}"
        )
        if code == 0:
            output_text: str = output.decode()
            for line in output_text.splitlines(keepends=False):
                if self._OUTPUT_DIVIDER in line:
                    zip_path, output_path = line.split(self._OUTPUT_DIVIDER)
                    output_path: str = os.path.abspath(os.path.normpath(output_path.strip()))
                    await aiofiles.os.rename(output_path, os.path.join(output_dir, output_file_name))
        else:
            err_msg = "\n".join([
                line
                for i, line in enumerate(output_error.decode().splitlines(keepends=False))
                if i != 0 and len(line.strip()) > 0
            ])
            raise ValueError(f"Platform authorities dump failed!\n{err_msg}")


class AndroidPlatformAPIPermissions:
    _OUTPUT_DIVIDER = " -> "
    _CLASS_EXT = ".class"
    _ANNOTATION_ITEM_XPATH = "/root/item[annotation[contains(@name,'RequiresPermission')]]"
    _ANNOTATION_ITEM_ANNOTATION_XPATH = "annotation[contains(@name,'RequiresPermission') and val]"
    _ANNOTATION_ITEM_ANNOTATION_VAL_PERMISSION_XPATH = "val[(@name='value' or @name='allOf' or @name='anyOf') and @val]"
    _ANNOTATION_ITEM_ANNOTATION_VAL_CONDITIONAL_XPATH = "val[@name='conditional' and @val='true']"

    def __init__(self, client: aiohttp.ClientSession, platform_dir: str, sources_dir: str):
        self._platform: AndroidPlatform = AndroidPlatform(client, platform_dir)
        self._source: AndroidSources = AndroidSources(client, sources_dir)
        self._annotation_pattern: re.Pattern = re.compile(r"android-.*/data/annotations.zip")
        self._android_jar_pattern: re.Pattern = re.compile(r"android-.*/android.jar")
        self._method_name_pattern: re.Pattern = re.compile(r"^(.*?)\s(.*?)\s(.*?)\((.*?)\)\s?(\d+)?$")
        self._constructor_name_pattern: re.Pattern = re.compile(r"^(.*?)\s(.*?)\((.*?)\)\s?(\d+)?$")
        self._field_name_pattern: re.Pattern = re.compile(r"^(.*?)\s(.*?)$")

    async def _get_field_types(
            self,
            platform_zip_path: str,
            sources_zip_path: str,
            raw_result: set[_RawAPIPermission]
    ) -> dict[_RawAPIPermission, str]:
        field_apis = {f"{i.api.class_name}:{i.api.name}": i for i in raw_result if isinstance(i.api, _RawField)}
        field_args = " ".join(field_apis.keys())
        code, output, output_error = await run_commands(
            f"java -jar \"{_PLATFORM_TOOLS_JAR_PATH}\" field-type -p \"{platform_zip_path}\" -s \"{sources_zip_path}\" {field_args}"
        )
        if code == 0:
            output_text: str = output.decode()
            result: dict[_RawAPIPermission, str] = {}
            for line in output_text.splitlines(keepends=False):
                if self._OUTPUT_DIVIDER in line:
                    field_api, field_type = line.split(self._OUTPUT_DIVIDER)
                    result[field_apis[field_api.strip()]] = field_type.strip()
            return result
        else:
            err_msg = "\n".join([
                line
                for i, line in enumerate(output_error.decode().splitlines(keepends=False))
                if len(line.strip()) > 0
            ])
            raise ValueError(f"Platform field type dump failed!\n{err_msg}")

    @staticmethod
    def _fix_class_name(class_name: str, class_names: set[str]) -> str:
        if class_name in class_names:
            return class_name
        elif "." in class_name:
            out_class, inner_class = class_name.rsplit(".", 1)
            return AndroidPlatformAPIPermissions._fix_class_name(out_class + "$" + inner_class, class_names)
        else:
            raise ValueError(f"Class {class_name.replace('$', '.')} not found in all classes")

    @staticmethod
    def _parse_args_list_str(text: str) -> list[str]:
        return [
            i.strip()
            for i in (text.split(",") if "," in text else [text])
            if len(i.strip()) > 0
        ]

    def _build_android_api_permission(self, name: str, permissions: list[_RawAPIPermissionGroup], class_names: set[str]) -> _RawAPIPermission:
        method_matcher = self._method_name_pattern.fullmatch(name)
        if method_matcher is None:
            constructor_matcher = self._constructor_name_pattern.fullmatch(name)
            if constructor_matcher is None:
                field_matcher = self._field_name_pattern.fullmatch(name)
                if field_matcher is not None:
                    return _RawAPIPermission(
                        api=_RawField(
                            class_name=self._fix_class_name(field_matcher.group(1), class_names),
                            name=field_matcher.group(2),
                        ),
                        permission_groups=permissions
                    )
            else:
                constructor_args = self._parse_args_list_str(constructor_matcher.group(3))
                class_name = self._fix_class_name(constructor_matcher.group(1), class_names)
                constructor_name = constructor_matcher.group(2)
                if class_name.endswith(constructor_name):
                    return _RawAPIPermission(
                        api=_RawMethod(
                            class_name=class_name,
                            name=JVM_CONSTRUCTOR_NAME,
                            args=constructor_args,
                            return_value=JVM_CONSTRUCTOR_RETURN,
                        ),
                        permission_groups=permissions
                    )
                else:
                    raise ValueError(f"Wrong constructor text: {name}")
        elif method_matcher.group(5) is None:
            method_args = self._parse_args_list_str(method_matcher.group(4))
            return _RawAPIPermission(
                api=_RawMethod(
                    class_name=self._fix_class_name(method_matcher.group(1), class_names),
                    name=method_matcher.group(3),
                    args=method_args,
                    return_value=method_matcher.group(2),
                ),
                permission_groups=permissions
            )
        raise ValueError(f"Unknown jvm api format: {name}")

    def _extract_permission_annotations(self, xml_bytes: bytes, class_names: set[str]) -> list[_RawAPIPermission]:
        tree: _Element = etree.fromstring(xml_bytes, parser=etree.XMLParser(recover=True))
        method_elements: list[_Element] = tree.xpath(self._ANNOTATION_ITEM_XPATH)
        result: list[_RawAPIPermission] = []
        if method_elements is not None:
            for method_element in method_elements:
                method_name = method_element.attrib["name"]
                annotation_elements: list[_Element] = method_element.xpath(self._ANNOTATION_ITEM_ANNOTATION_XPATH)
                if annotation_elements is not None and len(annotation_elements) > 0:
                    api_permission_groups = []
                    for annotation_element in annotation_elements:
                        val_permission_elements: list[_Element] = annotation_element.xpath(self._ANNOTATION_ITEM_ANNOTATION_VAL_PERMISSION_XPATH)
                        conditional_elements = annotation_element.xpath(self._ANNOTATION_ITEM_ANNOTATION_VAL_CONDITIONAL_XPATH)
                        conditional = conditional_elements is not None and len(conditional_elements) > 0
                        if val_permission_elements is not None:
                            value: Optional[str] = None
                            all_of: Optional[list[str]] = None
                            any_of: Optional[list[str]] = None

                            for val_permission_element in val_permission_elements:
                                permissions_text: str = val_permission_element.attrib["val"].strip("{} ")
                                permissions = [
                                    p.strip().strip("\"")
                                    for p in (permissions_text.split(",") if "," in permissions_text else [permissions_text])
                                ]
                                group_type = val_permission_element.attrib["name"]
                                if group_type == "allOf":
                                    all_of = permissions
                                elif group_type == "anyOf":
                                    any_of = permissions
                                elif group_type == "value":
                                    value = permissions[0]

                            api_permission_groups.append(_RawAPIPermissionGroup(
                                conditional=conditional,
                                value=value,
                                all_of=all_of,
                                any_of=any_of
                            ))
                    api_permission = self._build_android_api_permission(method_name, api_permission_groups, class_names)
                    result.append(api_permission)
        return result

    async def get_api_permissions(self, api: int) -> list[AndroidAPIPermission]:
        if api < 26:
            raise ValueError("Only support API level >= 26")
        platform_zip_path = await self._platform.load_platform_zip(api)
        sources_zip_path = await self._source.load_sources_zip(api)
        result: set[_RawAPIPermission] = set()
        with zipfile.ZipFile(platform_zip_path) as p_f:
            android_jar_file = next(filter(lambda x: self._android_jar_pattern.fullmatch(x.filename), p_f.infolist()))
            annotation_zip_file = next(filter(lambda x: self._annotation_pattern.fullmatch(x.filename), p_f.infolist()))
            with zipfile.ZipFile(BytesIO(p_f.read(android_jar_file))) as a_f:
                class_names = set([
                    i.filename.replace("/", ".")[:-len(self._CLASS_EXT)]
                    for i in a_f.infolist()
                    if not i.is_dir() and i.filename.endswith(self._CLASS_EXT)
                ])
            with zipfile.ZipFile(BytesIO(p_f.read(annotation_zip_file))) as a_f:
                for annotation_file in a_f.infolist():
                    if not annotation_file.is_dir() and os.path.basename(annotation_file.filename) == "annotations.xml":
                        xml_bytes = a_f.read(annotation_file)
                        result.update(self._extract_permission_annotations(xml_bytes, class_names))
        field_types = await self._get_field_types(platform_zip_path, sources_zip_path, result)
        return [
            i.to_android_api(field_types[i] if isinstance(i.api, _RawField) else None)
            for i in sorted(result, key=lambda x: repr(x))
        ]
