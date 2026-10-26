#!/bin/bash -eux

# Simple script for getting ready to build Helium macOS binaries on GitHub Actions

_target_cpu="$1"

case "$_target_cpu" in
  arm64)
    _gn_target_cpu="arm64"
    _sparkle_arch="arm64"
    ;;
  x86_64)
    _gn_target_cpu="x64"
    _sparkle_arch="x86_64"
    ;;
  *)
    echo "Unsupported macOS build architecture: $_target_cpu" >&2
    exit 2
    ;;
esac

# Some path variables
_root_dir="$(dirname "$(greadlink -f "$0")")"
_download_cache="$_root_dir/build/download_cache"
_src_dir="$_root_dir/build/src"
_main_repo="$_root_dir/helium-chromium"

shopt -s nocasematch

_sparkle_public_key="${PROD_MACOS_SPARKLE_ED_PUB_KEY-}"
_sparkle_feed_base_url="${PROD_MACOS_SPARKLE_FEED_BASE_URL-}"
_sparkle_feed_url=""
if [[ -n "$_sparkle_public_key" || -n "$_sparkle_feed_base_url" ]]; then
  if [[ -z "$_sparkle_public_key" || -z "$_sparkle_feed_base_url" ]]; then
    echo 'Sparkle requires both PROD_MACOS_SPARKLE_ED_PUB_KEY and PROD_MACOS_SPARKLE_FEED_BASE_URL.' >&2
    exit 2
  fi

  if ! _sparkle_feed_url=$(python3 "$_root_dir/devutils/sparkle_feed.py" \
      --public-key "$_sparkle_public_key" \
      --feed-base-url "$_sparkle_feed_base_url" \
      --arch "$_sparkle_arch"); then
    echo 'Sparkle configuration is invalid; update checking remains disabled.' >&2
    exit 2
  fi
fi

echo "target_cpu = \"$_gn_target_cpu\"" >> "$_root_dir/flags.macos.gn"

cp "$_main_repo/flags.gn" "$_src_dir/out/Default/args.gn"
cat "$_root_dir/flags.macos.gn" >> "$_src_dir/out/Default/args.gn"
echo 'cc_wrapper="sccache"' >> "$_src_dir/out/Default/args.gn"
# Resume partitions retain Ninja's dependency state, never Siso state.
echo 'use_siso=false' >> "$_src_dir/out/Default/args.gn"

if [[ -n "$_sparkle_public_key" ]]; then
  echo 'enable_sparkle=true' >> "$_src_dir/out/Default/args.gn"
  printf 'sparkle_ed_key="%s"\n' "$_sparkle_public_key" >> "$_src_dir/out/Default/args.gn"
  printf 'sparkle_feed_url="%s"\n' "$_sparkle_feed_url" >> "$_src_dir/out/Default/args.gn"
fi

echo 'symbol_level=1' >> "$_src_dir/out/Default/args.gn"
echo 'chrome_pgo_phase=2' >> "$_src_dir/out/Default/args.gn"

cd "$_src_dir"

./tools/gn/bootstrap/bootstrap.py -o out/Default/gn --skip-generate-buildfiles
./out/Default/gn gen out/Default --fail-on-unused-args
