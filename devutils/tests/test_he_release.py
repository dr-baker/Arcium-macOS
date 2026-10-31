"""Exercise the official archive entrypoint without a Chromium download."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('ninja') and shutil.which('greadlink'), 'needs ninja and GNU readlink')
class ReleaseEntrypointTest(unittest.TestCase):
    def test_archive_both_architectures_keep_official_flags_lock_and_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            shutil.copy2(TOOLS / 'build.sh', root / 'build.sh')
            (root / 'devutils').symlink_to(TOOLS / 'devutils', target_is_directory=True)
            core = root / 'helium-chromium'
            (core / 'utils').mkdir(parents=True)
            (core / 'devutils').mkdir()
            (core / 'devutils/restore_lite_test_fixtures.py').write_text('')
            (core / 'flags.gn').write_text('is_official_build = true\n')
            (root / 'flags.macos.gn').write_text('is_component_build = false\n')
            (root / 'env.sh').write_text('''
_arch="$(uname -m)"
_root_dir="${_root_dir}"
_build_dir="${HELIUM_DEV_BUILD_ROOT}"
_src_dir="$_build_dir/src"
_download_cache="$_build_dir/download_cache"
_main_repo="$_root_dir/helium-chromium"
_depot_tools_dir="$_src_dir/third_party/depot_tools"
___helium_setup_python() { :; }
''')
            for name in ('prune_binaries', 'patches', 'domain_substitution', 'name_substitution',
                         'i18n_apply', 'helium_version', 'generate_resources', 'replace_resources'):
                (core / 'utils' / (name + '.py')).write_text('')
            # The release script owns this invocation even during preparation.
            prepare = root / 'retrieve_and_unpack_resource.sh'
            prepare.write_text('''#!/bin/bash
set -e
python3 -m he.release --worktree "$(dirname "$0")" held
mkdir -p "$HELIUM_DEV_BUILD_ROOT/src/out/Default"
''')
            prepare.chmod(0o755)
            src = root / 'build/src'
            (src / 'third_party/depot_tools').mkdir(parents=True)
            (src / 'third_party/siso/cipd').mkdir(parents=True)
            (src / 'third_party/siso/cipd/siso').touch()
            (src / 'third_party/depot_tools/autoninja.py').write_text('''import os,sys
from pathlib import Path
src=Path.cwd()
assert (src.parent/'.gclient').is_file()
assert (src.parent/'.gclient_entries').is_file()
assert '--offline' in sys.argv
args=[]
for a in sys.argv[1:]:
 if a in ('--offline','-o','-project='): continue
 if a.startswith('-local_jobs='): args += ['-j',a.split('=',1)[1]]
 else: args.append(a)
os.execvp('ninja',['ninja',*args])
''')
            (src / 'build/config/siso').mkdir(parents=True)
            (src / 'build/config/siso/configure_siso.py').write_text('')
            (src / 'buildtools/mac').mkdir(parents=True)
            gn = src / 'buildtools/mac/gn'
            gn.write_text("#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\nout=Path(sys.argv[2])\n(out/'build.ninja').write_text('build chrome: phony\\nbuild chromedriver: phony\\n')\n")
            gn.chmod(0o755)
            package = root / 'sign_and_package_app.sh'
            package.write_text('''#!/bin/bash
set -e
python3 -m he.release --worktree "$(dirname "$0")" held
cp "$HELIUM_DEV_BUILD_ROOT/src/out/Default/args.gn" "$HELIUM_DEV_BUILD_ROOT/packaged-args.gn"
''')
            package.chmod(0o755)
            # Run the real guarded release router against the synthetic graph.
            (root / 'devutils').unlink()
            (root / 'devutils').mkdir()
            (root / 'devutils/he').symlink_to(TOOLS / 'devutils/he', target_is_directory=True)
            (root / 'devutils/cloud_build').symlink_to(TOOLS / 'devutils/cloud_build', target_is_directory=True)
            env = {**os.environ, 'HELIUM_BUILD_EXECUTION': 'local'}
            for arch, cpu in [('arm64', 'arm64'), ('x86_64', 'x64')]:
                result = subprocess.run(['bash', str(root / 'build.sh'), '-d', arch], cwd=root,
                                        env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-5000:])
                flags = (root / 'build/packaged-args.gn').read_text()
                self.assertIn(f'target_cpu = "{cpu}"', flags)
                self.assertIn('is_official_build = true', flags)
                self.assertIn('chrome_pgo_phase=2', flags)
                self.assertIn('is_component_build = false', flags)
                self.assertTrue((root / 'build/.arcium/release.lock').exists())
                self.assertFalse((root / 'build/.arcium/lane.lock').exists())
                self.assertFalse((root / 'build/.arcium/lane-command.json').exists())


if __name__ == '__main__':
    unittest.main()
