#!/usr/bin/env bash

set -eux
_release_args=("$@")

# Validate inputs before preparing dependencies or resetting build output.
clone=true
while getopts ':d' OPTION; do
  case "$OPTION" in
    d)
      clone=false
      ;;
    *)
      echo "Unsupported build option: -$OPTARG" >&2
      exit 2
      ;;
  esac
done

shift "$(($OPTIND -1))"

if [[ $# -gt 1 ]]; then
  echo 'Usage: build.sh [-d] [arm64|x86_64]' >&2
  exit 2
fi

_build_target_arch=${1-arm64}
case "$_build_target_arch" in
  arm64|x86_64) ;;
  *)
    echo "Unsupported macOS build architecture: $_build_target_arch" >&2
    exit 2
    ;;
esac

# Build script for local macOS environment
_root_dir="$(dirname "$(greadlink -f "$0")")"

# Python paths are resolved while env.sh is sourced. Bind them before that
# happens so a standalone release build cannot use an ambient development
# build dir. dev.sh's settings (HELIUM_BUILD_DIR, ~/.config/arcium/dev.env)
# never apply here.
unset _build_dir HELIUM_BUILD_DIR HELIUM_DEV_WORKTREE HELIUM_TMPDIR
export HELIUM_DEV_BUILD_ROOT="$_root_dir/build"
export HELIUM_DEV_PYTHON_ENV="$_root_dir/build/python-env"
source "$_root_dir/env.sh"

# env.sh initializes _arch from the host. Preserve the requested build target.
_arch="$_build_target_arch"

if [[ -e "$_root_dir/build/.arcium/lane.lock" || -d "$_src_dir/.pc" ]]; then
  echo 'Refusing to reset a development lane; use a dedicated release checkout.' >&2
  exit 2
fi

export PYTHONPATH="$_root_dir/devutils${PYTHONPATH:+:$PYTHONPATH}"
if ! python3 -m he.release --worktree "$_root_dir" held; then
  exec python3 -m he.release --worktree "$_root_dir" lock -- /bin/bash "$0" "${_release_args[@]}"
fi

# Keep resource retrieval inside the same release checkout.
export HELIUM_DEV_DOWNLOAD_CACHE="$_download_cache"
___helium_setup_python

# Add local clang and build tools to PATH
# export PATH="$PATH:$_src_dir/third_party/llvm-build/Release+Asserts/bin"

rm -rf "$_src_dir/out" || true
mkdir -p "$_download_cache"

if $clone; then
  "$_root_dir/retrieve_and_unpack_resource.sh" -g $_arch
else
  "$_root_dir/retrieve_and_unpack_resource.sh" -d -g $_arch
fi

mkdir -p "$_src_dir/out/Default"
python3 -m he --worktree "$_root_dir" --build-dir "$_root_dir/build" gclient-marker

python3 "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list"
"$_root_dir/retrieve_and_unpack_resource.sh" -t
"$_root_dir/devutils/setup_dawn_go.sh" \
    "$_src_dir" "$_depot_tools_dir" "$_arch"

# Apply patches, substitutions and translations
python3 "$_main_repo/utils/patches.py" apply --no-fuzz "$_src_dir" "$_main_repo/patches" "$_root_dir/patches"
python3 "$_main_repo/utils/domain_substitution.py" apply -r "$_main_repo/domain_regex.list" -f "$_main_repo/domain_substitution.list" "$_src_dir"
python3 "$_main_repo/utils/name_substitution.py" --sub -t "$_src_dir"
python3 "$_main_repo/utils/i18n_apply.py" -t "$_src_dir"

python3 "$_main_repo/utils/helium_version.py" \
    --tree "$_main_repo" \
    --platform-tree "$_root_dir" \
    --chromium-tree "$_src_dir"

# Generate and apply Helium resources
python3 "$_main_repo/utils/generate_resources.py" "$_main_repo/resources/generate_resources.txt" "$_main_repo/resources"
python3 "$_main_repo/utils/replace_resources.py" "$_root_dir/resources/platform_resources.txt" "$_root_dir/resources" "$_src_dir"
python3 "$_main_repo/utils/replace_resources.py" "$_main_repo/resources/helium_resources.txt" "$_main_repo/resources" "$_src_dir"

# Set build flags
cat "$_main_repo/flags.gn" "$_root_dir/flags.macos.gn" > "$_src_dir/out/Default/args.gn"

echo 'use_siso = true' >> "$_src_dir/out/Default/args.gn"
if python3 -m he.release --worktree "$_root_dir" enabled; then
  printf 'use_remoteexec = true\nuse_reclient = false\n' >> "$_src_dir/out/Default/args.gn"
elif command -v sccache 2>&1 >/dev/null; then
  echo 'cc_wrapper="sccache"' >> "$_src_dir/out/Default/args.gn";
elif command -v ccache 2>&1 >/dev/null; then
  echo 'cc_wrapper="env CCACHE_COMPILERCHECK=content CCACHE_SLOPPINESS=time_macros ccache"' >> "$_src_dir/out/Default/args.gn";
else
  echo 'warn: sccache or ccache is not available' >&2
fi

# Set target_cpu to the corresponding architecture
if [[ $_arch == "arm64" ]]; then
  echo 'target_cpu = "arm64"' >> "$_src_dir/out/Default/args.gn"
else
  echo 'target_cpu = "x64"' >> "$_src_dir/out/Default/args.gn"
fi

if $clone; then
  echo 'chrome_pgo_phase=2' >> "$_src_dir/out/Default/args.gn"
fi

cd "$_src_dir"

./tools/gn/bootstrap/bootstrap.py -o out/Default/gn --skip-generate-buildfiles
python3 -m he.release --worktree "$_root_dir" configure
./out/Default/gn gen out/Default --fail-on-unused-args
python3 -m he.release --worktree "$_root_dir" record-ready

python3 -m he.release --worktree "$_root_dir" compile \
  --execution "${HELIUM_BUILD_EXECUTION:-auto}" chrome chromedriver

"$_root_dir/sign_and_package_app.sh"
