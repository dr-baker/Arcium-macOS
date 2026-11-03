#!/usr/bin/env python3
"""Build the standalone AppKit motion experiment; never invokes Chromium tooling."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / ".build"
APP = BUILD / "PiP Motion Lab.app"
EXECUTABLE = APP / "Contents/MacOS/PiPMotionLab"


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Launch after building and checking")
    args = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    # Avoid replacing this experiment's executable while its process is alive.
    processes = subprocess.check_output(["/bin/ps", "-axo", "pid=,command="], text=True)
    if any(line.strip().split(maxsplit=1)[-1].startswith(str(EXECUTABLE))
           for line in processes.splitlines() if line.strip()):
        parser.error("Quit PiP Motion Lab before rebuilding it.")
    run("/usr/bin/clang++", "-std=c++20", "-Wall", "-Wextra", "-pedantic",
        ROOT / "MotionTests.cpp", "-o", BUILD / "MotionTests")
    run(BUILD / "MotionTests")
    EXECUTABLE.parent.mkdir(parents=True, exist_ok=True)
    run("/usr/bin/clang++", "-std=c++20", "-O2", "-Wall", "-Wextra",
        "-Wno-unused-parameter", "-fobjc-arc", "-fmodules",
        f"-fmodules-cache-path={BUILD / 'module-cache'}", "-framework", "AppKit",
        "-framework", "QuartzCore", ROOT / "main.mm", "-o", EXECUTABLE)
    with (APP / "Contents/Info.plist").open("wb") as file:
        plistlib.dump({
            "CFBundleIdentifier": "dev.arcium.pip-motion-lab",
            "CFBundleName": "PiP Motion Lab", "CFBundleDisplayName": "PiP Motion Lab",
            "CFBundleExecutable": "PiPMotionLab", "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1", "CFBundleShortVersionString": "0.1",
            "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
        }, file)
    run("/usr/bin/codesign", "--force", "--sign", "-", APP)
    print(APP)
    if args.run:
        with (BUILD / "app.log").open("ab") as log:
            process = subprocess.Popen([str(EXECUTABLE), "--settings", str(BUILD / "settings.json")],
                                       cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
        (BUILD / "launch.json").write_text(json.dumps({"pid": process.pid, "app": str(APP)}, indent=2) + "\n")
        print(f"Launched PID {process.pid}; live settings: {BUILD / 'settings.json'}")


if __name__ == "__main__":
    main()
