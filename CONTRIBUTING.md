# Contributing to the DFO docs

Issues and pull requests are welcome. The ONE Data team maintains this repository. Open an issue to discuss a large change, such as a new section or a new source repository, before you write it. Contributors follow the [Code of Conduct](https://github.com/DevelopmentFinanceObservatory/.github/blob/main/CODE_OF_CONDUCT.md). Report security issues through the "Report a vulnerability" button under the repository's Security tab, as the [security policy](https://github.com/DevelopmentFinanceObservatory/.github/blob/main/SECURITY.md) describes.

The DFO docs serve analysts who know the DAC and the CRS, write some Python or R, and need data they can trust in their own work. AI assistants read the same pages.

## Where pages live

The site publishes hub pages from Markdown files under `content/hub/` in this repository. Source pages live in each source repository's docs folder, and the build fetches them through a row in `sources.yaml`.

```text
dfo-docs/
├── content/hub/          hub pages; a page's URL is its path here
│   ├── index.md          Home, published at /docs
│   ├── get-started/      tutorials, one per way into the DFO
│   ├── build/            how-tos for taking data and charts into your own work
│   ├── data/             how the data is modelled: explanation and reference
│   ├── skills/           what a skill is and how to use one
│   └── about/            citation and licence
├── hub.yaml              the nav: hub pages, grouping headings, and source mounts
└── sources.yaml          the registry of source repositories
```

A hub page publishes at its path under `content/hub/` without the `.md` suffix, so `content/hub/data/glossary.md` publishes at `/docs/data/glossary`. Its place in the nav comes from `hub.yaml`, so a page can move in the nav without changing its URL. Only pages named in `hub.yaml` publish.

A source repository with several pages groups them by mode in `tutorials/`, `how-to/` and `about/`, as `tossd-reader` does.

## Writing a page

Each page does one job. Pick its mode before writing:

- A tutorial teaches by doing, from a fresh start to one working result.
- A how-to solves one task for a reader who already knows the basics.
- A reference page lists facts to look up: fields, codes, endpoints.
- An explanation says why things are the way they are.

Split a page that mixes modes. A tutorial that needs to explain the data model should link to the explanation page.

Every page starts with front matter carrying a one-sentence `description`. The site uses it as the page's meta description.

```markdown
---
description: Search for CRS disbursements on /data and download them as a CSV.
---

# Get data
```

Use DFO values in examples, including `country/NGA`, CRS purpose 12220, finance type 110, and a real `spec_…` id. Show the output first, whether a table, response or screen, then the call or steps that produce it. Each example must run when pasted into a fresh shell or session. Put its imports and setup on the page or in one linked setup section. Run every example before publishing it and paste the output the command produced, trimmed with a visible `…`. Source repositories test their own examples.

End every page with a `## Next` section of one or two links, each with a sentence saying what the reader gets there. Leave out boilerplate headings such as Overview, Summary or Conclusion.

Use only three callouts, `!!! note`, `!!! tip` and `!!! warning`. Leave them untitled and indent the body four spaces. The build renders them as site alerts. A title becomes a bold lead sentence, so put the point in the body. Use callouts for optional material and keep required information in the page body.

```markdown
!!! warning
Studio links are always snapshots.
```

The build passes collapsible `???` blocks through unchanged, where they render as raw text. Leave them out.

Pages describe the current state. Leave out "As of" dates and counts that change as the DFO grows, such as the number of sources or skills, and link the live list instead: `/data/sources`, a Wikibase class page, or the Skills section. Put planned work on the roadmap at `/data/roadmap`. Where a page needs a fact that cannot be checked, leave an HTML comment such as `<!-- TODO: link when the API guide is public -->` in place of a guess. HTML comments are author notes, and the build drops them from the published corpus.

Write in British English, in short sentences, in the second person for tutorials and how-tos. Pages carry no emoji. Write each paragraph as one line. The mdformat pre-commit hook runs with `--wrap no`.

Show a right and a wrong example as two consecutive fences titled `Right` and `Wrong`, such as ```` ```python title="Right" ````. Keep both visible. An explanation of either half goes in the fence as an ordinary comment.

Use tabs only for alternatives a reader picks one of, such as curl or Python, pandas or R, or one assistant or another. Each tab holds a working example that gives the same result as the others. Leave a blank line after `:::tabs`, before and after each `::tab` line, and before the closing `:::`. The formatter mangles tabs without these blank lines.

````markdown
:::tabs

::tab{label="curl"}

```bash
curl -s "$DFO_API/..."
```

::tab{label="Python"}

```python title="quickstart.py"
...
```

:::
````

Title a fence that holds a file the reader saves, such as ```` ```json title=".mcp.json" ````. Draw a diagram as a `mermaid` fence, such as `flowchart LR`, with short node labels in plain words.

## Links

- Between corpus pages, use relative `.md` links, such as `../data/versions.md`. The site turns them into `/docs/…` URLs, and CI checks that each target exists.
- Hub pages link into a source's pages through the corpus layout, `corpus/<source name>/…`. From `content/hub/index.md`, the ODA reader's landing page is `../oda_reader/index.md`.
- For site pages outside the docs, use root-relative links such as `/data`, `/data/sources` or `/studio`. CI skips these, so check each one against the site.
- For anything else, use an absolute `https://` URL.

Only published pages are valid link targets. The link check fails for a page absent from `hub.yaml` or in a disabled source.

## Publishing a source repository's docs

A source repository keeps its pages in a docs folder and declares them in a nav sidecar. The build looks for the sidecar at `docs/mkdocs.yml`, then a root `mkdocs.yml`, then a root `zensical.toml`. The docs root is the sidecar's own `docs_dir`, resolved from the folder the sidecar sits in.

Use a root `mkdocs.yml` when user-facing pages sit in a subfolder separate from a repository's internal docs. dfo-apis publishes `docs/guide/` this way:

```yaml
site_name: API
docs_dir: docs/guide
extra:
  dfo:
    path: api
nav:
  - Quickstart: quickstart.md
  - Conventions: conventions.md
  - Resolve a question: resolve-a-question.md
  - Get a dataset: get-a-dataset.md
  - Look things up: look-things-up.md
```

`site_name` is the section title. `extra.dfo.path` is the public path, so these pages publish under `/docs/api`. The nav lists every page to publish. Only pages reached by a nav entry enter the corpus. The build warns about any other page in the docs root.

Then register the repository in `sources.yaml`:

```yaml
- name: dfo-apis
  repo: DevelopmentFinanceObservatory/apis
  ref: dev
  docs_dir: docs/guide
  path: api
  title: API
```

In `sources.yaml`, `docs_dir` sets which folder the build checks out. Match it to the sidecar's `docs_dir`. Set `path` to `extra.dfo.path`. The build fails if they differ. Add a `mount` entry in `hub.yaml` that names the source row. To register a repository before publication, set `enabled: false` with a `reason` and leave it out of `hub.yaml`. A mount for a disabled source fails the build. Every registered repository must be public. [docs/development.md](docs/development.md) covers `exclude`, `kind: external`, `kind: skill`, and each build failure.

Before opening a pull request in the source repository, check its nav against its pages from a dfo-docs checkout. Then check links from the source repository's docs folder:

```bash
uv run python scripts/check_nav.py /path/to/source-repo
lychee --offline /path/to/source-repo/docs/guide/
```

## Checking a change here

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src/dfo_docs
uv run pytest
uv run python scripts/build.py --out /tmp/dfo-docs-build
lychee --config lychee.toml /tmp/dfo-docs-build/corpus/
```

The build clones every enabled source over HTTPS without credentials, so none of this needs ONE's cloud access. Run `uv run pre-commit install` once, and pre-commit then runs the formatters and hygiene checks on each commit.

## Pull requests

Branch from `dev` and open the pull request into `dev`. A push to `dev` rebuilds the corpus the site reads, and a pull request runs the build without publishing. A draft pull request runs no CI, so mark it ready when you want the checks. CI runs ruff, ty, the tests on Python 3.13 and 3.14, the build, and the link check. A page change needs a description in its front matter and working links. Code changes need tests and must pass these checks.

Commit messages follow Conventional Commits, such as `docs(docsync): describe the first run without state`.

Maintainer internals are in [docs/development.md](docs/development.md).
