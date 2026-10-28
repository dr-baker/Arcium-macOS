# Updating from Helium

An upstream update spans two repositories and a Chromium source tree. A clean
Git merge does not prove that the patch series applies, and a clean replay does
not prove that Chromium compiles.

## Establish the target

From the macOS checkout:

```sh
git fetch --no-recurse-submodules origin
git -C helium-chromium fetch --no-recurse-submodules origin
python3 devutils/upstream_status.py --ref origin/main --json > /tmp/arcium-fork-status.json
python3 devutils/upstream_status.py --fetch
python3 devutils/upstream_status.py --json > /tmp/arcium-upstream-status.json
```

Check the published forks before choosing the starting commits. A local `main`
can contain unpublished tooling while missing newer product features from
`origin/main`. Reconcile both sets in the update branch before the expensive
browser build. Compare trees and patch content as well as ancestry: cherry-picked
history can report many missing commits whose changes are already present.
The `--fetch` option refreshes only `upstream`; the two explicit fetches above
refresh the published forks.

The report records both local heads, both upstream heads, their merge bases,
Chromium versions, the core commit selected by upstream macOS, and paths changed
on both sides. It separates local patch refreshes that changed only headers or
hunk positions. It reads committed heads; its working-tree section identifies
edits that the comparison does not include. Without `--fetch`, remote refs may
be stale.

Fetch each repository's `upstream` remote with `--no-recurse-submodules`.
The macOS submodule points to Daniel's fork. A recursive fetch can ask that fork
for an upstream core commit it does not have and fail despite fetching macOS.
Never change the product's submodule URL to work around this.

Check that the selected core target contains the macOS upstream pin. Compare
changes after that pin before using a newer core head. Equal Chromium versions
are necessary for this pairing, but do not prove compatibility.

## Integrate in isolation

Use an isolated worktree for a Chromium version change. Record the starting
outer and core commits, and preserve uncommitted work in the original checkout.
Merge core first, then macOS, and commit core before recording the outer pin.
Keep upstream merge ancestry so the next update compares against the correct
base. Do not substitute the vanilla upstream core pin for Arcium's merged core.

Review conflicts in this order:

1. Source downloads, toolchains, pruning, and GN configuration.
2. Imported patches. Compare actual changes before retaining old hunk context.
3. Patch series order. Preserve all personal patches and their dependencies.
4. Product resources, generated translations, packaging, and CI.

Keep Arcium's build router, lane reservation, timestamp tracking, profile
isolation, signing identity, and update-feed configuration. When upstream
replaces an entry point, port its required source/toolchain changes into the
guarded path and document the retained downstream behavior. Run
`python3 devutils/check_build_entrypoints.py` afterward.

Do not regenerate translations from an unpatched source tree. Preserve local
message additions as well as product-name substitutions; taking the upstream
generated JSON alone loses Arc import, Spaces, and onboarding text.

## Replay and build

For a Chromium version change, explicitly export a new `HELIUM_BUILD_DIR` before
sourcing `dev.sh`. Machine settings otherwise select the existing shared build.
Keep that old build until the new one passes. Allow at least 100 GiB for the new
source and output, and check available space on the selected volume.

```sh
export HELIUM_BUILD_DIR=/absolute/path/to/new-build
export HELIUM_DEV_WORKTREE=/absolute/path/to/update-worktree
source dev.sh
he agent check --json
he agent presetup
he agent merge
he agent push
```

Chromium 156 uses Helium's prepared base archive and a host-specific macOS
overlay. Both target architectures use the overlay for the machine doing the
build. Preserve build dependencies during pruning. The overlay supplies GN,
Siso, Clang, Rust, Node, and other pinned tools; do not run the old toolchain
download and Node-moving steps over it.

Refresh development defaults when adopting the 156 tooling:
`he agent configure --diagnostics --refresh-defaults`. Plain configure preserves
existing `args.gn`. The development defaults set `use_static_angle=false` because
156's static default links the same Objective-C graphics class into both Blink
and GL component libraries. Dynamic ANGLE restores the previous macOS ownership.
Refresh `--daily` separately before validating that development output mode.
Official release configuration uses a separate entry point.

If archive acquisition fails, setup preserves the incomplete source and stops.
Fix the reported download or extraction error and retry, or select a fresh build
directory for `he agent setup --full-source`. Do not automatically clone over a
partially extracted archive: the full-source checkout requires an empty tree.
Prepared archives also omit WebUI test fixtures used by personal patches.
Keep the missing-fixture restoration step in setup. It fetches only absent files
from the exact Chromium release tag and preserves existing source files.

When upstream moves code, move its build dependencies and tests with it. In the
156 port, vertical-tab geometry moved into layout classes, browser access moved
to `BrowserWindowInterface`, and `browser_view_unittest.cc` was removed. Existing
UI checks belong in the browser-test fixture; restoring the deleted file would
leave tests outside the current build graph.

Repair each rejected patch at its Quilt position using the procedure in
[agent workflow](agent-workflow.md#repair-a-patch-that-fails-to-apply).
Save repairs back to their owning repository. Never globally refresh the series
with fuzz to hide compatibility failures. Pay attention to patches that apply
with offsets: successful textual application does not prove that a changed
upstream API still means the same thing.

After the whole series applies, replay it from clean source, validate both
catalogs, configure, and compile. A Chromium version change requires a full
build; incremental timing from the previous version is not a useful estimate.
Run the affected feature contracts, especially tab ownership, restore, imports,
and native window integration. Establish runtime mode before launch or install.

Record upstream SHAs, merged SHAs, build directory, repairs, and each proof gate
in the update handoff. Keep unverified work on its update branch. A new version
number or a successful patch linter is not a completed browser update.

## Resolve moved and removed code

Read each rejected hunk against the current source before refreshing it. A
three-way candidate built from the previous patched source can help recover
intent, but still needs review. In this port, fuzzy matches put GN exclusions
inside an unrelated target and extended a preprocessor guard over new PDF
accessibility behavior. Check conditional boundaries, not just balanced braces.

After forcing the stopped patch as the repair workflow describes, prepare a
three-way candidate from recorded Quilt preimages:

```sh
python3 devutils/patch_candidates.py \
  --old-src /absolute/path/to/previous-build/src \
  --new-src /absolute/path/to/new-build/src \
  --patch-name personal/arcium-spaces.patch \
  --patch helium-chromium/patches/personal/arcium-spaces.patch \
  --file chrome/browser/ui/helium/helium_space.cc \
  --output /tmp/arcium-space-candidates
```

The output directory must be new and outside both source trees. Repeat `--file`
for additional rejected files. The tool requires the old patch to apply forward
with zero fuzz to its recorded old preimage. It refuses a mismatched preimage,
writes conflict markers where needed, and never edits source or refreshes a
patch. It handles modified and added text files; review deleted files by hand.
Review candidates against current APIs and build ownership, resolve them
at the stopped Quilt position, then use `he agent save-patch` and `he agent push`.

Before restoring a missing file, distinguish an omitted archive fixture from
code deleted upstream. Check the exact Chromium release and current build
membership. Retire patches whose implementation and APIs have disappeared;
record the evidence and preserve any independent behavior they also changed.
When upstream has adopted an equivalent fix, remove that part of the personal
patch instead of layering duplicate guards over it. Review likely obsolete
test-compatibility patches early and batch confirmed series removals: the
catalog currently requires a fully popped stack for any membership change.
Repeatedly discovering one retired patch during replay adds a full pop/merge
cycle each time. Do not edit the generated catalog to skip that check.

For Polymer-to-Lit migrations, port property initialization, conditional HTML,
and test synchronization together. Tests must not await browser-proxy calls
that a build-time availability flag deliberately prevents.

Trace GN ownership before placing a surviving source back into a list. Chromium
156 split the old UI target into many smaller targets. A fuzzy insertion beside
an unrelated source can replay successfully while leaving duplicate objects,
missing dependencies, or tests in the wrong executable. Put public headers and
implementation sources in their current targets, then validate the graph during
configuration.

After changing GN dependencies, run `he agent configure --diagnostics` before
the guarded build. This preserves existing arguments while regenerating the
graph. Siso's dry run can otherwise report only the planned regeneration and
zero steps, leaving the agent guard unable to count the actual compile plan.
Inspect the plan error, then regenerate explicitly instead of bypassing the
guard or treating that zero as a successful build.

For onboarding imports, keep stable profile IDs in selections and resolve them
to the current import indices at dispatch. Block discovery refresh while a batch
is running. Preserve upstream permission prompts when restoring a custom flow;
automatic startup discovery is no longer the upstream contract.

When native interfaces split into creation and update operations, update all
callers together. For macOS chrome, distinguish the native window's opacity from
the compositor's opacity: even an opaque custom material behind Views needs the
Views surface to let that material show through.

Translation catalogs can contain several entries with the same source path and
message name for platform-specific wording. Preserve those variants; name-only
deduplication drops valid translations. Check generated messages against the
fully patched tree, including local macOS patches and onboarding, before
applying translations. The upstream generator's fetched platform checkouts do
not include an uncommitted downstream port.

A clean patch replay proves context compatibility, not API compatibility. Before
starting the first full compile, scan feature-owned code for APIs removed by the
Chromium jump. For the 156 window migration, migrate service signatures, weak
handles, window creation, and callers together to `BrowserWindowInterface`.
Avoid reintroducing `GetBrowserForMigrationOnly()` or downcasting the interface.
Keep concrete lifecycle operations at their owner: a deferred empty-strip close
can retain Browser's weak close callback instead of making Spaces depend on
Browser internals. Update test factories alongside production signatures.
For each changed local API, inventory every caller in the fully patched tree,
including observers owned by other feature patches. Include those production
objects in the focused compile set. The empty-strip deferral migration compiled
in Browser and Spaces before review found its separate UnloadController caller.
Keep a read-only state query separate from callback registration so observing
the state cannot erase a pending continuation.

After configuration, list the C++ and Objective-C++ objects owned by active
personal patches in both repositories:

```sh
python3 devutils/personal_build_targets.py --build-dir "$HELIUM_BUILD_DIR" --json
```

The command reads the selected compilation database, excludes test/support
objects, and reports sources absent from that configuration. It never builds or
guesses targets for other platforms. Add `--daily` to inspect `out/Default`.
In zsh, use its plain output for a complete downstream object pass:

```zsh
targets=("${(@f)$(python3 devutils/personal_build_targets.py --build-dir "$HELIUM_BUILD_DIR")}")
if [[ -n "${targets[1]:-}" ]]; then
    he agent build --approved --jobs 6 "${targets[@]}"
fi
```

The 156 port initially checked 43 objects; the complete inventory found 239.
Compiling this set can expose downstream API errors before the full browser's
remaining libraries. It covers directly patched `.cc` and `.mm` files, not every
consumer of a changed header. It still needs generated prerequisites and does
not replace linking `chrome`, executing tests, or runtime acceptance.

When a feature is retired during a UI framework port, remove its template
control as well as its property, preference, strings, and availability data.
An obsolete control can survive patch replay and fail only during the full
Settings TypeScript build. Compile generated WebUI inputs before treating a
successful standalone frontend test run as coverage of the browser's resources.

If the first compile slows after swap pressure, inspect `he agent check --json`
and the build evidence before calling it stuck. The desktop resource policy
changes process priority after launch; it does not lower the active job ceiling.
A supervised restart with fewer jobs can reduce the concurrent working set
(for example, add `--jobs 6` to the same `he agent build` command). Let the old
supervisor drain its children before restarting. Completed outputs are reused;
do not bypass the supervisor or assume fewer jobs is always faster.

Recheck memory during later compilation phases. Several hours of healthy
samples do not establish a safe job ceiling for the remaining graph. Record
the pressure interval and the revised ceiling when restarting, and distinguish
an intentional interruption from a compiler failure in the handoff.

For live diagnostics, inspect the console log and `siso.INFO` alongside resource
samples. Raw phase output can lag because the capture writer buffers writes.
The Python 3.14 runtime used for this port flushed stdout in 128 KiB batches.
A stale raw-file timestamp alone does not prove the build stopped or lost
output. The in-progress manifest is also an initial snapshot. Check the final
manifest and capture warnings after the command drains before claiming complete
evidence. Console-drop warnings and raw-capture failures have different effects.

After an agent or server restart, verify the recorded process identities before
resuming. A build child can survive its outer shell, leaving queued test commands
unexecuted. Confirm that the old process group has exited before starting a
replacement, and explicitly requeue any tests that never ran.

Use command-completion notifications for long builds. In T3 Code, a scheduled
check bound to the working thread can provide recovery if those notifications
are lost. Each run should read the current result once and end quietly while
compilation progresses. Disable the schedule on completion or a failure that
needs intervention. Reserve an agent for diagnosing a concrete problem rather
than keeping one alive to poll logs; the build supervisor already handles
resource backoff.

Choose native-test coverage before acquiring source. Prepared release archives
can build the browser while omitting test fixtures such as
`chrome/test/data/webui/chai_assert.ts`. Even a single unit-test object can need
that tree through generated-resource dependencies. Use the full-source workflow
in [Building](building.md#full-source-and-browser-tests) when those tests are
required; do not fill the gaps with fixtures from an older Chromium release.
Check each focused executable's dependency closure before treating every native
test as blocked. In this port, `helium_persistent_item_model_tests` and
`arcium_optional_navigation_tests` avoid WebUI fixtures, while
`helium_little_arc_tests` reaches them through browser test support. A small test
source does not imply a small dependency graph.

For isolated manual lifecycle checks, serve the synthetic fixture locally:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory devutils/scenarios/fixtures
```

Open `http://127.0.0.1:8765/tab-lifecycle.html?page=A` in the named Dev profile.
The links provide a second page for Peek and split checks. Record its instance
token and draft before promoting Little Arc or cancelling a close; both should
remain unchanged. Arm the before-unload checkbox through the UI before testing
cancellation. The color-scheme witness updates live for native Settings checks.
Use the existing Pin/split contracts for restart persistence; this fixture's
unsaved DOM state is only a live-content identity witness. Stop the server when
testing ends.

For graphics linkage changes, open `/webgl.html` on the same fixture server.
It checks WebGL context creation and a green framebuffer readback. Capture the
visible result and inspect `chrome://gpu` separately; a passing framebuffer
does not establish hardware acceleration. Inspect new-launch diagnostics for
duplicate Objective-C classes, including classes that native tests never load.
