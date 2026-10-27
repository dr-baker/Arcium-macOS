#!/usr/bin/env python3
"""One immutable source generation for each native UI iteration."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


class SupersededIteration(RuntimeError):
    pass


CONFIGURATION_INPUTS = (
    'flags.macos.gn', 'downloads.ini', 'deps.ini',
    'helium-chromium/flags.gn', 'helium-chromium/chromium_version.txt',
    'helium-chromium/version.txt', 'helium-chromium/deps.ini', 'helium-chromium/downloads.ini',
)


def inputs(root):
    result = {root / name for name in CONFIGURATION_INPUTS if (root / name).is_file()}
    for repo, mapping in ((root, 'resources/platform_resources.txt'),
                          (root / 'helium-chromium', 'resources/helium_resources.txt')):
        series = repo / 'patches/series'
        result.add(series)
        for raw in series.read_text().splitlines():
            name = raw.split('#')[0].strip()
            if name: result.add(repo / 'patches' / name)
        resource_map = repo / mapping
        result.add(resource_map)
        for raw in resource_map.read_text().splitlines():
            raw = raw.split('#')[0].strip()
            if raw:
                origin, _ = raw.split()
                path = repo / 'resources' / origin
                if path.is_file(): result.add(path)
        result.update(path for path in (repo / 'resources').rglob('*')
                      if path.is_file() and 'generated' not in path.relative_to(repo / 'resources').parts)
    lab = root / 'devutils/command-bar-studio'
    result.update(lab.glob('*.py'))
    result.add(lab / 'native_host.mm')
    for directory in ('assets',):
        result.update(p for p in (lab / directory).rglob('*') if p.is_file())
    return sorted(result)


def hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in inputs(root)}


def stamps(root, extra_files=None):
    result = {}
    for path in inputs(root):
        stat = path.stat()
        result[str(path.relative_to(root))] = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    for name, path in (extra_files or {}).items():
        stat = path.stat()
        result[name] = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return result


@dataclass(frozen=True)
class Generation:
    identity: str
    root: Path
    source: Path
    files: dict
    external: dict = field(default_factory=dict)

    def require_current(self):
        try:
            current = hashes(self.source)
            current.update({name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for name, path in self.external.items()})
        except (FileNotFoundError, ValueError) as error:
            raise SupersededIteration('Source inputs changed during the iteration; previous app retained') from error
        if current != self.files:
            raise SupersededIteration('Source inputs changed during the iteration; previous app retained')


def capture(root, cache, extra_files=None):
    root = root.resolve()
    extra_files = extra_files or {}
    before = hashes(root)
    before.update({name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in extra_files.items()})
    identity = hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()
    generation = cache / 'generations' / identity
    if generation.exists():
        expected = json.loads((generation / 'generation.json').read_text())
        cached = hashes(generation)
        cached.update({name: hashlib.sha256((generation / name).read_bytes()).hexdigest() for name in extra_files})
        if expected != before or cached != before:
            raise RuntimeError('Immutable input generation was modified')
        result = Generation(identity, generation, root, before, extra_files)
        result.require_current()
        return result
    cache.mkdir(parents=True, exist_ok=True)
    blobs = cache / 'blobs'; blobs.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='generation-', dir=cache))
    try:
        for relative, digest in before.items():
            data = extra_files.get(relative, root / relative).read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise SupersededIteration('Source changed while capturing input generation')
            blob = blobs / digest
            if not blob.exists():
                blob.write_bytes(data)
                blob.chmod(0o444)
            elif hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                raise RuntimeError('Immutable input cache was modified')
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(blob, destination)
        result = Generation(identity, temporary, root, before, extra_files)
        result.require_current()
        (temporary / 'generation.json').write_text(json.dumps(before, sort_keys=True) + '\n')
        generation.parent.mkdir(exist_ok=True)
        temporary.rename(generation)
        return Generation(identity, generation, root, before, extra_files)
    except BaseException:
        import shutil
        shutil.rmtree(temporary)
        raise


@contextmanager
def build_lock(cache):
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / 'iteration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def publish_latest(state, app, generation):
    state.mkdir(parents=True, exist_ok=True)
    path = state / 'latest.pending.json'
    path.write_text(json.dumps({'app': str(app), 'generation': generation.identity}, indent=2) + '\n')
    path.replace(state / 'latest.json')
