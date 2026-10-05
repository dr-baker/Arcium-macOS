# Build-lane scratch reference

This reference describes temporary storage for heavy-lane tooling. For source
selection, lane ownership, and build commands, use
[the build guide](building.md#select-a-build-lane).

## Temporary storage and identity

Heavy-lane transactions route temporary files and Siso logs to a short directory
on the verified external volume: `<mount>/.arcium-tmp-<uid>/<lane-hash>`. The
selector reserves 19 bytes for sccache's `/sccacheXXXXXX/sock` suffix and rejects
paths that would reach macOS's 104-byte Unix-socket path limit. This prevents a
long lane name from failing compiler-cache startup before Clang runs.

The selector checks the pinned volume UUID, writable case-sensitive APFS, every
existing path component without following symlinks, and matching device IDs.
Scratch directories must report the caller's UID and mode `0700`; their
`lane.json` identity binds the full lane path, UID and volume UUID. An existing
unrelated identity or directory is rejected. Volume ownership-disabled remains
an advisory warning, as reported by `he lane`. Per-user names separate scratch
namespaces; they provide no cross-user privacy guarantee when ownership is
ignored. Keep profiles, Keychain data and other private data out of compiler
scratch.

`build_lane.heavy_lane_temp(spec)` selects and validates the path without creating
storage. `build_lane_cli.py --select-temp` exposes that same read-only selection
and prints only the path on stdout, with advisory warnings on stderr. Shell build
commands select first; their locked Python transaction creates and revalidates
the directory before invoking build tools.
External drivers must use the same API inside their existing lane lock and
material guard:

```python
import os

from build_lane import heavy_lane_temp

# spec is the already-selected heavy LaneSpec with the pinned volume UUID.
# The lane lock and material guard are already held here.
os.environ["TMPDIR"] = str(heavy_lane_temp(spec, create=True))
```
