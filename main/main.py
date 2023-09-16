import asyncio
import http
import json
import os
from typing import Optional

import aiofiles.os
import aiohttp
import aioshutil
from tqdm import tqdm

from android_info.consts import ANDROID_MAIN_REFS
from android_info.permissions import AndroidFrameworkPermissions
from android_info.platforms import AndroidPlatformAPIPermissions, AndroidPlatformProviderAuthorities
from android_info.providers import AndroidProviderManifests
from android_info.utils import check_java_version
from android_info.versions import AndroidVersions, AndroidAPILevel, AndroidBuildTag

USE_TMP = False
REMOVE_OLD_OUTPUTS = True

DUMP_PERMISSIONS = True
DUMP_API_PERMISSION_MAPPINGS = True
DUMP_AUTHORITIES_CLASS = True
DUMP_CONTENT_PROVIDER_PERMISSIONS = True

MIN_JAVA_VERSION: str = "11"


def filter_available_api_levels(api_levels: list[AndroidAPILevel]) -> list[AndroidAPILevel]:
    return [i for i in api_levels if i.api >= 4 and i.api != 11 and i.api != 12 and i.api != 20]


async def dump_json(data: any, output_path: str):
    async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=4))


async def remove_old_ref_versions_tmp(refs: str, tmp_dir: str):
    if refs.startswith("refs"):
        return
    # noinspection PyBroadException
    try:
        current_tag = AndroidBuildTag.parse(refs)
    except:
        return
    version_tags = [i for i in os.listdir(tmp_dir) if not i.startswith("refs")]
    for t in version_tags:
        # noinspection PyBroadException
        try:
            tag = AndroidBuildTag.parse(t)
            if tag.version == current_tag.version and tag.revision < current_tag.revision:
                await aioshutil.rmtree(os.path.join(tmp_dir, tag.tag), ignore_errors=True)
        except:
            pass


async def dump_ref_permissions(client: aiohttp.ClientSession, output_dir: str, tmp_dir: str, refs_api: Optional[tuple[str, int]] = None):
    use_tmp = USE_TMP if refs_api is not None else False
    refs = refs_api[0] if refs_api is not None else ANDROID_MAIN_REFS
    if refs_api is not None:
        await remove_old_ref_versions_tmp(refs, tmp_dir)

    android_permissions = AndroidFrameworkPermissions(client, refs, tmp_dir, use_tmp)

    permissions = await android_permissions.get_permissions()

    tmp_file_name = f"permissions-{refs_api[1] if refs_api is not None else 'REL'}.json"

    await dump_json(
        data=permissions.to_dict(),
        output_path=os.path.join(output_dir, tmp_file_name)
    )

    del android_permissions


async def dump_permissions(client: aiohttp.ClientSession, output_dir: str, api_levels: list[AndroidAPILevel], android_versions: AndroidVersions):
    permissions_output_dir = os.path.join(output_dir, "permissions")
    if not await aiofiles.os.path.exists(permissions_output_dir):
        await aiofiles.os.makedirs(permissions_output_dir)

    tmp_dir = os.path.join("download_tmp", "permission")
    if not await aiofiles.os.path.exists(tmp_dir):
        await aiofiles.os.makedirs(tmp_dir)

    # Dump REL version
    await dump_ref_permissions(client, permissions_output_dir, tmp_dir)

    # Dump all API levels version
    filtered_api_levels = filter_available_api_levels(api_levels)
    with tqdm(desc="Permissions", total=len(filtered_api_levels)) as pbar:
        for api_level in filtered_api_levels:
            pbar.set_postfix_str(f"API {api_level.api}")
            for version in reversed(api_level.versions):
                latest_build_version = await android_versions.get_latest_build_version(version, False)
                if latest_build_version is not None:
                    try:
                        await dump_ref_permissions(client, permissions_output_dir, tmp_dir, (latest_build_version.tag, api_level.api))
                        break
                    except aiohttp.ClientResponseError as e:
                        if e.status != http.HTTPStatus.NOT_FOUND:
                            raise
            pbar.update(1)


async def dump_api_permission_mappings(client: aiohttp.ClientSession, platform_dir: str, sources_dir: str, output_dir: str, api_levels: list[AndroidAPILevel]):
    permissions_mapping_dir = os.path.join(output_dir, "permission_mappings")
    if not await aiofiles.os.path.exists(permissions_mapping_dir):
        await aiofiles.os.makedirs(permissions_mapping_dir)

    platform_api = AndroidPlatformAPIPermissions(client, platform_dir, sources_dir)

    # Only support API level >= 26
    filtered_api_levels = [i for i in filter_available_api_levels(api_levels) if i.api >= 26]
    with tqdm(desc="API-Permission Mappings", total=len(filtered_api_levels)) as pbar:
        for api_level in filtered_api_levels:
            pbar.set_postfix_str(f"API {api_level.api}")
            try:
                api_permissions = await platform_api.get_api_permissions(api_level.api)
            except aiohttp.ClientResponseError as e:
                if e.status != http.HTTPStatus.NOT_FOUND.value:
                    raise
            else:
                await dump_json(
                    data=[i.to_dict() for i in api_permissions],
                    output_path=os.path.join(permissions_mapping_dir, f"sdk-{api_level.api}.json")
                )
            pbar.update(1)


async def dump_content_provider_authority_classes(client: aiohttp.ClientSession, download_dir: str, output_dir: str, api_levels: list[AndroidAPILevel]):
    providers_dir = os.path.join(output_dir, "providers")
    if not await aiofiles.os.path.exists(providers_dir):
        await aiofiles.os.makedirs(providers_dir)

    latest_api = max(api_levels, key=lambda x: x.api).api
    provider_authorities = AndroidPlatformProviderAuthorities(client, download_dir)
    await provider_authorities.dump_platform_authority(latest_api, providers_dir, "authority_classes.json")


async def dump_content_provider_permissions(client: aiohttp.ClientSession, output_dir: str):
    tmp_dir = os.path.join("download_tmp", "manifest")
    if not await aiofiles.os.path.exists(tmp_dir):
        await aiofiles.os.makedirs(tmp_dir)

    providers_dir = os.path.join(output_dir, "providers")
    if not await aiofiles.os.path.exists(providers_dir):
        await aiofiles.os.makedirs(providers_dir)

    provider_manifests = AndroidProviderManifests(client, tmp_dir)

    providers = await provider_manifests.get_all_android_providers(ANDROID_MAIN_REFS, False)
    permission_providers = provider_manifests.filter_permission_providers(providers)

    await dump_json(
        data=[i.to_dict() for i in providers],
        output_path=os.path.join(providers_dir, "all_providers.json")
    )
    await dump_json(
        data=[i.to_dict() for i in permission_providers],
        output_path=os.path.join(providers_dir, "permission_providers.json")
    )


async def main():
    await check_java_version(MIN_JAVA_VERSION)

    output_dir = os.path.join(".", "outputs")
    if REMOVE_OLD_OUTPUTS:
        if await aiofiles.os.path.exists(output_dir):
            await aioshutil.rmtree(output_dir)
        await aiofiles.os.makedirs(output_dir)
    else:
        if not await aiofiles.os.path.exists(output_dir):
            await aiofiles.os.makedirs(output_dir)

    download_tmp_dir = os.path.join(".", "download_tmp")

    platform_download_dir = os.path.join(download_tmp_dir, "platform")
    if not await aiofiles.os.path.exists(platform_download_dir):
        await aiofiles.os.makedirs(platform_download_dir)

    sources_download_dir = os.path.join(download_tmp_dir, "source")
    if not await aiofiles.os.path.exists(sources_download_dir):
        await aiofiles.os.makedirs(sources_download_dir)

    async with aiohttp.ClientSession(raise_for_status=True) as client:
        print("Loading versions ...")

        android_versions = AndroidVersions(client)

        api_levels = await android_versions.list_api_levels()
        with open(os.path.join(output_dir, "api_levels.json"), "w", encoding="utf-8") as f:
            json.dump({i.api: i.to_dict() for i in api_levels}, f, ensure_ascii=False, indent=4)

        build_versions = await android_versions.list_build_versions()
        with open(os.path.join(output_dir, "build_versions.json"), "w", encoding="utf-8") as f:
            json.dump({i.tag: i.to_dict() for i in build_versions}, f, ensure_ascii=False, indent=4)

        if DUMP_PERMISSIONS:
            print()
            print("Loading permissions ...")
            await dump_permissions(client, output_dir, api_levels, android_versions)

        if DUMP_API_PERMISSION_MAPPINGS:
            print()
            print("Loading API-Permission mappings ...")
            await dump_api_permission_mappings(client, platform_download_dir, sources_download_dir, output_dir, api_levels)

        if DUMP_AUTHORITIES_CLASS:
            print()
            print("Loading ContentProvider authority classes ...")
            await dump_content_provider_authority_classes(client, platform_download_dir, output_dir, api_levels)

        if DUMP_CONTENT_PROVIDER_PERMISSIONS:
            print()
            print("Loading ContentProvider permissions ...")
            await dump_content_provider_permissions(client, output_dir)

    print("Done")


if __name__ == "__main__":
    looper = asyncio.get_event_loop()
    try:
        looper.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        if not looper.is_closed:
            looper.close()
