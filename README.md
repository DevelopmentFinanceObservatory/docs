# DFO docs

This repository holds the documentation of the [Development Finance Observatory](https://github.com/DevelopmentFinanceObservatory) (DFO), an initiative of [ONE Data](https://data.one.org) built on [Google Data Commons](https://datacommons.org). It also holds the build that gathers pages from the DFO's other repositories into one corpus for the DFO website.

The published docs are at <https://developmentfinance.org/docs>. Public launch is expected in late 2026.

This repository is under active development. Interfaces, schemas, and data may change without notice.

## What's inside

```text
content/hub/     hub pages, written here: Get started, Build, Data, Skills, About
roadmap/         the DFO roadmap, one YAML file per track
hub.yaml         the site nav: hub pages, grouping headings, and source mounts
sources.yaml     the registry of repositories whose docs the build fetches
docsync.yaml     the sources published as Google Docs for editors who do not use GitHub
src/dfo_docs/    the build and the docsync tool
scripts/         build.py and check_nav.py
tests/           the test suite
```

Every other page lives in the `docs/` folder of its own repository, such as [apis](https://github.com/DevelopmentFinanceObservatory/apis), [ai](https://github.com/DevelopmentFinanceObservatory/ai), and [skills](https://github.com/DevelopmentFinanceObservatory/skills), or in a package repository under [ONEcampaign](https://github.com/ONEcampaign), and `sources.yaml` points the build at it. To change one of those pages, open a pull request in the repository that holds it. The [org profile](https://github.com/DevelopmentFinanceObservatory) links every DFO repository.

## Getting started

Everything here runs without access to ONE's Google Cloud project, because the build clones public repositories anonymously. You need [uv](https://docs.astral.sh/uv/) and Python 3.13.

```bash
uv sync
uv run python scripts/build.py --out /tmp/dfo-docs-build
```

The build writes `corpus/` and `manifest.json` under the output directory. The Google Docs sync (`dfo-docsync`) needs ONE credentials and is for maintainers.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) explains how to edit a hub page, page modes, style, the link rules, and how a repository publishes its docs.
- [docs/development.md](docs/development.md) holds maintainer notes: the source registry, build failures, and the Google Docs sync.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. See [LICENSE](LICENSE).
