# Arcium-macOS

macOS build, packaging, signing, and platform integration for
[Arcium](https://github.com/dr-baker/Arcium). This repository pins one exact
Arcium core commit through its nested checkout.

## Start here

- Use Arcium: [Arc quickstart and feature list](docs/arc-quickstart.md).
- Develop Arcium: [build guide](docs/building.md), and
  [how Arcium's tooling differs from Helium's](docs/development-changes.md).

Use this repository for macOS builds and macOS-only changes. Shared browser
features belong in Arcium core.

## Read more when needed

| Question | Read |
| --- | --- |
| How do I migrate an existing profile and recover if it fails? | [Daily-driver migration](docs/arc-daily-driver-migration.md) |
| How do I author patches and build the product? | [Build guide](docs/building.md) |
| Why does the tooling differ from upstream Helium's? | [Development changes](docs/development-changes.md) |
| How should coding agents work in parallel? | [Working with agents](docs/agents.md) |
| How does native Settings integrate with the browser and renderer? | [SettingsUI integration](docs/settingsui-integration.md) |
| Which saved preference and runtime consumer backs each control? | [Native settings bindings](docs/native-settings-bindings.md) |
| What happens when a feature is turned off or unavailable? | [Feature settings contracts](docs/feature-settings-audit.md) |
| How do I validate tab ownership or measure performance? | [Tab invariants](docs/tab-invariants.md) and [feature performance](docs/feature-performance.md) |

## Working notes and evidence

Keep reusable instructions and current references in `docs/`. Keep run plans,
screenshots, logs, and acceptance records outside the repository, for example
under the build dir or `~/Library/Logs/Arcium/`. Dated design and validation
records from before October 2026 are on the `archive/dated-docs-2026-10-11`
branch.

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
