# The architecture of the running shell
# Also used to determine the build target architecture
_arch="$(/usr/bin/uname -m)"

# General paths. dev.sh sets _root_dir and _build_dir before sourcing this
# file; build.sh leaves _build_dir unset, so release builds always use
# <checkout>/build.
_root_dir=${_root_dir:-$(dirname $(greadlink -f $0))}
_build_dir=${_build_dir:-$_root_dir/build}
_download_cache="$_build_dir/download_cache"
_src_dir="$_build_dir/src"
_out_dir="$_src_dir/out/Default"
_main_repo="$_root_dir/helium-chromium"
_subs_cache="$_build_dir/subs.tar.gz"
_namesubs_cache="$_build_dir/namesubs.tar"

# SISO paths
_depot_tools_dir="$_src_dir/third_party/depot_tools"
_siso_dir="$_src_dir/third_party/siso/cipd"
_siso_path="$_siso_dir/siso"

source "$_root_dir/devutils/setup_python.sh"
