#!/usr/bin/env python3
"""Prove Linux remote execution produces an arm64 macOS object, outside Chromium outputs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

STATE = Path(__file__).resolve().parents[2] / "build/gcp-remote"
CLANG = "third_party/llvm-build/Release+Asserts_linux/bin/clang"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True, help="Existing Chromium source root; read only")
    parser.add_argument("--endpoint", default="127.0.0.1:50051")
    args = parser.parse_args()
    src = args.src.resolve()
    siso = src / "third_party/siso/cipd/siso"
    update = src / "tools/clang/scripts/update.py"
    if not siso.is_file() or not update.is_file():
        parser.error("--src must contain the pinned Siso and Clang update script")
    STATE.mkdir(parents=True, exist_ok=True)
    toolchain = STATE / "llvm-linux"
    # This updater writes only to the explicit private output directory.
    subprocess.run([sys.executable, str(update), "--host-os=linux", "--output-dir=" + str(toolchain)], check=True)
    trial = Path(tempfile.mkdtemp(prefix="smoke-", dir=STATE))
    (trial / ".gclient").write_text('solutions = [{"name": "src", "url": "", "managed": False}]\n')
    root = trial / "src"
    config = root / "build/config/siso"
    config.mkdir(parents=True)
    compiler = root / CLANG
    compiler.parent.mkdir(parents=True)
    os.link((toolchain / "bin/clang").resolve(), compiler)
    (root / "smoke.cc").write_text(f"// {uuid.uuid4().hex}\nint arcium_remote_smoke() {{ return 42; }}\n")
    configuration = {
        "platforms": {"default": {"cpu_count": "1"}},
        "input_deps": {},
        "rules": [{"name": "smoke", "action": "smoke_cc", "remote": True,
                   "inputs": ["smoke.cc", CLANG], "timeout": "2m"}],
        "executables": [CLANG],
    }
    (config / "main.star").write_text(
        'load("@builtin//encoding.star", "json")\n'
        'load("@builtin//struct.star", "module")\n\n'
        'def init(ctx):\n'
        f'    return module("config", step_config=json.encode({configuration!r}), filegroups={{}}, handlers={{}})\n')
    output = root / "out/Smoke"
    output.mkdir(parents=True)
    (output / "build.ninja").write_text(
        "rule smoke_cc\n"
        f"  command = ../../{CLANG} --target=arm64-apple-macos14 -c ../../smoke.cc -o $out\n"
        "build smoke.o: smoke_cc ../../smoke.cc\n")
    command = [str(siso), "ninja", "-C", "out/Smoke", "-project=", "-reapi_instance=main",
               "-reapi_address=" + args.endpoint, "-reapi_insecure", "-strict_remote",
               "-cache_enable_read=false", "-local_jobs=1", "-remote_jobs=1", "smoke.o"]
    result = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=300)
    (trial / "siso.log").write_text(result.stdout)
    print(result.stdout, end="")
    if result.returncode:
        print(f"Smoke failed; evidence: {trial}", file=sys.stderr)
        return result.returncode
    kind = subprocess.check_output(["file", str(output / "smoke.o")], text=True).strip()
    if "Mach-O" not in kind or "arm64" not in kind:
        raise RuntimeError("Remote compiler produced an unexpected object: " + kind)
    evidence = {"object": str(output / "smoke.o"), "file": kind, "strict_remote": True,
                "cache_read": False, "compiler_host": "Linux x86_64", "endpoint": args.endpoint}
    (trial / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
