#!/usr/bin/env python3
"""Find source ownership in authoritative patches without preparing a build lane."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import sys

from patch_workspace import (
    PatchWorkspaceError,
    _authoritative_state,
    generated_root,
    validate_catalog_snapshot,
)
from quilt_state import QuiltStateError, inspect_quilt_state, read_patch_list


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _source_path(header: str) -> str | None:
    # Unified headers separate timestamps with a tab. Preserve unquoted spaces.
    token = header.split("\t", 1)[0] if "\t" in header else header
    if token.startswith('"'):
        # Git quotes UTF-8 bytes as octal escapes under core.quotePath.
        token = re.sub(r"(?:\\[0-7]{3})+", lambda match: bytes(int(part, 8) for part in match.group()[1:].split("\\")).decode("utf-8", errors="surrogateescape"), token)
        fields = [ast.literal_eval(token)]
    else:
        fields = [re.split(r"\s+\d{4}-\d{2}-\d{2}\s", token, maxsplit=1)[0]]
    if not fields or fields[0] == "/dev/null":
        return None
    value = fields[0]
    for prefix in ("a/", "b/", "src/", "src.orig/"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        raise PatchWorkspaceError(f"unsafe source path in patch header: {value}")
    return str(path)


def _files(content: bytes) -> list[dict[str, object]]:
    """Read unified hunks, retaining both sides' source and patch line numbers."""
    lines = content.decode("utf-8", errors="replace").splitlines()
    files: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    old_line = new_line = old_remaining = new_remaining = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        # Count hunk lines before considering headers. Source text may itself
        # start with --- or +++, and must not be mistaken for a new file.
        if old_remaining or new_remaining:
            kind = {"+": "added", "-": "removed", " ": "context"}.get(line[:1])
            if kind and current is not None:
                entry = {
                    "kind": kind,
                    "text": line[1:],
                    "patch_line": index + 1,
                    "old_line": old_line if kind != "added" else None,
                    "new_line": new_line if kind != "removed" else None,
                }
                current["lines"].append(entry)
                if kind != "added":
                    old_line += 1
                    old_remaining -= 1
                if kind != "removed":
                    new_line += 1
                    new_remaining -= 1
            elif line != "\\ No newline at end of file":
                raise PatchWorkspaceError(f"invalid unified hunk at patch line {index + 1}")
        elif line.startswith("diff --git "):
            fields = re.findall(r'"(?:[^"\\]|\\.)*"|\S+', line)
            if len(fields) != 4:
                # Git leaves ordinary spaces unquoted in diff --git headers.
                paths = line[len("diff --git "):].split(" b/")
                if len(paths) != 2 or not paths[0].startswith("a/"):
                    raise PatchWorkspaceError(f"ambiguous Git file header at patch line {index + 1}")
                fields = ["diff", "--git", paths[0], "b/" + paths[1]]
            old_path = _source_path(fields[2])
            new_path = _source_path(fields[3])
            current = {"sourcepath": new_path, "previous_sourcepath": old_path if old_path != new_path else None, "lines": [], "fallback": True}
            files.append(current)
        elif line.startswith("Index: "):
            current = {"sourcepath": _source_path(line[7:]), "previous_sourcepath": None, "lines": [], "fallback": True}
            files.append(current)
        elif line.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
            old_path = _source_path(line[4:])
            new_path = _source_path(lines[index + 1][4:])
            path = new_path or old_path
            if path is None:
                raise PatchWorkspaceError("patch file has no source path")
            header = {"sourcepath": path, "previous_sourcepath": old_path if old_path != path else None, "lines": [], "fallback": False}
            if current is not None and current["fallback"]:
                # Replace a preceding Git/Index fallback with the unified paths.
                current.update(header)
            else:
                current = header
                files.append(current)
            index += 1
        elif match := _HUNK.match(line):
            if current is None:
                raise PatchWorkspaceError(f"hunk has no file header at patch line {index + 1}")
            old_line, old_count, new_line, new_count = match.groups()
            old_line, new_line = int(old_line), int(new_line)
            old_remaining = int(old_count) if old_count is not None else 1
            new_remaining = int(new_count) if new_count is not None else 1
            heading = line[match.end():].strip()
            if heading:
                current["lines"].append({"kind": "heading", "text": heading, "patch_line": index + 1, "old_line": None, "new_line": None})
        elif current is not None and line.startswith(("+", "-")) and line != "-- ":
            raise PatchWorkspaceError(f"source change outside a unified hunk at patch line {index + 1}")
        index += 1
    if old_remaining or new_remaining:
        raise PatchWorkspaceError("patch ends before the unified hunk is complete")
    return files


def _query_mode(query: str, mode: str) -> str:
    if not query or "\n" in query or "\r" in query:
        raise PatchWorkspaceError("query must be one nonempty line")
    if mode == "auto":
        mode = "glob" if any(character in query for character in "*?[") else "path" if "/" in query else "text"
    if mode in {"path", "glob"}:
        path = PurePosixPath(query)
        if path.is_absolute() or ".." in path.parts:
            raise PatchWorkspaceError("source path queries must be relative to Chromium src, without '..'")
    return mode


def _lane(authoritative: dict[str, object], build_root: Path | None, source: Path | None) -> tuple[dict[str, object], tuple[str, ...] | None]:
    lane: dict[str, object] = {"build_root": str(build_root) if build_root else None, "generated_catalog": "unselected", "quilt_status": "unavailable", "top": None}
    applied = None
    if build_root is None:
        return lane, applied
    root = generated_root(build_root)
    lane["generated_patch_root"] = str(root)
    if not root.exists():
        lane["generated_catalog"] = "missing"
        lane["catalog_detail"] = "selected lane has no generated patch catalog"
    else:
        try:
            validate_catalog_snapshot(root, authoritative)
            lane["generated_catalog"] = "current"
        except (OSError, UnicodeError, PatchWorkspaceError) as error:
            lane["generated_catalog"] = "stale"
            lane["catalog_detail"] = str(error)
    if source is None:
        return lane, applied
    lane["source"] = str(source)
    if not (source / ".pc").is_dir():
        lane["quilt_detail"] = "selected source has no Quilt metadata"
        return lane, applied
    try:
        ledger = source / ".pc" / "applied-patches"
        if ledger.exists():
            observed = read_patch_list(ledger)
            lane["top"] = observed[-1] if observed else None
        report = inspect_quilt_state(source, root)
        lane["top"] = report.comparison.applied[-1] if report.comparison.applied else None
        report.comparison.require_valid_prefix()
        lane["quilt_status"] = "complete" if report.comparison.complete else "partial" if report.comparison.applied else "popped"
        lane["applied_count"] = len(report.comparison.applied)
        if lane["generated_catalog"] == "current":
            applied = report.comparison.applied
    except (OSError, UnicodeError, QuiltStateError) as error:
        lane["quilt_status"] = "invalid"
        lane["quilt_detail"] = str(error)
    return lane, applied


def locate(worktree: Path, query: str, *, mode: str = "auto", build_root: Path | None = None, source: Path | None = None, limit: int = 40, ignore_case: bool = False) -> dict[str, object]:
    """Search series entries only. Neither source copies nor generated patches own results."""
    if not 1 <= limit <= 200:
        raise PatchWorkspaceError("limit must be between 1 and 200 patch/file matches")
    worktree = worktree.expanduser().resolve()
    build_root = build_root.expanduser().resolve() if build_root else None
    source = source.expanduser().resolve() if source else None
    mode = _query_mode(query, mode)
    authoritative = _authoritative_state(worktree)
    lane, applied = _lane(authoritative, build_root, source)
    needle = query.casefold() if ignore_case else query
    owners = authoritative["owners"]
    names = (*authoritative["core_names"], *authoritative["outer_names"])
    if len(set(names)) != len(names):
        raise PatchWorkspaceError("authoritative patch catalogs contain duplicate entries")
    matches: list[dict[str, object]] = []
    for position, name in enumerate(names, start=1):
        owner = owners[name]
        patch_root = worktree / "helium-chromium" / "patches" if owner == "core" else worktree / "patches"
        try:
            files = _files(authoritative["contents"][name])
        except (ValueError, SyntaxError, PatchWorkspaceError) as error:
            raise PatchWorkspaceError(f"{patch_root / name}: {error}") from error
        for file in files:
            paths = [file["sourcepath"]]
            if file["previous_sourcepath"]:
                paths.append(file["previous_sourcepath"])
            candidates = [path.casefold() if ignore_case else path for path in paths]
            if mode == "text":
                hits = [line for line in file["lines"] if needle in (line["text"].casefold() if ignore_case else line["text"])]
            else:
                matched = any(needle == path if mode == "path" else fnmatch.fnmatchcase(path, needle) for path in candidates)
                hits = file["lines"] if matched else []
                if not matched:
                    continue
            if mode == "text" and not hits:
                continue
            generated_state = "unknown" if applied is None else "top" if lane["top"] == name else "applied" if name in applied else "pending"
            matches.append({
                "sourcepath": file["sourcepath"],
                "previous_sourcepath": file["previous_sourcepath"],
                "owner": owner,
                "patch": name,
                "authoritative_patch": str(patch_root / name),
                "series_position": position,
                "generated_source": str(source / file["sourcepath"]) if source else None,
                "generated_source_exists": (source / file["sourcepath"]).is_file() if source else None,
                "generated_patch_state": generated_state,
                "counts": {kind: sum(line["kind"] == kind for line in hits) for kind in ("added", "context", "removed")},
                "matching_hunk_headings": sum(line["kind"] == "heading" for line in hits),
                "excerpts": [{**line, "text": line["text"][:240], "text_truncated": len(line["text"]) > 240} for line in hits[:3]],
                "omitted_excerpts": max(0, len(hits) - 3),
            })
    matches.sort(key=lambda item: (item["sourcepath"], item["series_position"]))
    groups: list[dict[str, object]] = []
    for item in matches[:limit]:
        if not groups or groups[-1]["sourcepath"] != item["sourcepath"]:
            groups.append({"sourcepath": item["sourcepath"], "owners": []})
        groups[-1]["owners"].append(item)
    return {"schema_version": 1, "query": query, "mode": mode, "ignore_case": ignore_case, "worktree": str(worktree), "lane": lane, "total_patch_file_matches": len(matches), "omitted_patch_file_matches": max(0, len(matches) - limit), "groups": groups}


def format_report(report: dict[str, object]) -> str:
    lane = report["lane"]
    lines = [f"Authoritative {report['mode']} lookup: {report['query']}", f"Selected lane catalog: {lane['generated_catalog']}; Quilt: {lane['quilt_status']}; top: {lane['top'] or '(none)'}"]
    for key in ("catalog_detail", "quilt_detail"):
        if lane.get(key):
            lines.append(str(lane[key]))
    for group in report["groups"]:
        lines.append(f"\n{group['sourcepath']}")
        for owner in group["owners"]:
            counts = ", ".join(f"{kind} {count}" for kind, count in owner["counts"].items() if count)
            if owner["matching_hunk_headings"]:
                counts = ", ".join(filter(None, (counts, f"headings {owner['matching_hunk_headings']}")))
            lines.append(f"  #{owner['series_position']} {owner['owner']} {owner['patch']} [{owner['generated_patch_state']}; {counts or 'file headers only'}]")
            lines.append(f"    authoritative: {owner['authoritative_patch']}")
            if owner["generated_source"]:
                lines.append(f"    generated source: {owner['generated_source']}")
            for excerpt in owner["excerpts"]:
                location = "hunk-heading" if excerpt["kind"] == "heading" else f"hunk-old:{excerpt['old_line']}" if excerpt["kind"] == "removed" else f"hunk-new:{excerpt['new_line']}"
                lines.append(f"    {excerpt['kind']} {location} patch:{excerpt['patch_line']} {excerpt['text']}{'…' if excerpt['text_truncated'] else ''}")
            if owner["omitted_excerpts"]:
                lines.append(f"    {owner['omitted_excerpts']} more matching lines")
    lines.append(f"\n{report['total_patch_file_matches']} patch/file matches; {report['omitted_patch_file_matches']} omitted by limit")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--mode", choices=("auto", "text", "path", "glob"), default="auto", help="auto: literal text, exact path when '/' occurs, glob when '*?[' occurs; paths are relative to Chromium src")
    parser.add_argument("--ignore-case", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=40, help="maximum patch/file matches, 1–200; three line excerpts per match")
    parser.add_argument("query")
    arguments = parser.parse_args(argv)
    try:
        report = locate(arguments.worktree, arguments.query, mode=arguments.mode, build_root=arguments.build_root, source=arguments.source, limit=arguments.limit, ignore_case=arguments.ignore_case)
    except (OSError, PatchWorkspaceError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True) if arguments.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
