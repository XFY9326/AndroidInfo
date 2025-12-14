import os

import aiohttp

from .repository import AndroidRepository


class AndroidSources:
    # Stable channel
    _DEFAULT_CHANNEL = "channel-0"

    def __init__(self, client: aiohttp.ClientSession, download_dir: str):
        self._repo: AndroidRepository = AndroidRepository.cached_instance(client)
        self._download_dir: str = download_dir
        self._cached_source_zip_archive_url: dict[int, str] = {}

    async def _get_sources_zip_archive(self, api: int, no_cache: bool = False) -> str:
        if not no_cache and api in self._cached_source_zip_archive_url:
            return self._cached_source_zip_archive_url[api]
        else:
            pkg_dict = await self._repo.get_latest_package(f"sources;android-{api}", self._DEFAULT_CHANNEL)
            url = self._repo.get_best_archive_url(pkg_dict)
            self._cached_source_zip_archive_url[api] = url
            return url

    async def load_sources_zip(self, api: int) -> str:
        archive_name = await self._get_sources_zip_archive(api)
        local_path = os.path.join(self._download_dir, archive_name)
        if os.path.isfile(local_path):
            return local_path
        else:
            return await self._repo.download_archive(archive_name, self._download_dir)
