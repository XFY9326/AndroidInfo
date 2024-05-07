import asyncio
import dataclasses
import http
import json
import os
import random
import urllib.parse
from io import StringIO
from typing import Optional

import aiofiles
import aiofiles.os
import aiohttp
from bs4 import BeautifulSoup
from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element
from tqdm import tqdm


@dataclasses.dataclass(frozen=True)
class AndroidSourceCodePath:
    project: str
    path: str

    @property
    def full_path(self):
        return self.project + self.path


@dataclasses.dataclass(frozen=True)
class AndroidProjectMapping:
    name: str
    path: str


class AndroidRemoteSourceCode:
    def __init__(self, client: aiohttp.ClientSession, source_code_path: AndroidSourceCodePath, download_dir: Optional[str]):
        self._source: AndroidGoogleSource = AndroidGoogleSource(client)
        self._download_dir: Optional[str] = download_dir
        self._source_code_path: AndroidSourceCodePath = source_code_path

    async def get_content(self, refs: str, load_cache: bool = False) -> str:
        if self._download_dir is not None:
            local_path = os.path.join(
                self._download_dir,
                refs.replace("/", "_"),
                os.path.basename(self._source_code_path.path)
            )
            if load_cache and os.path.isfile(local_path):
                async with aiofiles.open(local_path, "r", encoding="utf-8") as f:
                    return await f.read()
            else:
                file_content = await self._source.get_source_code(self._source_code_path, refs)
                if self._download_dir is not None:
                    if not os.path.isdir(os.path.dirname(local_path)):
                        await aiofiles.os.makedirs(os.path.dirname(local_path))
                    async with aiofiles.open(local_path, "w", encoding="utf-8") as f:
                        await f.write(file_content)
                return file_content
        else:
            return await self._source.get_source_code(self._source_code_path, refs)


class AndroidGoogleSource:
    _BS4_PARSER = "lxml"
    _BASE_URL = "https://android.googlesource.com"

    def __init__(self, client: aiohttp.ClientSession):
        self._client: aiohttp.ClientSession = client

    def _build_url(self, project: str, refs: Optional[str] = None, path: Optional[str] = None):
        project = project.lstrip("/ ")
        url = f"{self._BASE_URL}/{project}"
        if refs is not None:
            refs = refs.lstrip("/ ")
            url += f"/+/{refs}"
            if path is not None:
                path = path.lstrip("/ ")
                url += f"/{path}"
        return url

    async def get_content(self, url: str) -> str:
        async with self._client.get(url) as response:
            html_content = await response.text()
        soup = BeautifulSoup(html_content, self._BS4_PARSER)
        file_element = soup.find("table", {"class": "FileContents"})
        line_elements = file_element.find_all("td", {"id": True})
        return "\n".join([i.text for i in line_elements])

    async def exists(self, project: str, refs: Optional[str] = None) -> bool:
        async with self._client.head(self._build_url(project, refs)) as response:
            return response.status != http.HTTPStatus.NOT_FOUND

    async def get_file(self, project: str, refs: str, path: str) -> str:
        return await self.get_content(self._build_url(project, refs, path))

    async def get_source_code(self, code_path: AndroidSourceCodePath, refs: str) -> str:
        return await self.get_file(code_path.project, refs, code_path.path)


class AndroidPlatformManifest:
    _MANIFEST_REPO = "platform/manifest"
    _MANIFEST_REF = "refs/heads/main"
    _MANIFEST_PATH = "default.xml"

    def __init__(self, source: AndroidGoogleSource):
        self._source: AndroidGoogleSource = source
        self._path: Optional[list[AndroidProjectMapping]] = None

    async def _load_project_mappings(self) -> list[AndroidProjectMapping]:
        manifest_file = await self._source.get_file(self._MANIFEST_REPO, self._MANIFEST_REF, self._MANIFEST_PATH)
        root_node: _Element = etree.fromstring(manifest_file.encode("utf-8"))
        return [
            AndroidProjectMapping(element.attrib["name"], element.attrib["path"])
            for element in root_node.xpath("/manifest/project")
        ]

    async def get_project_mappings(self) -> list[AndroidProjectMapping]:
        if self._path is None:
            self._path = await self._load_project_mappings()
        return self._path


class AndroidSourceCodeQuery:
    MAIN_REFS = "refs/heads/main"

    # From https://cs.android.com/search
    _API_URL = "https://grimoireoss-pa.clients6.google.com"
    # noinspection SpellCheckingInspection
    _API_KEY = "AIzaSyD1ZDuAdU_IZqa3Wscr053WydRT7FoJdmQ"

    _DEFAULT_QUERY_PAGE_NUM = 100
    _REQUEST_DELAY = 1

    def __init__(self, client: aiohttp.ClientSession):
        self._client: aiohttp.ClientSession = client
        self._source: AndroidGoogleSource = AndroidGoogleSource(client)
        self._platform_manifest: AndroidPlatformManifest = AndroidPlatformManifest(self._source)

    @staticmethod
    def _generate_random_batch() -> str:
        return f"batch{int(random.random() * 1e18)}"

    def _get_api_url(self, batch: str) -> str:
        query_part = urllib.parse.urlencode({
            "$ct": f"multipart/mixed; boundary={batch}"
        }, quote_via=urllib.parse.quote)
        return f"{self._API_URL}/batch?{query_part}"

    @staticmethod
    def get_query_config(
            query_string: str,
            project: str = "",
            repository: str = "",
            path_prefix: str = "",
            page_token: Optional[str] = None
    ) -> dict:
        return {
            "queryString": query_string,
            "searchOptions": {
                "enableDiagnostics": False,
                "exhaustive": False,
                "numberOfContextLines": 0,
                "pageSize": AndroidSourceCodeQuery._DEFAULT_QUERY_PAGE_NUM,
                "pageToken": page_token if page_token is not None else "",
                "pathPrefix": path_prefix,
                "repositoryScope": {
                    "root": {
                        "ossProject": project,
                        "repositoryName": repository
                    }
                },
                "retrieveMultibranchResults": True,
                "savedQuery": "",
                "scoringModel": "",
                "showPersonalizedResults": False
            },
            "snippetOptions": {
                "minSnippetLinesPerFile": 0,
                "minSnippetLinesPerPage": 0,
                "numberOfContextLines": 0
            }
        }

    def _build_query_content(self, batch: str, query_config: dict) -> str:
        return f"--{batch}\r\n" + \
            "Content-Type: application/http\r\n" + \
            f"Content-ID: <{batch}+gapiRequest@googleapis.com>\r\n" + \
            "\r\n" + \
            f"POST /v1/contents/search?alt=json&key={self._API_KEY}\r\n" + \
            "Content-Type: application/json\r\n" + \
            "\r\n" + \
            f"{json.dumps(query_config)}\r\n" + \
            f"--{batch}--"

    @staticmethod
    def _parse_query_result(text: str) -> dict:
        batch_barrier: Optional[str] = None
        http_content: list[str] = []
        part_counter = 0
        is_http_success = False
        with StringIO(text) as reader:
            for line in reader:
                line = line.strip()
                if len(line) > 0 and batch_barrier is None and line.startswith("--"):
                    batch_barrier = f"{line}--"
                elif batch_barrier is not None and len(line) == 0:
                    part_counter += 1
                elif part_counter == 1 and line == "HTTP/1.1 200 OK":
                    is_http_success = True
                elif batch_barrier != line and part_counter == 2:
                    http_content.append(line)
                elif batch_barrier == line:
                    break
        content = json.loads("\n".join(http_content))
        if is_http_success:
            return content
        else:
            raise ValueError(f"Request failed: {content}")

    async def query_pages(self, query_config: dict) -> list[dict]:
        result: list[dict] = list()
        is_first_batch = True
        next_page_token: Optional[str] = None
        with tqdm(desc="Code query", total=1) as pbar:
            while is_first_batch or next_page_token is not None:
                if is_first_batch:
                    is_first_batch = False
                batch = self._generate_random_batch()
                url = self._get_api_url(batch)
                if next_page_token is not None:
                    query_config["searchOptions"]["pageToken"] = next_page_token
                content = self._build_query_content(batch, query_config)
                async with self._client.post(url, data=content, headers={
                    "Content-Type": "text/plain",
                    "Referer": "https://cs.android.com/"
                }) as response:
                    query_result = self._parse_query_result(await response.text())
                    result.append(query_result)
                    next_page_token = query_result.setdefault("nextPageToken", None)
                    total_query_results = int(query_result["estimatedResultCount"])
                    if pbar.total != total_query_results:
                        last_pos = pbar.pos
                        pbar.reset(total_query_results)
                        pbar.update(last_pos)
                    pbar.update(len(query_result["searchResults"]))
                    if next_page_token is not None:
                        await asyncio.sleep(self._REQUEST_DELAY)
        return result

    async def extract_source_code_path(self, query_results: list[dict]) -> list[AndroidSourceCodePath]:
        file_path_list = [
            item["fileSearchResult"]["fileSpec"]["path"]
            for query_result in query_results for item in query_result["searchResults"]
        ]
        project_path_list = await self._platform_manifest.get_project_mappings()
        result: list[AndroidSourceCodePath] = []
        for file_path in file_path_list:
            found = False
            for project_path in project_path_list:
                if file_path.startswith(project_path.path + "/"):
                    result.append(AndroidSourceCodePath(project_path.name, file_path[len(project_path.path):]))
                    found = True
                    break
            if not found:
                raise ValueError(f"Unknown project path: {file_path}")
        return result

    async def get_source(self) -> AndroidGoogleSource:
        return self._source
