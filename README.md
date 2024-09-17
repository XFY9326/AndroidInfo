# AndroidInfo

[![Automatic update](https://github.com/XFY9326/AndroidInfo/actions/workflows/automatic-update.yml/badge.svg)](https://github.com/XFY9326/AndroidInfo/actions/workflows/automatic-update.yml)

Get latest Android info from docs

Reference: [Android source docs](https://source.android.com/docs)

## Features

- Without downloading all source codes
- Full type hint for future development
- Easy to load from JSON and dump to JSON
- Contains all details

## Data

### Versions

API levels: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/api_levels.json)

Build versions: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/build_versions.json)

### Permissions

Latest Permissions: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/permissions/permissions-REL.json)

Latest SDK Permissions: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/permissions/permissions-REL-SDK.json)

Permissions with API level: [View](https://github.com/XFY9326/AndroidInfo/tree/main/outputs/permissions)

### API-Permission mappings

**Attention: This data is not complete, please use it with caution.**

API-Permission Mappings (Only support API >= 26): [View](https://github.com/XFY9326/AndroidInfo/tree/main/outputs/permission_mappings)

### ContentProviders

Latest ContentProviders: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/providers/all_providers.json)

Latest ContentProviders authority classes: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/providers/authority_classes.json)

Latest ContentProviders with permissions: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/providers/permission_providers.json)

## Usage

```shell
python3 src/main.py
```

Or you can import any script you like in your code

```python
from android_info import AndroidFrameworkPermissions
from android_info import AndroidPlatformAPIPermissions, AndroidPlatformProviderAuthorities
from android_info import AndroidProviderManifests
from android_info import AndroidVersions, AndroidAPILevel, AndroidBuildTag
```

## Jar libs

'libs/PlatformTools' -> platform_tools.jar (Require JDK 17)

