import asyncio
import dataclasses
import http
import os
import re

import aiofiles
import aiofiles.os
import aiohttp
from dataclasses_json import DataClassJsonMixin
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element
from tqdm.asyncio import tqdm

from .consts import ANDROID_MANIFEST_NS, SOURCE_CODE_QUERY_EXCLUDE_PATH
from .source_code import AndroidSourceCodePath, AndroidSourceCodeQuery
from .utils import android_attrib


@dataclasses.dataclass(frozen=True)
class AndroidUriPermission(DataClassJsonMixin):
    type: str
    path: str


@dataclasses.dataclass(frozen=True)
class AndroidProvider(DataClassJsonMixin):
    package: str
    name: str
    authorities: list[str]
    exported: bool
    read_permission: str | None
    write_permission: str | None
    has_uri_permission: bool
    grant_uri_permissions: list[AndroidUriPermission]

    @property
    def all_permissions(self) -> list[str]:
        result = []
        if self.read_permission is not None:
            result.append(self.read_permission)
        if self.write_permission is not None:
            result.append(self.write_permission)
        return result

    def need_permission(self) -> bool:
        return self.read_permission is not None or self.write_permission is not None

    def __hash__(self) -> int:
        return hash(frozenset(self.authorities))


class AndroidProviderManifests:
    _PROVIDER_XPATH = "//application/provider[@android:authorities and (@android:exported='true' or @android:grantUriPermissions='true')]"
    _APPLICATION_ID_PATTERN = re.compile(r"applicationId\s*(?:=\s*)?(['\"])(.*?)\1")

    _QUERY_PROJECT = "android"
    # noinspection SpellCheckingInspection
    _QUERY_REPO = "platform/superproject/main"
    # noinspection SpellCheckingInspection
    _QUERY_STRING = "lang:xml file:AndroidManifest.xml " + \
                    "content:<provider content:android\\:authorities " + \
                    "(content:android\\:exported=\"true\" OR content:android\\:grantUriPermissions=\"true\") " + \
                    SOURCE_CODE_QUERY_EXCLUDE_PATH

    _REQUEST_DELAY = 1

    def __init__(self, client: aiohttp.ClientSession, manifest_tmp_dir: str | None = None):
        self._query: AndroidSourceCodeQuery = AndroidSourceCodeQuery(client)
        self._manifest_tmp_dir: str | None = manifest_tmp_dir
        self._query_config: dict = self._query.get_query_config(
            query_string=self._QUERY_STRING,
            project=self._QUERY_PROJECT,
            repository=self._QUERY_REPO
        )

    async def get_latest_provider_manifest_path(self) -> dict[str, list[AndroidSourceCodePath]]:
        query_results = await self._query.query_pages(self._query_config)
        path_results = await self._query.extract_source_code_path(query_results)
        path_results = set(path_results)
        result: dict[str, list[AndroidSourceCodePath]] = {}
        for path in path_results:
            result.setdefault(path.project, []).append(path)
        return result

    def _get_manifest_tmp_path(self, code_path: AndroidSourceCodePath, refs: str) -> str:
        return os.path.join(self._manifest_tmp_dir, refs.replace("/", "_"), code_path.full_path)

    def _has_manifest_tmp(self, code_path: AndroidSourceCodePath, refs: str) -> bool:
        if self._manifest_tmp_dir is None:
            return False
        else:
            return os.path.isfile(self._get_manifest_tmp_path(code_path, refs))

    async def _get_manifest_source_code(self, code_path: AndroidSourceCodePath, refs: str, load_cache: bool = False) -> str:
        local_path = self._get_manifest_tmp_path(code_path, refs)
        if load_cache and self._manifest_tmp_dir is not None and os.path.isfile(local_path):
            async with aiofiles.open(local_path, "r", encoding="utf-8") as f:
                content = await f.read()
        else:
            content = await (await self._query.get_source()).get_source_code(code_path, refs)
            if self._manifest_tmp_dir is not None:
                await aiofiles.os.makedirs(os.path.dirname(local_path), exist_ok=True)
                async with aiofiles.open(local_path, "w", encoding="utf-8") as f:
                    await f.write(content)
        return content

    async def _try_get_package_from_gradle(self, manifest_path: AndroidSourceCodePath, refs: str, load_cache: bool = False):
        app_path = os.path.dirname(os.path.dirname(os.path.dirname(manifest_path.path)))
        possible_build_gradle_paths: list[AndroidSourceCodePath] = [
            AndroidSourceCodePath(
                project=manifest_path.project,
                path=f"{app_path}/build.gradle"
            ),
            AndroidSourceCodePath(
                project=manifest_path.project,
                path=f"{app_path}/build.gradle.kts"
            )
        ]
        gradle_path: AndroidSourceCodePath | None = None
        gradle_content: str | None = None
        for possible_code_path in possible_build_gradle_paths:
            # noinspection PyBroadException
            try:
                gradle_content = await self._get_manifest_source_code(possible_code_path, refs, load_cache)
                gradle_path = possible_code_path
                break
            except aiohttp.ClientResponseError as e:
                if e.status == http.HTTPStatus.NOT_FOUND:
                    continue
                else:
                    raise RuntimeError(f"Gradle content {possible_code_path} load failed: {e}")
        if gradle_content is None:
            raise FileNotFoundError(f"Failed to get gradle content for manifest: {manifest_path}")

        match = re.search(self._APPLICATION_ID_PATTERN, gradle_content)
        if match:
            return match.group(2)
        else:
            raise ValueError(f"Can't get package from build gradle file: {gradle_path}")

    async def get_providers_from_manifest(self, code_path: AndroidSourceCodePath, refs: str, load_cache: bool = False) -> list[AndroidProvider]:
        manifest_content = await self._get_manifest_source_code(code_path, refs, load_cache)

        def _get_android_attr(element, name: str, default: str) -> str:
            if android_attrib(name) in element.attrib:
                return element.attrib[android_attrib(name)]
            else:
                return default

        def _get_uri_permission_path(element) -> list[AndroidUriPermission]:
            uri_permission_result: list[AndroidUriPermission] = []
            for uri_element in element.xpath("grant-uri-permission", namespaces=ANDROID_MANIFEST_NS):
                for name in ["path", "pathPrefix", "pathPattern"]:
                    if android_attrib(name) in uri_element.attrib:
                        uri_permission_result.append(AndroidUriPermission(name, uri_element.attrib[android_attrib(name)]))
                        break
            return uri_permission_result

        def _fix_pkg_or_app_name(package: str, content: str) -> str:
            return content.replace("${packageName}", package).replace("${applicationId}", package)

        def _fix_name(package: str, name: str) -> str:
            if name.startswith("."):
                return package + name
            elif "." not in name:
                return package + "." + name
            else:
                return name

        def _transform_authorities(package: str, authorities: str) -> list[str]:
            if ";" in authorities:
                return [_fix_pkg_or_app_name(package, i) for i in authorities.split(";")]
            else:
                return [_fix_pkg_or_app_name(package, authorities)]

        def _convert_bool(text: str) -> bool:
            if text == "true":
                return True
            elif text == "false":
                return False
            else:
                raise ValueError(f"Unknown boolean string: {text}")

        tree: _Element = etree.fromstring(manifest_content.encode("utf-8"))
        providers = tree.xpath(
            AndroidProviderManifests._PROVIDER_XPATH,
            namespaces=ANDROID_MANIFEST_NS
        )

        if "package" in tree.attrib:
            package_name = tree.attrib["package"]
        else:
            package_name = await self._try_get_package_from_gradle(code_path, refs, load_cache)

        result: list[AndroidProvider] = []
        for provider in providers:
            read_permission: str | None = None
            write_permission: str | None = None

            if android_attrib("permission") in provider.attrib:
                read_permission = provider.attrib[android_attrib("permission")]
                write_permission = read_permission
            if android_attrib("readPermission") in provider.attrib:
                read_permission = provider.attrib[android_attrib("readPermission")]
            if android_attrib("writePermission") in provider.attrib:
                write_permission = provider.attrib[android_attrib("writePermission")]

            result.append(
                AndroidProvider(
                    package=package_name,
                    name=_fix_name(package_name, provider.attrib[android_attrib("name")]),
                    authorities=_transform_authorities(package_name, provider.attrib[android_attrib("authorities")]),
                    exported=_convert_bool(_get_android_attr(provider, "exported", "false")),
                    read_permission=read_permission,
                    write_permission=write_permission,
                    has_uri_permission=_convert_bool(_get_android_attr(provider, "grantUriPermissions", "false")),
                    grant_uri_permissions=_get_uri_permission_path(provider)
                )
            )
        return result

    async def get_all_android_providers(self, refs: str, load_cache: bool = False) -> list[AndroidProvider]:
        async def _task(is_last: bool, project: str, provider_path: AndroidSourceCodePath) -> list[AndroidProvider]:
            has_cache = load_cache and self._has_manifest_tmp(provider_path, refs)
            if not has_cache and not await (await self._query.get_source()).exists(project, refs):
                await asyncio.sleep(self._REQUEST_DELAY / 2)
                return []
            fetch_success = False
            while not fetch_success:
                try:
                    providers = await self.get_providers_from_manifest(provider_path, refs, load_cache)
                    fetch_success = True
                    return providers
                except aiohttp.ClientResponseError as e:
                    if e.status == http.HTTPStatus.TOO_MANY_REQUESTS:
                        await asyncio.sleep(20)
                    elif e.status == http.HTTPStatus.NOT_FOUND:
                        fetch_success = True
                    else:
                        raise
                if not has_cache and not is_last:
                    await asyncio.sleep(self._REQUEST_DELAY)
            return []

        provider_path_dict = await self.get_latest_provider_manifest_path()
        result: set[AndroidProvider] = set()
        tasks = [
            asyncio.ensure_future(_task(i == len(provider_path_list) - 1, project, provider_path))
            for project, provider_path_list in provider_path_dict.items()
            for i, provider_path in enumerate(provider_path_list)
        ]
        for task in tqdm.as_completed(tasks, desc="Fetching providers"):
            result.update(await task)
        return sorted(result, key=lambda x: (x.package, x.name))

    @staticmethod
    def filter_permission_providers(providers: list[AndroidProvider]) -> list[AndroidProvider]:
        return [p for p in providers if p.need_permission()]
