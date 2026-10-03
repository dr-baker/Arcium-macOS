import os
import argparse
from pathlib import Path
import subprocess
import tempfile
from time import sleep

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REQUEST_HEADERS = {}
if GITHUB_TOKEN is not None:
  REQUEST_HEADERS['Authorization'] = f'Bearer {GITHUB_TOKEN}'
  print('using github token for api requests')

class mount(object):
    def __init__(self, dmg, mountpoint):
      self.dmg = dmg
      self.mountpoint = mountpoint
    def __enter__(self):
      subprocess.check_output([ 'hdiutil', 'attach', self.dmg, '-mountpoint', self.mountpoint ])
    def __exit__(self, *args, **kwargs):
      subprocess.check_output([ 'hdiutil', 'detach', '-force', self.mountpoint ])


def get_asset_url(release, arch):
  for asset in release['assets']:
      if (
        asset['name'].startswith('arcium_')
        and asset['name'].endswith(f'_{arch}-macos.dmg')
      ):
        return asset['browser_download_url']
  return None


def get_historic_dmg_urls():
  import requests

  repo = os.environ.get('GITHUB_REPOSITORY', 'dr-baker/Arcium-macOS')
  response = requests.get(
    f'https://api.github.com/repos/{repo}/releases?per_page=5',
    headers=REQUEST_HEADERS,
  )
  response.raise_for_status()

  urls = {}

  response = response.json()
  for release in response:
    version = release['tag_name'].split('-')[0]
    x86_url = get_asset_url(release, 'x86_64')
    arm_url = get_asset_url(release, 'arm64')
    if arm_url is not None or x86_url is not None:
      urls[version] = (arm_url, x86_url)

  return urls


def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument('--x86', help='.dmg')
  parser.add_argument('--arm', help='.dmg')
  parser.add_argument('--out', help='dir', required=True)

  args = parser.parse_args()
  return (args.arm, args.x86, args.out)


def do_diff(old_path, new_path, out_path):
  print(f'diffing: ({old_path} ~ {new_path}) -> {out_path}')
  subprocess.check_output([
    'BinaryDelta', 'create', '--version', '4',
    old_path, new_path, out_path
  ])


def mounted_release_app_path(mountpoint):
  """Resolve the Arcium app bundle in a mounted release disk image."""
  mountpoint = Path(mountpoint)
  path = mountpoint / "Arcium.app"
  if path.is_dir():
    return str(path)
  raise FileNotFoundError(f"release disk image has no Arcium.app: {mountpoint}")


def generate_delta_for(version, urls, args):
  import requests

  for i, arch in enumerate(['arm64', 'x86_64']):
    if args[i] is None:
      print(f'skipping {arch}')
      continue
    if urls[i] is None:
      print(f'skipping {arch}: release has no Arcium DMG')
      continue

    with tempfile.NamedTemporaryFile(suffix='.dmg') as f:
      with requests.get(urls[i], headers=REQUEST_HEADERS, stream=True) as r:
        r.raise_for_status()
        f.write(r.content)
      print(f.name)
      with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        with mount(f.name, d1), mount(args[i], d2):
          old_app = mounted_release_app_path(d1)
          new_app = mounted_release_app_path(d2)
          do_diff(old_app, new_app, f'{args[2]}/{version}-{arch}.delta')


if __name__ == '__main__':
  args = parse_args()
  versions = get_historic_dmg_urls()
  for version in versions:
    print(f'doing {version}')
    generate_delta_for(version, versions[version], args)
