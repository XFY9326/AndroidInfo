import os
from functools import lru_cache

import aiohttp

from .repository import AndroidRepository


class AndroidSources:
    # Stable channel
    _DEFAULT_CHANNEL = "channel-0"

    def __init__(self, client: aiohttp.ClientSession, download_dir: str):
        self._repo: AndroidRepository = AndroidRepository(client)
        self._download_dir: str = download_dir

    @lru_cache
    async def _get_sources_zip_archive(self, api: int):
        pkg_dict = await self._repo.get_latest_package(f"sources;android-{api}", self._DEFAULT_CHANNEL)
        return self._repo.get_best_archive_url(pkg_dict)

    async def load_sources_zip(self, api: int) -> str:
        archive_name = await self._get_sources_zip_archive(api)
        local_path = os.path.join(self._download_dir, archive_name)
        if os.path.isfile(local_path):
            return local_path
        else:
            return await self._repo.download_archive(archive_name, self._download_dir)
