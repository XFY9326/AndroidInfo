import os
from typing import Optional

import aiofiles
import aiohttp
import aioshutil
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element

from android_info.utils import xml_to_dict

# noinspection HttpUrlsUsage
ANDROID_REPO_NS: dict[str, str] = {
    "common": "http://schemas.android.com/repository/android/common/02",
    "generic": "http://schemas.android.com/repository/android/generic/02",
    "sdk": "http://schemas.android.com/sdk/android/repo/repository2/03",
    "sdk-common": "http://schemas.android.com/sdk/android/repo/common/03",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


class AndroidRepository:
    _REPO_URL = "https://dl.google.com/android/repository/repository2-3.xml"
    _DL_URL = "https://dl.google.com/android/repository"

    _DOWNLOAD_CHUNK_SIZE = 1024 * 1024 * 8

    def __init__(self, client: aiohttp.ClientSession):
        self._client = client
        self._tree: Optional[_Element] = None

    async def _prepare(self):
        if self._tree is None:
            async with self._client.get(self._REPO_URL) as response:
                repo_text = await response.text()
            self._tree = etree.fromstring(repo_text.encode("utf-8"))
        assert self._tree is not None

    async def get_license(self) -> dict[str, str]:
        await self._prepare()
        return {
            e.attrib["id"]: e.text
            for e in self._tree.xpath("/sdk:sdk-repository/license", namespaces=ANDROID_REPO_NS)
        }

    async def get_channels(self) -> dict[str, str]:
        await self._prepare()
        return {
            e.attrib["id"]: e.text
            for e in self._tree.xpath("/sdk:sdk-repository/channel", namespaces=ANDROID_REPO_NS)
        }

    async def _get_package_elements(self, path: str) -> list[_Element]:
        await self._prepare()
        pkg_elements: list[_Element] = self._tree.xpath(
            f"/sdk:sdk-repository/remotePackage[@path='{path}']",
            namespaces=ANDROID_REPO_NS
        )
        if pkg_elements is not None:
            return pkg_elements
        raise ValueError(f"Package {path} not found!")

    async def list_packages(self, category: Optional[str] = None) -> list[str]:
        await self._prepare()
        if category is None:
            xpath = "/sdk:sdk-repository/remotePackage"
        else:
            xpath = f"/sdk:sdk-repository/remotePackage[starts-with(@path,'{category};') or @path='{category}']"
        return sorted(set([
            e.attrib["path"]
            for e in self._tree.xpath(xpath, namespaces=ANDROID_REPO_NS)
        ]))

    @staticmethod
    def revision_dict_to_list(revision: dict) -> list[int]:
        return [
            int(revision["major"]) if "major" in revision else 0,
            int(revision["minor"]) if "minor" in revision else 0,
            int(revision["micro"]) if "micro" in revision else 0,
        ]

    @staticmethod
    def _get_archive_dl_url(archive_name: str) -> str:
        return f"{AndroidRepository._DL_URL}/{archive_name}"

    async def download_archive(self, archive_name: str, output_dir: Optional[str] = None) -> str:
        if output_dir is None:
            output_dir = "."
        if not os.path.isdir(output_dir):
            raise FileNotFoundError(f"Output dir not found: {output_dir}")
        tmp_file_path = os.path.join(output_dir, f"{archive_name}.tmp")
        target_file_path = os.path.join(output_dir, archive_name)
        async with self._client.get(self._get_archive_dl_url(archive_name)) as response:
            async with aiofiles.open(tmp_file_path, "wb") as f:
                async for chunk in response.content.iter_chunked(self._DOWNLOAD_CHUNK_SIZE):
                    await f.write(chunk)
        if os.path.isfile(tmp_file_path):
            await aioshutil.move(tmp_file_path, target_file_path)
        else:
            raise ValueError(f"Missing download tmp: {tmp_file_path}")
        return target_file_path

    async def get_packages(self, path: str, channel: Optional[str] = None) -> list[dict]:
        pkg_elements = await self._get_package_elements(path)
        return sorted([
            d
            for d in [xml_to_dict(e, ANDROID_REPO_NS)["remotePackage"] for e in pkg_elements]
            if channel is None or ("channelRef" in d and d["channelRef"]["@ref"] == channel)
        ], key=lambda x: self.revision_dict_to_list(x["revision"]), reverse=True)

    async def get_latest_package(self, path: str, channel: Optional[str] = None) -> dict:
        pkgs = await self.get_packages(path, channel)
        if len(pkgs) > 0:
            return pkgs[0]
        else:
            raise ValueError(f"Package {path} not exists!")
