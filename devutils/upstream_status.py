#!/usr/bin/env python3
"""Report upstream drift without changing either checkout or the build directory."""

import argparse
import json
from pathlib import Path
import subprocess


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def patch_content(text):
    """Ignore Quilt headers and hunk positions, but retain context and edits."""
    lines = []
    for line in text.splitlines():
        if line.startswith(("Index: ", "===", "@@")):
            continue
        if line.startswith("--- src.orig/"):
            line = line.replace("--- src.orig/", "--- a/", 1)
        elif line.startswith("+++ src/"):
            line = line.replace("+++ src/", "+++ b/", 1)
        lines.append(line)
    return "\n".join(lines)


def report(root, ref):
    head = git(root, "rev-parse", "HEAD")
    upstream = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    base = git(root, "merge-base", head, upstream)
    local_count, incoming_count = map(int, git(root, "rev-list", "--left-right", "--count", f"{head}...{upstream}").split())
    local = set(git(root, "diff", "--name-only", base, head).splitlines())
    incoming = set(git(root, "diff", "--name-only", base, upstream).splitlines())
    refresh_only, changed = [], []
    for path in sorted(local & incoming):
        if path.endswith(".patch"):
            before = subprocess.run(["git", "-C", str(root), "show", f"{base}:{path}"], capture_output=True, text=True)
            after = subprocess.run(["git", "-C", str(root), "show", f"{head}:{path}"], capture_output=True, text=True)
            if before.returncode == after.returncode == 0 and patch_content(before.stdout) == patch_content(after.stdout):
                refresh_only.append(path)
                continue
        changed.append(path)
    return dict(path=str(root), head=head, upstream=upstream, merge_base=base,
                local_commits=local_count, incoming_commits=incoming_count,
                overlapping_changes=changed, local_patch_refreshes=refresh_only,
                working_tree=git(root, "status", "--porcelain").splitlines())


def inspect(root, ref="upstream/main", fetch=False):
    core = root / "helium-chromium"
    if fetch:
        # The platform's upstream pin may not exist in the configured fork.
        # Fetch each upstream explicitly instead of recursing into origin.
        for repo in (root, core):
            subprocess.run(["git", "-C", str(repo), "fetch", "--no-recurse-submodules", "upstream"], check=True)
    outer_report = report(root, ref)
    core_report = report(core, ref)
    pin = git(root, "ls-tree", outer_report["upstream"], "helium-chromium").split()[2]
    current_version = git(core, "show", f'{core_report["head"]}:chromium_version.txt')
    target_version = git(core, "show", f'{core_report["upstream"]}:chromium_version.txt')
    pin_version = git(core, "show", f"{pin}:chromium_version.txt")
    contains_pin = subprocess.run(["git", "-C", str(core), "merge-base", "--is-ancestor", pin, core_report["upstream"]]).returncode == 0
    return dict(core=core_report, macos=outer_report, chromium_current=current_version,
                chromium_target=target_version, macos_upstream_core_pin=pin,
                macos_upstream_chromium=pin_version, core_contains_macos_pin=contains_pin,
                new_build_directory_required=current_version != target_version,
                fetched=fetch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ref", default="upstream/main")
    parser.add_argument("--fetch", action="store_true", help="refresh both upstream remotes without recursive submodule fetching")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = inspect(args.root.resolve(), args.ref, args.fetch)
    except (subprocess.CalledProcessError, IndexError) as error:
        parser.exit(1, f"Cannot inspect upstream: {error}. Fetch both upstream remotes and verify the platform pin exists in core.\n")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f'Chromium {result["chromium_current"]} -> {result["chromium_target"]}')
        print(f'Mac upstream pins {result["macos_upstream_core_pin"]} on Chromium {result["macos_upstream_chromium"]}')
        for name in ("core", "macos"):
            repo = result[name]
            print(f'{name}: {repo["incoming_commits"]} incoming commits, {len(repo["overlapping_changes"])} overlapping paths, {len(repo["local_patch_refreshes"])} formatting-only patch overlaps')
        if result["new_build_directory_required"]:
            print("Use a new build directory; keep the existing build until replay and compilation pass.")
        if not result["core_contains_macos_pin"]:
            print("Core target does not contain the macOS upstream pin. Choose a compatible pair before merging.")
        print("Path overlap is a planning aid, not proof of merge, patch replay, or build compatibility.")


if __name__ == "__main__":
    main()
