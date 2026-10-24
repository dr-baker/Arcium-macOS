"""Arcium's app identity, shared by the release packager and `he arcium`."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

from he import apps
from he.common import HeError

ARCIUM_BUNDLE_ID = "net.imput.arcium"
ARCIUM_NAME = "Arcium"
# Chromium picks ~/Library/Application Support/<CrProductDirName> for Dock launches.
PROFILE_DIR_NAME = "Arcium"
SIGNING_IDENTITY_ENV = "ARCIUM_CODESIGN_IDENTITY"
ENTITLEMENTS = Path(__file__).resolve().parents[2] / "entitlements"
INITIAL_PREFERENCES = Path(__file__).resolve().parents[2] / "resources/preview/initial-preferences.json"
_MACHO = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
          b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


class ArciumError(HeError):
    """The Arcium app cannot be packaged or installed safely."""


def _rewrite_id(value: str) -> str:
    prefix = "net.imput.helium"
    if value == prefix:
        return ARCIUM_BUNDLE_ID
    return ARCIUM_BUNDLE_ID + value[len(prefix):] if value.startswith(prefix + ".") else value


def rewrite_metadata(app: Path) -> int:
    """Set Arcium's identity and first-run defaults before the copy is signed."""
    try:
        count = apps.rewrite_identity(app, _rewrite_id, None, {
            "CFBundleIdentifier": ARCIUM_BUNDLE_ID,
            "CFBundleDisplayName": ARCIUM_NAME,
            "CFBundleName": ARCIUM_NAME,
            "CrProductDirName": PROFILE_DIR_NAME,
        })
        resources = app / "Contents/Resources"
        if resources.is_symlink():
            raise ArciumError("the staged app Resources directory must not be a symbolic link")
        resources.mkdir(parents=True, exist_ok=True)
        target = resources / "initial_preferences"
        target.unlink(missing_ok=True)
        with target.open("xb") as handle:
            handle.write(INITIAL_PREFERENCES.read_bytes())
        return count
    except ArciumError:
        raise
    except HeError as error:
        raise ArciumError(str(error)) from error


def verify_identity(app: Path) -> dict:
    info = apps.read_plist(app / "Contents" / "Info.plist")
    if info.get("CFBundleIdentifier") != ARCIUM_BUNDLE_ID:
        raise ArciumError(f"{app} has bundle identifier {info.get('CFBundleIdentifier')}, not {ARCIUM_BUNDLE_ID}")
    if info.get("CrProductDirName") != PROFILE_DIR_NAME:
        raise ArciumError(f"{app} would open the wrong profile directory; repackage it")
    return info


def copy_component_libraries(out_dir: Path, app: Path) -> int:
    """Make a component build self-contained: its dylibs go in Frameworks."""
    libraries = apps.component_libraries(out_dir)
    frameworks = app / "Contents" / "Frameworks"
    if libraries and not frameworks.is_dir():
        raise ArciumError(f"{app} has no Frameworks directory")
    for library in libraries:
        shutil.copy2(library, frameworks / library.name)
    return len(libraries)


# Signing -------------------------------------------------------------------------

def signing_identities() -> list[str]:
    result = subprocess.run(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
                            capture_output=True, text=True, check=False)
    return re.findall(r'^\s*\d+\)\s+[0-9A-F]+\s+"(.+)"\s*$', result.stdout, re.MULTILINE)


def signing_identity() -> str:
    """A stable identity. Keychain items for the persistent profile are bound to
    the signature, so an ad hoc signature would lose access to saved data."""
    requested = os.environ.get(SIGNING_IDENTITY_ENV, "").strip()
    if (requested == "-" and os.environ.get("HELIUM_TEST_MODE") == "1"
            and os.environ.get("HELIUM_TEST_ALLOW_AD_HOC") == "1"):
        return "-"  # stub apps in tests only
    identities = signing_identities()
    if requested:
        if requested not in identities:
            raise ArciumError(f"{SIGNING_IDENTITY_ENV} names no available signing identity: {requested}")
        return requested
    developer = [value for value in identities if value.startswith("Developer ID Application:")]
    if len(developer) == 1:
        return developer[0]
    if not developer:
        raise ArciumError("Arcium needs a Developer ID signing identity (or set "
                          f"{SIGNING_IDENTITY_ENV}); an ad hoc signature would lose Keychain access")
    raise ArciumError(f"several Developer ID identities are available; set {SIGNING_IDENTITY_ENV}")


def _targets(app: Path) -> list[Path]:
    """Nested bundles and Mach-O files, deepest first, without following links."""
    targets = [app]
    for directory, subdirs, files in os.walk(app):
        parent = Path(directory)
        subdirs[:] = [name for name in subdirs if not (parent / name).is_symlink()]
        targets += [parent / name for name in subdirs if Path(name).suffix in {".app", ".framework", ".xpc", ".appex"}]
        for name in files:
            path = parent / name
            if not path.is_symlink() and path.is_file():
                with path.open("rb") as handle:
                    if handle.read(4) in _MACHO:
                        targets.append(path)
    return sorted(set(targets), key=lambda path: (-len(path.parts), str(path)))


def _entitlements(target: Path, app: Path) -> Path | None:
    """JIT entitlements belong only to the renderer and GPU helpers."""
    if target == app:
        name = "app-entitlements.plist"
    elif target.name.endswith(" Helper (Renderer).app"):
        name = "helper-renderer-entitlements.plist"
    elif target.name.endswith(" Helper (GPU).app"):
        name = "helper-gpu-entitlements.plist"
    elif target.name.endswith(" Helper.app") or target.name.endswith(" Framework.framework"):
        name = "helper-entitlements.plist"
    else:
        return None
    return ENTITLEMENTS / name


def sign(app: Path, identity: str) -> None:
    for target in _targets(app):
        command = ["--force", "--sign", identity]
        if identity != "-":
            command += ["--timestamp", "--options", "runtime"]
        if (entitlements := _entitlements(target, app)) is not None and entitlements.is_file():
            command += ["--entitlements", str(entitlements)]
        apps.codesign([*command, str(target)], f"signing {target.name}")
    apps.verify_signature(app)
