#!/usr/bin/env python3
"""Prepare one Siso backend for the selected generated build lane."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping


LOCAL_RBE_INSTANCE = "projects/rbe-chrome-untrusted/instances/default_instance"
_REMOTE_ENVIRONMENT = (
    "SISO_PROJECT", "SISO_REAPI_ADDRESS", "SISO_REAPI_CAS_ADDRESS", "SISO_REAPI_INSTANCE",
    "RBE_service_no_security",
)


class BackendError(ValueError):
    """The requested backend differs from the prepared build inputs."""


@dataclass(frozen=True)
class BuildBackend:
    name: str
    address: str
    instance: str
    config: str
    no_security: str = "false"

    def identity(self) -> dict[str, str]:
        return asdict(self)

    def environment(self, current: Mapping[str, str]) -> dict[str, str]:
        environment = dict(current)
        for key in _REMOTE_ENVIRONMENT:
            environment.pop(key, None)
        if self.name == "nativelink":
            environment.update({
                "SISO_REAPI_ADDRESS": self.address,
                "SISO_REAPI_INSTANCE": self.instance,
                "RBE_service_no_security": self.no_security,
            })
        return environment


def selected_backend(environment: Mapping[str, str] | None = None) -> BuildBackend:
    environment = os.environ if environment is None else environment
    no_security = environment.get("RBE_service_no_security", "false")
    if no_security not in {"true", "false"}:
        raise BackendError("RBE_service_no_security must be true or false")
    address = environment.get("SISO_REAPI_ADDRESS", "")
    if not address:
        return BuildBackend("local", "", "default_instance", "google.star")
    instance = environment.get("SISO_REAPI_INSTANCE") or "main"
    for name, value in (("SISO_REAPI_ADDRESS", address), ("SISO_REAPI_INSTANCE", instance)):
        if any(character.isspace() or ord(character) < 32 or character == "=" for character in value):
            raise BackendError(f"{name} must be a single Siso configuration value")
    return BuildBackend("nativelink", address, instance, "nativelink.star", no_security)


def validate_gn_backend(source: Path, backend: BuildBackend) -> None:
    try:
        contents = (source / "out/Default/args.gn").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BackendError("GN arguments are missing; run he configure --refresh-defaults") from error
    declarations = [line.partition("#")[0].strip() for line in contents.splitlines()]
    remote = [line for line in declarations if re.match(r"use_remoteexec\b", line)]
    expected = backend.name == "nativelink"
    if remote and (len(remote) != 1 or not re.fullmatch(r"use_remoteexec\s*=\s*(true|false)", remote[0])):
        raise BackendError("use_remoteexec must be one literal boolean in args.gn")
    enabled = bool(remote and re.fullmatch(r"use_remoteexec\s*=\s*true", remote[0]))
    if enabled != expected:
        raise BackendError("GN backend differs; run he configure --refresh-defaults")
    if expected and any(re.match(r"cc_wrapper\b", line) for line in declarations):
        raise BackendError("NativeLink requires args.gn without cc_wrapper; run he configure --refresh-defaults")


def recipe_paths(source: Path, backend: BuildBackend) -> dict[str, Path]:
    siso = source / "build/config/siso"
    paths = {
        "configure-siso": siso / "configure_siso.py",
        "backend-config": siso / "backend_config" / backend.config,
    }
    if backend.name == "nativelink":
        paths.update({
            "clang-update": source / "tools/clang/scripts/update.py",
            "clang-wrapper": source / "buildtools/reclient_cfgs/chromium-browser-clang/clang_remote_wrapper",
            "rewrapper-config": source / "buildtools/reclient_cfgs/chromium-browser-clang/rewrapper_mac.cfg",
        })
    return paths


def output_paths(source: Path, backend: BuildBackend) -> dict[str, Path]:
    siso = source / "build/config/siso"
    paths = {
        "build/config/siso/.sisoenv": siso / ".sisoenv",
        "build/config/siso/backend_config/backend.star": siso / "backend_config/backend.star",
    }
    if backend.name == "nativelink":
        toolchain = source / "third_party/llvm-build/Release+Asserts_linux"
        paths.update({
            "linux-clang": toolchain / "bin/clang",
            "linux-clang-revision": toolchain / "cr_build_revision",
        })
    return paths


def validate_outputs(source: Path, backend: BuildBackend) -> None:
    try:
        siso = source / "build/config/siso"
        entries = dict(line.split("=", 1) for line in (siso / ".sisoenv").read_text().splitlines())
        expected = {"SISO_REAPI_INSTANCE": backend.instance}
        if backend.name == "nativelink":
            expected["SISO_REAPI_ADDRESS"] = backend.address
        else:
            expected["SISO_PROJECT"] = "rbe-chrome-untrusted"
        if entries != expected:
            raise BackendError("generated .sisoenv differs from the selected backend; run he configure")
        config = siso / "backend_config"
        if (config / "backend.star").read_bytes() != (config / backend.config).read_bytes():
            raise BackendError("generated backend.star differs from the selected backend; run he configure")
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, BackendError):
            raise
        raise BackendError("Siso backend configuration is missing or malformed; run he configure") from error


def prepare_backend(source: Path, backend: BuildBackend) -> None:
    # configure_siso writes .sisoenv and removes backend.star before copying
    # the selected recipe. Check every prerequisite before that mutation.
    for name, path in recipe_paths(source, backend).items():
        if path.is_symlink() or not path.is_file():
            raise BackendError(f"{name} prerequisite is missing or not a regular file: {path}")
    validate_gn_backend(source, backend)
    environment = backend.environment(os.environ)
    if backend.name == "nativelink":
        subprocess.run([
            sys.executable, str(source / "tools/clang/scripts/update.py"),
            "--host-os=linux",
            "--output-dir=" + str(source / "third_party/llvm-build/Release+Asserts_linux"),
        ], cwd=source, env=environment, check=True)
        arguments = [
            "--reapi_address=" + backend.address,
            "--reapi_instance=" + backend.instance,
            "--reapi_backend_config_path=" + backend.config,
        ]
    else:
        arguments = ["--rbe_instance", LOCAL_RBE_INSTANCE]
    # Regenerate both files, including when a previous configuration selected
    # NativeLink. Their existence alone cannot identify the current backend.
    subprocess.run([
        sys.executable, str(source / "build/config/siso/configure_siso.py"), *arguments,
    ], cwd=source, env=environment, check=True)
    validate_outputs(source, backend)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        prepare_backend(arguments.source_dir.expanduser().resolve(), selected_backend())
    except (BackendError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
