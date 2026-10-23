#!/bin/bash -eux

set -o pipefail

_root_dir="$(dirname "$(greadlink -f "$0")")"
_main_repo="$_root_dir/helium-chromium"

_notes_file="${RELEASE_NOTES_FILE:-}"
if [ -n "$_notes_file" ]; then
    _notes_file="$_root_dir/$_notes_file"
    if [ ! -f "$_notes_file" ] || [ ! -s "$_notes_file" ]; then
        echo "Release notes must name a nonempty file: $RELEASE_NOTES_FILE" >&2
        exit 1
    fi
elif [ "${REQUIRE_RELEASE_NOTES:-0}" = 1 ]; then
    echo 'Set RELEASE_NOTES_FILE to the versioned product release notes.' >&2
    exit 1
fi

_helium_version=$(python3 "$_main_repo/utils/helium_version.py" --tree "$_main_repo" --platform-tree "$_root_dir" --print)

_base_hash_name="arcium_${_helium_version}"
_x64_hash_name="${_base_hash_name}_x86_64-macos.dmg.hashes.md"
_arm64_hash_name="${_base_hash_name}_arm64-macos.dmg.hashes.md"

_gh_run_href="https://github.com/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"

: > ./github_release_note.md

if [ -n "$_notes_file" ]; then
    cat "$_notes_file" | tee -a ./github_release_note.md
    printf '\n\n## Release assets\n\n' | tee -a ./github_release_note.md
else
    printf '## Arcium for macOS %s\n' "${_helium_version}" | tee -a ./github_release_note.md
    if [ -f "$_root_dir/announcements.md" ]; then
        printf '\n### Announcements\n\n' | tee -a ./github_release_note.md
        cat "$_root_dir/announcements.md" | tee -a ./github_release_note.md
        printf '\n\n### Release assets\n\n' | tee -a ./github_release_note.md
    fi
fi

cat "$_arm64_hash_name" | tee -a ./github_release_note.md
printf '\n' | tee -a ./github_release_note.md
cat "$_x64_hash_name" | tee -a ./github_release_note.md

submodule_commit_at() {
    git ls-tree "$1" helium-chromium | awk '{print $3}'
}

last_tag=$(git describe --tags --abbrev=0)
commit_then=$(submodule_commit_at "$last_tag")
commit_now=$(submodule_commit_at HEAD)

{
  printf '\n\n<details>\n<summary>Source changes since the previous build</summary>\n\n### helium-macos\n```\n'
  git log --oneline "$last_tag..HEAD"
  printf '```\n\n### helium-chromium\n```\n'
  git -C helium-chromium log --oneline "$commit_then..$commit_now"
  printf '```\n\n</details>\n\n---\n\n'
  printf 'See [this GitHub Actions Run](%s) for the [Workflow file](%s/workflow) used ' \
    "$_gh_run_href" "$_gh_run_href"
  printf 'as well as the build logs and artifacts\n'
} | tee -a ./github_release_note.md
