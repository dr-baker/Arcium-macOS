# Arcium-macOS

## What we're after

Build and package Arcium for macOS. This repository pins one exact Arcium core
commit and adds the macOS build, packaging, signing, resources, and platform
integration. Shared browser features belong in Arcium core.

AI-assisted development is welcome. The author remains responsible for every
change, regardless of which tools helped create it.

## Where to go

- `helium-chromium/` - pinned Arcium core checkout.
- `patches/` - macOS-only Quilt patches.
- `docs/building.md` - build and development procedure.
- `dev.sh` - development build and launch commands.
- `resources/` - macOS application resources.

## Ground rules

- Start macOS feature branches and COW worktrees in this repository.
- Keep `helium-chromium/` at the commit recorded by the outer gitlink.
- Put shared browser behavior in Arcium core. Keep only macOS-specific changes
  here.
- Understand and inspect all generated or AI-assisted output before submission.
- Test the affected behavior and state each completed proof gate accurately.
- Disclose uncertainty, missing tests, and tool-generated work that needs extra
  review.
- Do not send duplicate, automated, or unreviewed contributions.
- Never push to an upstream repository unless Daniel asks.

## Vocabulary

- **Arcium core** - the shared browser product pinned by this repository.
- **Arcium-macOS** - this macOS build, package, and platform repository.
- **Dev build** - `out/Default/Helium Dev.app` from the active worktree. This is
  the current artifact name until the application branding changes.
- **Proof gate** - one verified stage, such as patch replay, compilation, launch,
  visible behavior, persistence, or teardown.
