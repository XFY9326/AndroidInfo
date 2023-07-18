# AndroidInfo

Get latest Android info from docs

Reference: [Android source docs](https://source.android.com/docs)

## Features

- Daily automatically update
- Without downloading all source codes
- Full type hint for future development
- Easy to load from JSON and dump to JSON
- Contains all details

## Daily automatically update

### Versions

API levels: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/api_levels.json)

Build versions: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/build_versions.json)

### Permissions

Latest Permissions: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/permissions/permissions-REL.json)

Permissions with  API level: [View](https://github.com/XFY9326/AndroidInfo/tree/main/outputs/permissions)

### API-Permission mappings

API-Permission Mappings (Only support API >= 26): [View](https://github.com/XFY9326/AndroidInfo/tree/main/outputs/permission_mappings)

Latest ContentProviders: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/permission_mappings/all_content_providers-REL.json)

Latest ContentProviders with permissions: [Download](https://github.com/XFY9326/AndroidInfo/raw/main/outputs/permission_mappings/permission_content_providers-REL.json)

## Usage

```shell
python main.py
```

Or you can import any script you like in your code

```python
from android_info.versions import AndroidVersions
from android_info.permissions import AndroidFrameworkPermissions
from android_info.platforms import AndroidPlatformAPIPermissions
from android_info.providers import AndroidProviderManifests
```
