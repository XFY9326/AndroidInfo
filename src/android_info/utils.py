import asyncio
import locale
import re
from collections import defaultdict
from functools import lru_cache
from itertools import zip_longest
from typing import Optional

from lxml import etree
# noinspection PyProtectedMember
from lxml.etree import _Element

from .consts import ANDROID_MANIFEST_NS, JVM_BASIC_SIGNATURE_MAPPING


@lru_cache
def android_attrib(name: str) -> str:
    return f"{{{ANDROID_MANIFEST_NS['android']}}}{name}"


@lru_cache
def jvm_type_to_signature(type_name: str) -> str:
    is_array = type_name.endswith("[]")
    # noinspection RegExpRedundantEscape
    type_name = re.sub(r"<.*>|\[\]", "", type_name)
    if type_name in JVM_BASIC_SIGNATURE_MAPPING:
        signature_name = JVM_BASIC_SIGNATURE_MAPPING[type_name]
    else:
        signature_name = f"L{type_name.replace('.', '/')};"
    if is_array:
        signature_name = "[" + signature_name
    return signature_name


def get_short_class_name(class_name: str) -> str:
    inner_class_idx = class_name.find("$")
    if inner_class_idx < 0:
        return class_name[inner_class_idx + 1:]
    else:
        class_idx = class_name.find(".")
        if class_idx < 0:
            return class_name[class_idx + 1:]
        else:
            return class_name


def xml_to_dict(element: _Element, namespaces: dict[str, str] | None = None) -> dict | None:
    ns_idx = {
        v: k for k, v in namespaces.items()
    } if namespaces is not None else None
    # noinspection RegExpRedundantEscape
    ns_attr_pattern: re.Pattern = re.compile(r"^\{(.*?)\}(.*)$")

    def _ns_attr(name: str) -> str:
        if ns_idx is not None and name.startswith("{"):
            matcher = ns_attr_pattern.fullmatch(name)
            if matcher and matcher.group(1) in ns_idx:
                return f"{ns_idx[matcher.group(1)]}:{matcher.group(2)}"
        return name

    def _recursion(e: _Element) -> dict | None:
        children = [c for c in e.getchildren() if not isinstance(c.tag, type(etree.Comment))]
        tag = _ns_attr(e.tag)
        if children:
            dd = defaultdict(list)
            for dc in map(_recursion, children):
                for k, v in dc.items():
                    dd[k].append(v)
            d = {tag: {_ns_attr(k): v[0] if len(v) == 1 else v for k, v in dd.items()}}
        else:
            d = {tag: {} if e.attrib else None}
        if e.attrib:
            d[tag].update(("@" + _ns_attr(k), v) for k, v in e.attrib.items())
        if e.text:
            text = e.text.strip()
            if children or e.attrib:
                if text:
                    d[tag]["#text"] = text
            else:
                d[tag] = text
        return d

    return _recursion(element)


class VersionCompare:
    _INSTANCE: Optional['VersionCompare'] = None

    @staticmethod
    def instance() -> 'VersionCompare':
        if VersionCompare._INSTANCE is None:
            VersionCompare._INSTANCE = VersionCompare()
        return VersionCompare._INSTANCE

    def __init__(self):
        self._version_pattern: re.Pattern = re.compile(r"(\d+)([a-zA-Z]*)")

    def compare(self, v1: str, v2: str) -> int:
        if v1 == v2:
            return 0

        m1 = self._version_pattern.findall(v1)
        m2 = self._version_pattern.findall(v2)

        for p1, p2 in zip_longest(m1, m2):
            c1, s1 = p1 if p1 is not None else (0, "")
            c2, s2 = p2 if p2 is not None else (0, "")
            c1, c2 = int(c1), int(c2)

            if c1 < c2:
                return -1
            elif c1 > c2:
                return 1
            elif s1 < s2:
                return -1
            elif s1 > s2:
                return 1

        return 0


async def run_exec(program: str, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        program,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    stdout, stderr = await process.communicate()
    return await process.wait(), stdout.decode(locale.getpreferredencoding()), stderr.decode(
        locale.getpreferredencoding())


async def check_java_version(min_version: str):
    # noinspection PyBroadException
    try:
        code, _, output = await run_exec("java", "-version")
        if code == 0:
            matcher = re.search(r"version \"(.*?)\"", output)
            if matcher is not None:
                java_version = matcher.group(1).strip()
                if VersionCompare.instance().compare(min_version, java_version) > 0:
                    raise EnvironmentError(
                        f"Current java version {java_version}. Require java version >= {min_version}!")
            else:
                raise EnvironmentError("Unknown java version")
        else:
            raise EnvironmentError("No java running environment")
    except UnicodeDecodeError:
        raise EnvironmentError("No java running environment")
