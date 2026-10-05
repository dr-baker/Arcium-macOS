# Arcium-macOS

macOS build, packaging, signing, and platform integration for
[Arcium](https://github.com/dr-baker/Arcium). This repository pins one exact
Arcium core commit through its nested checkout.

## Start here

- Use Arcium: [Arc quickstart and feature list](docs/arc-quickstart.md).
- Develop Arcium: [maintainer quickstart](docs/helium-maintainer-quickstart.md).

Use this repository for macOS builds and macOS-only changes. Shared browser
features belong in Arcium core.

## Read more when needed

| Question | Read |
| --- | --- |
| How do I migrate an existing profile and recover if it fails? | [Daily-driver migration](docs/arc-daily-driver-migration.md) |
| Why are source ownership and build lanes separate? | [Maintainer onboarding](docs/helium-maintainer-onboarding.md) |
| How do I author patches, coordinate parallel work, and build the product? | [Build guide](docs/building.md) |
| How does native Settings integrate with the browser and renderer? | [SettingsUI integration](docs/settingsui-integration.md) |
| Which saved preference and runtime consumer backs each control? | [Native settings bindings](docs/native-settings-bindings.md) |
| What happens when a feature is turned off or unavailable? | [Feature settings contracts](docs/feature-settings-audit.md) |
| How do I validate tab ownership or measure performance? | [Tab invariants](docs/tab-invariants.md) and [feature performance](docs/feature-performance.md) |
| What changed in the October delivery? | [Branch changelog](docs/changelog-2026-10-03.md) |

## Working notes and evidence

Keep reusable instructions and current references in `docs/`. Dated design,
implementation, and validation records belong in [docs/audits/](docs/audits/).
Their queues and proof claims describe the original snapshot; current procedures
come from the guides above.

Keep local run plans, screenshots, logs, and exact acceptance records outside the
repository, under the run's build lane or `~/Library/Logs/Arcium/`. Give each run
one readable summary that links its detailed evidence and unresolved checks.
Recorded evidence retains its original paths and source commits when the guides
are reorganized.

## Contributing
Before contributing, read Arcium's
[CONTRIBUTING.md](https://github.com/dr-baker/Arcium/blob/main/CONTRIBUTING.md).

## Credits

### Depot
The upstream Helium macOS project credits [Depot](https://depot.dev/) for
sponsoring its build runners. This acknowledgment comes from the upstream
project and does not imply sponsorship of Arcium.

### ungoogled-chromium-macos
Arcium-macOS descends from
[Helium for macOS](https://github.com/imputnet/helium-macos), which is based on
[ungoogled-chromium-macos](https://github.com/ungoogled-software/ungoogled-chromium-macos).

## License
All code, patches, modified portions of imported code or patches, and
any other content that is unique to this repository and not imported from other
repositories is licensed under GPL-3.0. See [LICENSE](LICENSE).

Any content imported from other projects retains its original license (for
example, any original unmodified code imported from ungoogled-chromium remains
licensed under their [BSD 3-Clause license](LICENSE.ungoogled_chromium)).
