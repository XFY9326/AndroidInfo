ANDROID_MAIN_REFS: str = "refs/heads/main"

# noinspection HttpUrlsUsage
ANDROID_MANIFEST_NS: dict[str, str] = {
    "android": "http://schemas.android.com/apk/res/android",
    "tools": "http://schemas.android.com/tools",
    "app": "http://schemas.android.com/apk/res-auto",
}

JVM_BASIC_SIGNATURE_MAPPING: dict[str, str] = {
    "int": "I",
    "long": "J",
    "float": "F",
    "double": "D",
    "byte": "B",
    "short": "S",
    "char": "C",
    "boolean": "Z",
    "void": "V",
}

# Manually written due to lack of documentation
API_LEVEL_MAPPING: dict[int, list[str]] = {
    1: ["1.0"],  # No build versions
    2: ["1.1"],  # No build versions
    3: ["1.5"],  # No build versions
    4: ["1.6"],
    5: ["2.0"],
    6: ["2.0.1"],
    7: ["2.1"],
    8: ["2.2", "2.2.1", "2.2.2", "2.2.3"],
    9: ["2.3", "2.3.1", "2.3.2"],
    10: ["2.3.3", "2.3.4", "2.3.5", "2.3.6", "2.3.7"],
    11: ["3.0"],  # No build versions
    12: ["3.1"],  # No build versions
    13: ["3.2", "3.2.1", "3.2.2", "3.2.4", "3.2.6"],  # Only 3.2.4 has build versions
    14: ["4.0.1", "4.0.2"],
    15: ["4.0.3", "4.0.4"],
    16: ["4.1.1", "4.1.2"],
    17: ["4.2", "4.2.1", "4.2.2"],
    18: ["4.3", "4.3.1"],
    19: ["4.4", "4.4.1", "4.4.2", "4.4.3", "4.4.4"],
    20: ["4.4w"],  # No build versions (Not list in docs)
    21: ["5.0.0", "5.0.1", "5.0.2", "5.1.0"],
    22: ["5.1.1"],
    23: ["6.0.0", "6.0.1"],
    24: ["7.0.0"],
    25: ["7.1.0", "7.1.1", "7.1.2"],
    26: ["8.0.0"],
    27: ["8.1.0"],
    28: ["9.0.0"],
    29: ["10.0.0"],
    30: ["11.0.0"],
    31: ["12.0.0"],
    32: ["12.1.0"],
    33: ["13.0.0"],
    34: ["14.0.0"],
}
