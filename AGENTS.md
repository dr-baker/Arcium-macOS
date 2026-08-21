# Arcium

## What we're after

Build Daniel's private AI-enabled, Arc-style macOS Helium fork as isolated,
reviewable Quilt changes and prove them in the real browser UI.
This outer repository is the canonical development, worktree, build, packaging,
personal-patch, and landing authority. Nested `helium-chromium` supplies the
pinned Chromium/Helium baseline.

## Where to go

- `patches/personal/` — Daniel-owned Chromium behavior patches.
- `patches/series` — active outer patch order.
- `helium-chromium/` — pinned baseline and upstream patch catalog.
- `docs/private-patch-validation.md` — active/inactive inventory and proof gates.
- `dev.sh` — worktree-aware build, relink, and Dev launch control plane.

## Ground rules

- Treat outer `main` as Arcium's product line; start feature branches and COW
  worktrees here. Keep `upstream-main` only as the public Helium mirror.
- Keep nested `helium-chromium` detached at the outer gitlink during normal
  development. Do not create parallel personal feature branches there.
- Put personal Chromium behavior in new `patches/personal/*.patch` files. Do
  not edit existing upstream patch files to carry personal behavior.
- Land the patch, series entry, verifier, and any intentional gitlink update
  together in the outer feature branch.
- Handle upstream baseline changes on a dedicated outer integration branch:
  advance the inner baseline, regenerate the merged series, replay it fully,
  and rebase only personal patches that need new context.
- Never push or open a pull request against public Helium unless Daniel asks.
- Use the active worktree's `Helium Dev.app`; keep packaging, compilation,
  launch, behavior, persistence, and teardown as separate proof gates.

## Vocabulary

- **Outer repository** — Arcium; the canonical product and landing history.
- **Inner repository** — `helium-chromium`; the baseline selected by the gitlink.
- **Personal overlay** — ordered `patches/personal/*.patch` entries applied after
  the baseline and existing macOS patches.
- **Dev build** — `out/Default/Helium Dev.app` from the active outer worktree.
