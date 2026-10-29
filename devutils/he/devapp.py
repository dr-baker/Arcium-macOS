"""Named Dev profiles: `he run --profile NAME` and `he stop --profile NAME`.

Every named profile runs the same `Helium Dev.app` (net.imput.helium.dev),
which keeps Dev builds apart from installed Helium and Arcium in the Dock,
LaunchServices, permissions, and preferences. Chromium already separates two
instances by user-data dir, so profiles do not need their own bundles.

`--labeled` gives a profile its own bundle, "Helium Dev - NAME.app", for when
several Dev instances run at once and each needs its own Dock icon and window
owner, for example parallel UI automation. Its identifier ends in a short
hash so App Shim Mach service names stay under macOS's 128-byte limit.

Bundles live next to `Helium.app` in the out dir because a component build's
framework finds its libraries relative to the app's directory.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import uuid

from . import apps, builds
from .common import HeError, Paths, read_json, sha256_bytes, write_json
from .profiles import clone_once

DEV_ID = "net.imput.helium.dev"
DEV_NAME = "Helium Dev"
DEV_FLAGS = ("--enable-ui-devtools", "--use-mock-keychain", "--no-first-run", "--disable-session-crashed-bubble")
ENABLED_FEATURES = ("HeliumFavoritesAndPins",)
DISABLED_FEATURES = ("DialMediaRouteProvider",)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_OWNED_SWITCHES = ("user-data-dir", "profile-directory", "use-mock-keychain")
RECORD = "dev-bundles.json"

# A new profile starts like a lived-in Arcium window: the vertical sidebar,
# Favorites, one Space with Pins and a folder, and a few open tabs. --empty
# skips all of it.
FIXTURE_TABS = ("https://example.com/", "https://en.wikipedia.org/wiki/Web_browser",
                "https://news.ycombinator.com/")


def _link(item_id: str, title: str, url: str) -> dict:
    return {"type": "link", "id": item_id, "title": title, "url": url}


FIXTURE_PREFERENCES = {
    "helium": {
        "browser": {"layout": 2},
        "completed_onboarding": True,
        "favorites": [
            _link("fixture-favorite-google", "Google", "https://www.google.com/"),
            _link("fixture-favorite-github", "GitHub", "https://github.com/"),
            _link("fixture-favorite-youtube", "YouTube", "https://www.youtube.com/"),
            _link("fixture-favorite-maps", "Maps", "https://www.openstreetmap.org/"),
        ],
        "spaces": [{
            "id": "fixture-space",
            "name": "Space",
            "pins": [
                _link("fixture-pin-mdn", "MDN Web Docs", "https://developer.mozilla.org/"),
                _link("fixture-pin-chromium", "Chromium", "https://www.chromium.org/"),
                {"type": "folder", "id": "fixture-pin-reading", "title": "Reading", "collapsed": False,
                 "children": [
                     _link("fixture-pin-verge", "The Verge", "https://www.theverge.com/"),
                     _link("fixture-pin-ars", "Ars Technica", "https://arstechnica.com/"),
                 ]},
            ],
        }],
        "active_space_id": "fixture-space",
    },
    "vertical_tabs": {"collapsed_state": False, "uncollapsed_width": 240},
    "session": {"restore_on_startup": 1},
}


def write_fixture(profile: Path) -> None:
    """Preferences for a new profile; the caller opens FIXTURE_TABS once."""
    default = profile / "Default"
    default.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(default / "Preferences", FIXTURE_PREFERENCES)


def support(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "Application Support"


def profile_dir(name: str | None, *, home: Path | None = None) -> Path:
    """The historic Dev profile, or a named one where the previous tooling kept them."""
    if name is None:
        return support(home) / "net.imput.helium.dev"
    if not _NAME.fullmatch(name):
        raise HeError(f"invalid profile name: {name} (letters, digits, '.', '_', '-'; up to 64)")
    return support(home) / "Helium Development" / "profiles" / "isolated" / name


def seed_source(value: str, home: Path | None = None) -> Path:
    named = {"installed": "net.imput.helium", "dev": "net.imput.helium.dev", "arcium": "Arcium"}
    path = support(home) / named[value] if value in named else Path(value).expanduser()
    if not path.is_dir():
        raise HeError(f"--seed-from profile does not exist: {path}")
    return path


def bundle_identity(label: str | None) -> tuple[str, str, str]:
    """(app name, bundle id, display name) for the shared or a labeled Dev app."""
    if label is None:
        return f"{DEV_NAME}.app", DEV_ID, DEV_NAME
    if not _NAME.fullmatch(label):
        raise HeError(f"invalid label: {label}")
    digest = hashlib.sha256(label.encode()).hexdigest()[:16]
    return f"{DEV_NAME} - {label}.app", f"{DEV_ID}.{digest}", f"{DEV_NAME} - {label}"


def _fingerprint(app: Path) -> str:
    entries = []
    for path in sorted(app.rglob("*")):
        metadata = path.lstat()
        entries.append(f"{path.relative_to(app)}\0{metadata.st_size}\0{metadata.st_mtime_ns}")
    return sha256_bytes("\n".join(entries).encode())


def prepare_bundle(paths: Paths, label: str | None) -> Path:
    """Copy Helium.app into its Dev identity when the build output changed."""
    out = paths.out
    builds.require_completed(out, paths.build_mode)
    source = out / "Helium.app"
    if not apps.executable(source).is_file():
        raise HeError(f"no built Helium.app in {out}; run he build first")
    app_name, bundle_id, display = bundle_identity(label)
    target = out / app_name
    records = read_json(paths.state / RECORD) or {}
    fingerprint = _fingerprint(source)
    key = f"{paths.build_mode}:{app_name}"
    current = target.is_dir() and records.get(key) == fingerprint
    if current:
        try:
            apps.verify_signature(target)
            return target
        except HeError:
            current = False
    if target.exists() and apps.browser_processes_in(target):
        raise HeError(f"{target.name} is running an older build; he stop its profile first")
    suffix = bundle_id[len("net.imput.helium"):]
    staging = out / f".{app_name}.staging-{uuid.uuid4().hex}"
    try:
        apps.copy_app(source, staging)
        apps.rewrite_identity(
            staging,
            lambda value: value if value.endswith(suffix) else value + suffix,
            lambda value: value if value.endswith(" Dev") or value.startswith(DEV_NAME) else value + " Dev",
            {"CFBundleIdentifier": bundle_id, "CFBundleDisplayName": display, "CFBundleName": display},
        )
        apps.sign_ad_hoc(staging)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    records[key] = fingerprint
    write_json(paths.state / RECORD, records)
    return target


def _features(passthrough: list[str]) -> tuple[list[str], list[str], list[str]]:
    enabled, disabled, rest = list(ENABLED_FEATURES), list(DISABLED_FEATURES), []
    for argument in passthrough:
        # Chromium accepts "-switch" and "--switch", and the last duplicate wins.
        key, _, value = argument.lstrip().partition("=")
        name = key.lstrip("-").strip().lower() if key.lstrip().startswith("-") else None
        if name in _OWNED_SWITCHES:
            raise HeError(f"--{name} is set by he run; choose the profile with --profile NAME")
        if name == "enable-features":
            enabled += [v for v in value.split(",") if v]
        elif name == "disable-features":
            disabled += [v for v in value.split(",") if v]
        else:
            rest.append(argument)
    enabled = [v for v in dict.fromkeys(enabled) if v not in disabled]
    return enabled, list(dict.fromkeys(disabled)), rest


def run(paths: Paths, name: str | None, *, new: bool = False, labeled: bool = False,
        seed: str | None = None, empty: bool = False, passthrough: list[str] | None = None,
        home: Path | None = None) -> dict:
    """Launch a Dev app on a profile and return once it owns that profile."""
    if labeled and name is None:
        raise HeError("--labeled needs --profile NAME")
    if new and name is None:
        raise HeError("--new needs --profile NAME")
    builds.require_completed(paths.out, paths.build_mode)
    profile = profile_dir(name, home=home)
    enabled, disabled, rest = _features(passthrough or [])
    apps.require_plain_profile(profile, [support(home) / "net.imput.helium", support(home) / "Arcium"])
    if apps.lock_state(profile)[0] == "foreign":
        raise HeError(f"profile {profile} is locked by another host; remove its SingletonLock if nothing uses it")
    if (owner := apps.profile_owner(profile)) is not None:
        raise HeError(f"profile {profile} is already running (pid {owner}); he stop --profile {name or ''} first".rstrip())
    if new and profile.exists():
        raise HeError(f"profile {name} already exists: {profile}; pick a new name")
    if seed is not None and empty:
        raise HeError("--empty and --seed-from both choose a new profile's contents; pick one")
    first_tabs: list[str] = []
    if not profile.exists():
        if seed is not None:
            clone_once(seed_source(seed, home), profile)
        else:
            profile.mkdir(mode=0o700, parents=True)
            if not empty and name is not None:
                write_fixture(profile)
                first_tabs = list(FIXTURE_TABS)
    elif seed is not None or empty:
        raise HeError(f"profile {profile} already exists; --seed-from and --empty only apply to a new profile")
    bundle = prepare_bundle(paths, name if labeled else None)
    executable = apps.executable(bundle)
    logs = (home or Path.home()) / "Library" / "Logs" / "Arcium"
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    log = logs / f"dev-{name or 'default'}.log"
    with log.open("ab") as handle:
        process = subprocess.Popen(
            [str(executable), f"--user-data-dir={profile}", *DEV_FLAGS,
             f"--enable-features={','.join(enabled)}", f"--disable-features={','.join(disabled)}", *rest,
             *first_tabs],
            stdin=subprocess.DEVNULL, stdout=handle, stderr=handle, start_new_session=True,
        )
    if not apps.wait_for_owner(profile, process.pid, executable, timeout=30):
        raise HeError(f"{bundle.name} did not take profile {profile}; see {log}")
    return {"pid": process.pid, "app": str(bundle), "profile": str(profile), "log": str(log),
            "build_mode": paths.build_mode, "diagnostics": paths.build_mode == "diagnostics",
            "output_dir": str(paths.out)}


def stop(name: str | None, *, home: Path | None = None, timeout: float = 15.0) -> str:
    profile = profile_dir(name, home=home)
    owner = apps.profile_owner(profile)
    if owner is None:
        return f"profile {profile} is not running"
    path = apps.process_path(owner) or ""
    if f"/{DEV_NAME}.app/" not in path and f"/{DEV_NAME} - " not in path:
        raise HeError(f"profile {profile} is owned by {path or f'pid {owner}'}, not a Dev app; refusing to stop it")
    # A stale lock's pid can be reused by another browser; require the process
    # to have been started on this profile, and recheck just before signalling.
    if not apps.uses_profile(owner, profile):
        raise HeError(f"pid {owner} holds {profile}'s lock but was not started on it; refusing to stop it")
    if apps.profile_owner(profile) != owner or apps.process_path(owner) != path:
        raise HeError("the Dev app changed while stopping; retry")
    os.kill(owner, signal.SIGTERM)
    if not apps.wait_for_exit([owner], timeout):
        raise HeError(f"pid {owner} did not quit within {timeout:.0f}s; check for an open dialog")
    return f"stopped pid {owner}"


def describe(result: dict) -> str:
    return json.dumps(result, indent=2, sort_keys=True)
