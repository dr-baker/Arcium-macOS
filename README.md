# Arcium-macOS

macOS build, packaging, signing, and platform integration for
[Arcium](https://github.com/dr-baker/Arcium). This repository pins one exact
Arcium core commit through its nested checkout.

## Building and development
Use this repository for macOS builds and macOS-only changes. Put shared browser
features in the Arcium core repository.

[> See docs/building.md](docs/building.md)

## Contributing
Before contributing, read Arcium's
[CONTRIBUTING.md](https://github.com/dr-baker/Arcium/blob/main/CONTRIBUTING.md).

## Credits

### Depot
Big thank you to [Depot](https://depot.dev/) for sponsoring our runners,
which handle the macOS builds of Arcium. Their high-performance infrastructure
lets us compile, package, and release new builds of Arcium within hours,
not days.

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
