#!/bin/bash -eux

_root_dir="$(dirname "$(greadlink -f "$0")")"
_main_repo="$_root_dir/helium-chromium"

_helium_version=$(python3 "$_main_repo/utils/helium_version.py" --tree "$_main_repo" --platform-tree "$_root_dir" --print)

if [ "${REQUIRE_RELEASE_TAG:-0}" = 1 ] && [ -z "${RELEASE_TAG:-}" ]; then
    echo 'Set RELEASE_TAG to the product release tag.' >&2
    exit 1
fi
_release_tag="${RELEASE_TAG:-$_helium_version}"
git check-ref-format "refs/tags/$_release_tag"

_file_name_base="arcium_${_helium_version}"
_x64_file_name="${_file_name_base}_x86_64-macos.dmg"
_arm64_file_name="${_file_name_base}_arm64-macos.dmg"

echo "x64_file_name=$_x64_file_name" >> "$GITHUB_OUTPUT"
echo "arm64_file_name=$_arm64_file_name" >> "$GITHUB_OUTPUT"
echo "release_tag_version=$_release_tag" >> "$GITHUB_OUTPUT"
echo "release_name=Arcium $_release_tag" >> "$GITHUB_OUTPUT"
