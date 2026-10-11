# Tab invariant tests

These tests check shared rules after action sequences. They require no model
review to evaluate. Focused regression tests remain beside them to explain
previous failures.

## Organization

| Tier | Target | Rules and sequences |
| --- | --- | --- |
| Model | `helium_persistent_item_model_tests` | Unique live ownership, forward/reverse association agreement, no retired associations, rekey preserves identity, rejected tree moves are atomic, serialization preserves tree state. Four fixed seeds exercise lifecycle and tree operations. |
| Service | `arcium_feature_settings_unit_tests` | Pin, Favorite, removal and selection sequences preserve tab count, WebContents, URL, selection and collection membership. Four fixed seeds interleave active and background tabs. |
| Browser | `browser_tests` | Visible native and persistent rows agree with the tab model after repeated Pin/Favorite conversions. Page-owned unsaved input survives. Includes focused visibility, retiring Favorite and selected-index regressions. |

Shared Chromium tests live in the core patch
`patches/personal/arcium-tab-invariant-tests.patch`. The macOS runner is
`devutils/tab_invariants.py`; its failure-path tests are in
`devutils/tests/test_tab_invariants.py`.

The browser sequence currently assumes one active Space and no dormant records.
Its row checker is intentionally scoped to that fixture. Multi-Space visibility,
dormant records, sidebar resizing/collapse and real session restart need their
own fixture setup before using that checker. Codec round trips prove durable
model persistence; they do not prove browser session restoration or motion quality.

## Build and run

Source `dev.sh`, push the patches with `he push`, and run `he check`. With
`--build`, the runner builds the tier's test targets through `he build` first.
`$HELIUM_DEV_BUILD_ROOT` is the build dir `dev.sh` selected.

```sh
source dev.sh
he check
python3 devutils/tab_invariants.py --build --driver-checkout "$PWD" \
  --tier model --build-root "$HELIUM_DEV_BUILD_ROOT" \
  --report-dir "$HELIUM_DEV_BUILD_ROOT/.arcium/test-results"
```

The service and browser tiers need Chromium's test data, so they need a build
dir made with `he setup --full-source`. Do not copy individual missing fixtures
into a lite build dir.

```sh
python3 devutils/tab_invariants.py --build --driver-checkout "$PWD" \
  --tier all --build-root "$HELIUM_DEV_BUILD_ROOT" \
  --report-dir "$HELIUM_DEV_BUILD_ROOT/.arcium/test-results"
```

Each run holds the build-dir lock while tests run and creates a fresh results
directory. Discovery
must find the required new tests. Results must account for every discovered test,
with no failures, skips, duplicates or missing results. Retries are disabled.
The model executable reports XML; Chromium service/browser launchers report an
aggregate JSON summary. Logs, binary SHA-256, commands and results are retained in that directory.
Use `--build` for a gate: it compiles each target from the replayed source under
the same lock before executing. Omitting it is useful for diagnosis, but the
report explicitly does not certify source freshness. Never accept an older
binary's report for a changed source tree.

## Failure handling

A seeded failure prints its seed, step and action. Reproduce it with the same
parameterized test name from the log. Fix the underlying rule, then retain a
small focused regression when it adds useful explanation. Add new operations to
the existing sequence tests rather than copying the entire fixture.

Before treating a new assertion as protection, deliberately break the relevant
behavior in a scratch build and check that the test fails. Keep such mutations
out of committed patches.

A missing executable or missing test is a failed gate. Compiling a test source
file is not a substitute for running it. The runner does not configure remote
branch protection; making it a required merge check needs an available test
worker with the correct Chromium source, SDK and build artifacts.

## Validation on 2026-09-27

- All 365 patches replayed with zero fuzz; source/whitespace checks passed.
- The focused target rebuilt in eight actions and executed 62 passing tests,
  including eight seeded invariant cases.
- An isolated mutation deliberately retained a deleted record's reverse tab
  association. All four lifecycle seeds failed. The production object remained
  byte-for-byte unchanged.
- Six runner tests passed, covering missing inventory, skipped/failed/duplicate
  results, missing reports, process failure and launcher summary validation.
- The service and browser translation units compiled. Their executable gates
  could not build: the lite build dir lacks
  `chrome/test/data/extensions/extension_api_unittest/api_features.json`.
  Neither executable ran. A full-source build dir remains required.
