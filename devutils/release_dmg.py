#!/usr/bin/env python3
"""Package a signed Arcium.app in the blush drag-to-Applications disk image."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


RESOURCES = Path(__file__).resolve().parents[1] / "resources"


def create_disk_image(app: Path, destination: Path, identity: str | None = None) -> None:
    app_input = app.expanduser()
    destination_input = destination.expanduser()
    if app_input.is_symlink() or not app_input.is_dir() or app_input.name != "Arcium.app":
        raise ValueError("source must be a plain Arcium.app directory")
    if destination_input.exists() or destination_input.is_symlink():
        raise ValueError("disk image destination already exists")
    app = app_input.resolve()
    destination = destination_input.resolve()
    if app in destination.parents:
        raise ValueError("disk image destination must be outside the app")
    if not shutil.which("appdmg"):
        raise RuntimeError("appdmg is required: npm install -g appdmg@0.6.6")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    config = json.loads((RESOURCES / "dmg.json").read_text())
    config["icon"] = str(app / "Contents/Resources/app.icns")
    config["background"] = str(RESOURCES / config["background"])
    config["contents"][0]["path"] = str(app)
    config["contents"][0]["name"] = "Arcium.app"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="arcium-dmg-", dir=destination.parent) as directory:
        staging = Path(directory)
        specification = staging / "dmg.json"
        specification.write_text(json.dumps(config, indent=2) + "\n")
        image = staging / "Arcium.dmg"
        subprocess.run(["appdmg", str(specification), str(image)], check=True)
        if identity:
            subprocess.run(["codesign", "--force", "--sign", identity, "--timestamp",
                            "--identifier", "net.imput.arcium", str(image)], check=True)
            subprocess.run(["codesign", "--verify", "--strict", str(image)], check=True)
        # Publish without replacing a destination created while appdmg was running.
        os.link(image, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--identity")
    args = parser.parse_args()
    create_disk_image(args.app, args.destination, args.identity)


if __name__ == "__main__":
    main()
