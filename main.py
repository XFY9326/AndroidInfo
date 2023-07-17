import os
import json
import dataclasses

from versions import AndroidBuildNumbers


def main():
    android_builds = AndroidBuildNumbers()

    output_dir = "outputs"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    api_levels = android_builds.list_api_levels()
    with open(os.path.join(output_dir, "api_levels.json"), "w", encoding="utf-8") as f:
        json.dump([dataclasses.asdict(i) for i in api_levels], f)

    build_versions = android_builds.list_build_versions()
    with open(os.path.join(output_dir, "build_versions.json"), "w", encoding="utf-8") as f:
        json.dump([dataclasses.asdict(i) for i in build_versions], f)

    api_mappings = android_builds.get_api_mappings()
    with open(os.path.join(output_dir, "api_mappings.json"), "w", encoding="utf-8") as f:
        json.dump(api_mappings, f)


if __name__ == "__main__":
    main()
