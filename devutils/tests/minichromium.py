"""A tiny stand-in for a Helium checkout and Chromium build dir.

It has the same shape `dev.sh` expects: an outer git repository with a
`helium-chromium/` core catalog, and a build dir whose `src/` holds a few C++
files, a real Ninja graph with depfiles, and a depot_tools `autoninja.py` shim.
Patches are applied with the real Quilt, so `he` commands run end to end in
well under a second each.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

TOOLS = Path(__file__).resolve().parents[2]

PRISTINE = {
    "h.h": "#pragma once\nint f();\n",
    "a.cc": '#include "h.h"\nint a() { return f(); }\n',
    "b.cc": "int b() { return 1; }\n",
    "p.cc": "int f() { return 0; }\n",
    "long.cc": "".join(f"int line{i}() {{ return {i}; }}\n" for i in range(20)),
}

# Core patch P touches h.h and p.cc; macOS patch Q touches a.cc and b.cc.
CORE_PATCH = "helium/core/p.patch"
OUTER_PATCH = "personal/q.patch"
LONG_PATCH = "personal/long.patch"
PATCHED = {
    CORE_PATCH: {"h.h": "#pragma once\nint f();\nint g();\n", "p.cc": "int f() { return 0; }\n// p\n"},
    OUTER_PATCH: {"a.cc": '#include "h.h"\nint a() { return f() + 1; }\n', "b.cc": "int b() { return 2; }\n"},
    LONG_PATCH: {"long.cc": PRISTINE["long.cc"].replace("return 10;", "return 100;")},
}

BUILD_NINJA = """\
rule cc
  command = clang++ -MMD -MF $out.d -c $in -o $out
  depfile = $out.d
  deps = gcc
build obj/a.o: cc ../../a.cc
build obj/b.o: cc ../../b.cc
build obj/p.o: cc ../../p.cc
build obj/long.o: cc ../../long.cc
build chrome: phony obj/a.o obj/b.o obj/p.o obj/long.o
build chromedriver: phony obj/p.o
"""

AUTONINJA = """\
import os, sys
args = [a for a in sys.argv[1:]]
os.execvp("ninja", ["ninja", *args])
"""


def unified(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}", n=3,
    )
    return "".join(lines)


def run(argv, cwd=None, env=None, check=True):
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(f"{argv} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result


class MiniChromium:
    def __init__(self) -> None:
        # Under /tmp so the build dir's temp path stays short, as on a real volume.
        self.root = Path(tempfile.mkdtemp(prefix="mc-", dir="/tmp")).resolve()
        self.worktree = self.root / "checkout"
        self.build_dir = self.root / "build"
        self.src = self.build_dir / "src"
        self.out = self.src / "out" / "Default"
        self.home = self.root / "home"
        self.home.mkdir()
        self._make_checkout()
        self._make_build_dir()

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    # Layout ---------------------------------------------------------------

    def _make_checkout(self) -> None:
        w = self.worktree
        core = w / "helium-chromium"
        for directory in (w / "patches", core / "patches", w / "devutils", w / "resources", core / "resources"):
            directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TOOLS / "env.sh", w / "env.sh")
        shutil.copy2(TOOLS / "devutils" / "setup_python.sh", w / "devutils" / "setup_python.sh")
        (w / "requirements-dev.txt").write_text("")
        (core / "chromium_version.txt").write_text("151.0.7922.71\n")
        (core / "version.txt").write_text("0\n")
        (core / "revision.txt").write_text("1\n")
        (core / "flags.gn").write_text("is_official_build=true\n")
        (w / "flags.macos.gn").write_text("")
        (w / "revision.txt").write_text("1\n")
        (core / "resources" / "list.txt").write_text("resource\n")
        (w / "resources" / "icon.txt").write_text("icon\n")
        self.write_patch(CORE_PATCH, core=True)
        self.write_patch(OUTER_PATCH, core=False)
        self.write_patch(LONG_PATCH, core=False)
        (core / "patches" / "series").write_text(f"{CORE_PATCH}\n")
        (w / "patches" / "series").write_text(f"# macOS patches\n{OUTER_PATCH}\n{LONG_PATCH}\n")
        run(["git", "init", "-q", "-b", "main"], cwd=w)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=w)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture"], cwd=w)

    def write_patch(self, name: str, core: bool, files: dict[str, str] | None = None) -> Path:
        root = self.worktree / ("helium-chromium/patches" if core else "patches")
        files = PATCHED[name] if files is None else files
        text = "".join(unified(path, PRISTINE[path], after) for path, after in files.items())
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target

    def _make_build_dir(self) -> None:
        self.src.mkdir(parents=True)
        for path, content in PRISTINE.items():
            (self.src / path).write_text(content)
        (self.src / "chrome").mkdir()
        (self.src / "chrome" / "VERSION").write_text("MAJOR=151\nMINOR=0\nBUILD=7922\nPATCH=71\n")
        tools = self.src / "third_party" / "depot_tools"
        tools.mkdir(parents=True)
        (tools / "autoninja.py").write_text(AUTONINJA)
        self.out.mkdir(parents=True)
        (self.out / "build.ninja").write_text(BUILD_NINJA)
        (self.out / "args.gn").write_text("is_component_build=true\n")

    # Driving dev.sh ---------------------------------------------------------

    def env(self, **extra: str) -> dict[str, str]:
        environment = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "HELIUM_DEV_WORKTREE": str(self.worktree),
            "HELIUM_BUILD_DIR": str(self.build_dir),
            "LANG": "C.UTF-8",
        }
        environment.update(extra)
        return environment

    def he(self, *args: str, check: bool = True, **env: str) -> subprocess.CompletedProcess:
        script = f'source "{TOOLS / "dev.sh"}" >/dev/null && he "$@"'
        return run(["bash", "-c", script, "he", *args], env=self.env(**env), check=check)

    def python_he(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return run(
            ["python3", "-m", "he", "--worktree", str(self.worktree), "--build-dir", str(self.build_dir), *args],
            env={**self.env(), "PYTHONPATH": str(TOOLS / "devutils")}, check=check,
        )

    def quilt(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        catalog = (cwd or self.src).parent / ".arcium" / "patches"
        env = {**self.env(), "QUILT_PATCHES": str(catalog), "QUILT_SERIES": "series.merged",
               "QUILT_REFRESH_ARGS": "-p ab --no-timestamps --no-index"}
        return run(["quilt", "--quiltrc", "-", *args], cwd=cwd or self.src, env=env, check=check)

    def stamp_all(self) -> None:
        for name in ("resources", "version", "gn-defaults"):
            self.python_he("stamp", name)

    def ninja(self, *args: str) -> subprocess.CompletedProcess:
        return run(["ninja", "-C", str(self.out), *args])

    def would_rebuild(self) -> set[str]:
        """Object files Ninja would rebuild for `chrome`."""
        output = run(["ninja", "-C", str(self.out), "-n", "-d", "explain", "chrome"]).stderr
        rebuilt = set()
        for line in output.splitlines():
            if "ninja explain: output obj/" in line and "older than most recent input" in line:
                rebuilt.add(line.split("output ", 1)[1].split()[0])
        return rebuilt

    def ready(self) -> None:
        """Merge, push, record stamps, and build once."""
        self.he("merge")
        self.he("push")
        self.stamp_all()
        self.he("build")
