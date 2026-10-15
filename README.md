# dfo-docs

dfo-docs fetches documentation from the DFO's source repositories, normalises it, and publishes a markdown corpus with a manifest that the DFO site renders. Each source repository keeps its own `docs/` folder and owns what is in it.

To write a page or publish a repository's docs, read [CONTRIBUTING.md](CONTRIBUTING.md).

## Adding a repository

Add a row to `sources.yaml` with `name`, `repo`, `ref`, `docs_dir`, and the `path` the documentation should publish at. A row with `kind: external` points at a package that publishes its own documentation elsewhere, and carries a `url` instead of a `docs_dir`.

A row with `kind: skill` publishes a repository of agent skills, such as dfo-skills. It needs no sidecar. The build walks `docs_dir` and publishes each directory that holds a `SKILL.md` as a skill page at `<path>/<directory>`, with each file in its `references/` as a page at `<path>/<directory>/references/<name>`. Directories whose names start with `_` stay out. The row must set `docs_dir`, `path`, and `title`, and it may not set `exclude`. It may set `internal_dir`, a second directory the build walks the same way. Skills under `docs_dir` are offered for install. Skills under `internal_dir` are published at the same `<path>/<directory>` and are not offered. A directory name may appear under only one of the two. Until the repository has the `internal_dir` directory, the build warns and reads `docs_dir` alone. Its `hub.yaml` mount becomes one group titled by `title`. A `categories.yaml` in `docs_dir` lists skills under `sources` or under a domain in `domains`, and each category becomes a group inside the mount, titled in sentence case: Sources, and Domains with a group such as Sovereign debt inside it. Categories and the skills in them follow the file's order. Skills the file leaves out come first, in directory order, and without the file that is every skill. Each skill page opens with a header the build writes from the front matter: the skill's name and the first sentence of its `description`. For a skill under `docs_dir`, whatever its category, the build writes a zip to `corpus/<name>/<directory>.zip`, holding `<directory>/SKILL.md` and `<directory>/references/*.md` as committed, records the zip on the page's manifest entry as `bundle_path`, and adds a line to the header that links to the hub page on using skills in your own agent and to the zip. A skill under `internal_dir` gets no zip, no `bundle_path`, and no such line.

If the repository needs to sit under a grouping heading, or nest alongside another package, add it to `hub.yaml`'s nav as a `mount` (or `external`) entry. A grouping heading such as `bblocks` or `ODA` lives only in `hub.yaml`, since no source repository declares it.

Every source repository is public, and the build and the registry-health workflow clone and query them without credentials. A private repository cannot be registered.

To register a repository without building it yet, set `enabled: false` and a `reason`. A disabled row still loads and is reported by name. Turning it on means enabling the row and adding its `hub.yaml` mount, since a mount whose source is disabled fails the build.

To take most of a repository but hold some pages back, list glob patterns under `exclude`. They match the docs-root-relative path, so `reference/*` keeps a whole section out and `changelog.md` keeps one page out. Use it for pages that cannot render outside their own site, such as an mkdocstrings reference section. A pattern matching no nav entry fails the build, so a pattern left behind by an upstream rename is reported rather than quietly letting those pages in.

## Running the build locally

```
uv sync
uv run python scripts/build.py
```

The build clones every enabled repository over HTTPS without credentials, normalises what it finds, and writes `corpus/` and `manifest.json`.

`corpus/` and `manifest.json` are generated output that lives on the `corpus` branch. A push to `dev` runs the same build in CI and commits the result there, and that branch is what the DFO site pins and reads. A pull request into `dev` or `main` runs the build and publishes nothing.

## Editing in Google Docs

`dfo-docsync` publishes the pages of the sources listed in `docsync.yaml` as Google Docs in the "DFO docs" folder of the ONE Data shared drive, so editors who do not use GitHub can revise them. It tracks the pages in a Sheet and turns the edits made in the Docs into pull requests, one for each source repository. The script splices the words an editor changed into the source file one word at a time, so untouched text keeps its exact form, and keeps the structure, code blocks, and tabs as they are. Editors read the guide in the Sheet's "How to edit" tab, which `init` writes from `src/dfo_docs/docsync/how_to_edit.md`.

```
uv run dfo-docsync init
uv run dfo-docsync push
uv run dfo-docsync pull
```

- `init` creates the tracking Sheet in the folder. Run it once.
- `push` creates a Doc for each page, or replaces it with the page's current source, and updates the Sheet. It refuses to run when the state store is empty but Docs exist under the folder (`StatelessDocsError`). Restore the state, or pass `--adopt` to adopt the Docs that match their source.
- `pull` reads every Doc whose Status is "Ready for review" and opens a new pull request for each source repository, on its own branch `docsync/edits-<stamp>`. docsync never pushes to that branch or edits the pull request again, so reviewers may edit it or commit to it. A page is in at most one open pull request. `pull` skips a page while its pull request is open, and fails a Ready page that an open docsync pull request carries but its state does not name, with the message "merge or close that PR, or revert the file on its branch, before sending this page". Edits made in the Doc while the pull request is open go in the next one.
- Both `push` and `pull` first settle each page's pull request. A merged pull request settles once the merge is in the branch the page's source is read from, and until then the page waits. The page then shows "Merged", or "Editing" when the Doc holds later edits, and the next `push` refreshes the Doc from GitHub. A pull request that is closed, or merged without the page, returns the page to "Editing" with the reason in the "Not applied" column. A page set to "Discard my edits" stays on it and is discarded. A "Ready for review" page whose Doc holds nothing new to send becomes "Merged" when its pull request has just merged and "Editing" otherwise, with "Nothing to send" in "Not applied".
- To drop one page from a multi-page pull request, revert that file on the pull request branch before merging. The page returns to "Editing".
- "Discard my edits" is a Status an editor sets. The next `push` resets the page's Doc from GitHub, even with open comments, and sets the page to "Editing". It refuses while the Doc has open suggestions, and waits while the page's pull request is open. When that pull request merged into a branch the page is not read from, the discard goes ahead. The page's state records the discard until a `push` reads another Status, so when the Sheet write after a discard fails, the next `push` only sets the page to "Editing" and keeps what the editor typed since.
- A Doc that was trashed or deleted is recreated on the next `push`, unless the page's pull request is open.

`--page <id>` limits `push` or `pull` to one page and can be repeated. A page id is the manifest's, such as `hub/build/share`. `pull --dry-run <dir>` writes the edited files and pull request bodies under `<dir>` and changes nothing in git, the Sheet, or the state. `docsync.yaml` sets `pr_author`, the author `gh` lists open docsync pull requests by; it is `app/dfo-docsync` for the pull requests CI opens. For a local run that opens pull requests under your own login, pass `--pr-author @me` to `push` and `pull`.

Hub pages (`hub/...`) run only from a checkout of this repository's `dev` that is at `origin/dev`.

A maintainer runs a sync from a `dev` checkout at `origin/dev`, signed in to Google with a one.org account. `.github/workflows/docsync.yml` (one command on dispatch, with no schedule) is not used: a Markdown upload made by its service account loses code blocks, and every page with one then fails to align. Its job runs only on `dev`, in the `docsync` environment, which is where the `dfo-docsync` App key and the Google workload identity settings live (see the workflow's header). The token lasts about an hour. Without it, the command uses Application Default Credentials.

```
git switch dev && git pull
gcloud auth login --enable-gdrive-access
export DOCSYNC_ACCESS_TOKEN=$(gcloud auth print-access-token)
uv run dfo-docsync pull --pr-author @me
uv run dfo-docsync push --pr-author @me
```

`pull` opens a pull request for each source repository with pages set to Ready for review. `push` refreshes each Doc whose page changed in its source repository, the pages of merged docsync pull requests included, and adds a Doc for each new page. Run the sequence again after docsync pull requests merge. A merge to this repository's `dev` rebuilds the corpus the site reads at once. A merge in another source repository reaches it at the 06:00 UTC build, or sooner with `gh workflow run build.yml --repo DevelopmentFinanceObservatory/docs --ref dev`.

When the `docsync-state` branch is empty but Docs already exist under the folder, `push` stops with `StatelessDocsError`. Run it once as `uv run dfo-docsync push --adopt --pr-author @me` from a `dev` checkout at `origin/dev`. `--adopt` takes over each Doc that carries a page id and whose settled export aligns with the source, and records the current `dev` commit as its baseline, so it needs no earlier commit. A Doc that differs from the source holds an editor's unsent work, so its page fails and the Doc stays. Resolve those by hand, then rerun `push --adopt`. Later runs need no flag.

Each page's state (Doc, source commit, baseline export, pull request) is a `state/<page id>.json` file on the orphan branch `docsync-state`, with one commit for each run. These guards hold a page back, and the run reports the reason and carries on:

- `push` leaves a Doc alone when it has edits that have not reached GitHub ("edited in Docs; set Status to Ready for review to send"), open comments, or open suggestions, because replacing a Doc discards or detaches them. "Discard my edits" overrides the first two. It checks the Doc's revision again just before replacing it and holds the Doc if the revision changed.
- `pull` skips a Doc with open suggestions. A skipped or failed page does not stop the other pages of its repository from going in the pull request.
- `pull` leaves out an edit the source cannot take, such as a changed code block or code block language, a new table row, a folded description, or a deleted label line, and lists it in the pull request body. When that leaves nothing to send for the page (the edits are all reported, or already in GitHub), the reasons go to the Sheet's "Not applied" column, the page returns to "Editing", and the next `push` refreshes the Doc from GitHub. The script never writes the Notes column.
- A line break an editor adds inside a paragraph starts a new paragraph in the source. A new list item goes after the last block of the item above it, its note included, at that item's marker, and a new list opens after a top-level paragraph, so adding items and links to a "Next" list applies. A bullet or number added to or removed from a paragraph applies only its text, and the report says so.
- Author notes follow the Doc. An Author note whose label an editor removed or changed becomes page text and so appears on the site. A paragraph that gains the label becomes an Author note and leaves the site. The pull request reports each change ("an Author note became page text; check it belongs on the site", "a paragraph became an Author note and leaves the site"), and the reviewer decides. When a note or the Description is changed, added or deleted and page text next to it also changes, with no unchanged paragraph between them, the edit applies and the pull request flags it once ("an Author note and the page text beside it changed together; check no text moved between them", and the same with "the Description"), unless one of the two flags above already covers it. A report of an applied edit, an anchor change or an Author note flag, appears in the pull request that carries it and not in the next one. A report of an edit left out appears each time. An Author note emptied down to its label is deleted, and a new paragraph that starts with the label becomes a note.
- A label belongs at the start of its own Doc paragraph. A label typed mid-paragraph is refused. A note joined onto the paragraph before or after it, or Enter pressed in the middle of a note, is refused, or applied with that flag when the page then matches the Doc. A refused region is left unchanged, and the report quotes the editor's text of it. Text crosses a note's edge when a note's words join another paragraph or split off it; a paragraph typed with Enter next to a note is a new paragraph and applies. A paragraph typed with Enter next to a note in a list item is refused and held when the source gives it no list item to join. A refusal also covers a label that is unbolded, a Description or Tab label removed or changed with its text kept, a Note, Tip or Warning label deleted together with a change to its text, a tab line deleted together with a change to the text beside it, a note added or labelled inside a plain `>` quote, a new note that holds `-->`, a heading or list item given the note label, an added paragraph the source has no place for, and an edit beside repeated text where docsync cannot tell which copy changed. Changing Note to Tip or Warning, deleting a callout's label with its text unchanged, and deleting a whole tab line or Description line are reported as not applied and not refused, so the page records its export as applied and the next `push` refreshes the Doc. A refusal is reported as the message, then the Doc's text in a fence, byte for byte. A note inside a list item whose label is removed becomes text in that item, flagged. A line typed above the Description is page text and the Description stays front matter.
- A pull that sends nothing for a page and has a refusal leaves the Doc alone. The page returns to "Editing", the Not applied column holds each refusal's message and quoted Doc text and says to rework the edit or set "Discard my edits", and the page's state records no new applied export, so `push` finds the Doc edited and holds it. Every other report kind records the export as applied, and the next `push` refreshes the Doc from GitHub. When the pull sends a pull request for the page, the refusals go in its body, and the refused text leaves the Doc when that pull request merges and `push` refreshes it. The Not applied cell holds at most 45,000 characters and the pull request body 60,000. Refusal quotes are cut to fit. A cut quote ends with the line "(Shortened here. The full text was in the Doc when this pull ran.)".
- `pull` checks that the merged file reads in the source dialect, as `push` reads it. When it does not, nothing is sent for the page, the run exits 1, and the page is held like a refusal: the Not applied column says "the edits would leave a file docsync cannot read: <error>; nothing sent" and the Doc keeps the editor's text.
- When upstream and an editor changed different words of one paragraph, both changes stay. When they changed the same words, the pull request applies the editor's text and shows the upstream text beside it.

The exit code is 1 when a page fails. It is 2 when the run stops: no credentials, folder, or Sheet; a git, `gh`, or Google error outside a page; a Page id listed twice, or a missing Page id or Status column, in the Sheet; or a state save that fails. A failed save writes the changed page states to `docsync-unsaved-states-<stamp>.json` in the working directory. In CI the workflow uploads it as the `docsync-unsaved-states` artifact. Run `uv run dfo-docsync restore <file>` to save those states over the stored ones before the next run. `--state-dir <dir>` restores into a local state directory. `restore` refuses when the state has moved since the failed run, because a later run may have saved newer states. Pass `--page <id>` (repeatable) to restore chosen pages, or `--force` to overwrite every page in the file.

To add a source, append its name to `sources` in `docsync.yaml`. It must be an enabled `docs` or `skill` row in `sources.yaml` that `hub.yaml` mounts. For another repository, install the `dfo-docsync` GitHub App on it and add its name to the `repositories:` input of the "Mint a token for dfo-docsync" step in `.github/workflows/docsync.yml`. Then run `push`. [CONTRIBUTING.md](CONTRIBUTING.md) covers writing the pages.

To try a change away from the real folder, make a scratch folder in the shared drive, share it with your account, and point each command at it. A Doc pushed under one folder belongs to that folder alone.

```
uv run dfo-docsync init --folder <scratch folder id>
uv run dfo-docsync push --folder <scratch folder id> --state-dir ./scratch-state
uv run dfo-docsync pull --folder <scratch folder id> --state-dir ./scratch-state --dry-run ./scratch-out
```

Without `--state-dir`, `push` and `pull` read and commit to the `docsync-state` branch on `origin`, so pass it whenever you experiment.

## Working on this repo

```
uv run ruff check .
uv run ruff format .
uv run ty check src/dfo_docs
uv run pytest
```

Run `uv run pre-commit install` once. Pre-commit then blocks a commit that fails these checks.

## When the build fails

The build checks every enabled repository before it exits, so the log names every failure in one run.

**A source repository cannot be cloned.** The repository was renamed, made private, or deleted. Fix the `repo` field in `sources.yaml`, or disable the row.

**An empty docs directory.** The source repository renamed its `docs_dir`. Update `docs_dir` in `sources.yaml` to match.

**A leaked `::: ` directive.** A repository is publishing mkdocstrings-generated reference through the normal build path. Exclude the pages that carry it, or move the whole repository to the self-published tier with `kind: external`.

**A sidecar declaring no nav.** The source would publish nothing. In a `zensical.toml` this is usually a `nav` array written after a `[project.<table>]` header, which TOML scopes into that table instead of into `[project]`. Move the array above every sub-table header.

**A skill directory without a `SKILL.md`, or with front matter that does not parse.** The build names the directory or file. Add the `SKILL.md`, fix its front matter so it carries a `name` and a `description`, or move the directory out of the row's `docs_dir` and `internal_dir` if it is not a skill.

**A skill directory of the same name under both `docs_dir` and `internal_dir`.** The build names both. A skill's directory name is its page address, so keep one.

**A `categories.yaml` that does not parse, or lists a skill twice.** The build names the file. Give `sources` a list of skill directories and `domains` a mapping from each domain to such a list, and list each skill once.

**An exclude pattern matching nothing.** A page an `exclude` row named was renamed or removed upstream. Update the pattern in `sources.yaml`, or drop it if the page is gone for good.
