"""Shared data model for dfo-docs.

Every module in this package reads and returns these types rather than growing its own shapes.
Fixing them here is what lets sidecar parsing, fetch, normalise, manifest assembly, and the guards
be built and changed independently of one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# The published manifest envelope's `schema_version`. See `Manifest`.
SCHEMA_VERSION = 2

# The published roadmap index's `schema_version`. See `RoadmapIndex`. Versioned independently of
# SCHEMA_VERSION and of ROADMAP_TRACK_SCHEMA_VERSION, since the index and a track document are
# separate documents with separate consumers.
ROADMAP_INDEX_SCHEMA_VERSION = 1

# The published roadmap track document's `schema_version`, shared by every track. See
# `RoadmapTrack`. Bumps when a field is removed or renamed, when a field's meaning changes, or
# when a value is added to `EntryStatus`. Adding a category to a track does not bump it, since
# categories are that document's own data rather than fixed in the schema.
ROADMAP_TRACK_SCHEMA_VERSION = 1


class SourceKind(StrEnum):
    """How a registered repository's documentation reaches the corpus."""

    DOCS = "docs"
    """Fetched, normalised, and copied into the corpus as pages."""

    EXTERNAL = "external"
    """Published on its own domain. The manifest carries a URL instead of a file."""

    SKILL = "skill"
    """A repository of agent skills, one directory per skill under `docs_dir`, each with a
    `SKILL.md` and optional `references/*.md`. Fetched like a docs source, but walked by
    `skills.load_skills` instead of a sidecar."""


# The kinds `fetch.fetch_source` clones. An external row publishes a URL and is never fetched.
FETCHED_KINDS = frozenset({SourceKind.DOCS, SourceKind.SKILL})


class PageKind(StrEnum):
    """The `kind` discriminator on a manifest.json entry. Matches the published manifest contract."""

    PAGE = "page"
    """Markdown in the corpus."""

    EXTERNAL = "external"
    """A package that publishes its own docs elsewhere. A card linking out, not a rendered page."""

    SKILL = "skill"
    """A skill's `SKILL.md`, carried in the corpus like a page. Its reference files are pages."""


@dataclass(frozen=True)
class Source:
    """One row of sources.yaml, a repository the build fetches, or one it only points at.

    Every row loads, enabled or not, so a disabled row can still be reported by name and flipping
    it on is a one-line edit. `ref` and `commit` are both always present so a tracked branch and a
    pinned release tag are the same shape. `ref` selects the branch cloned. `commit`, when set,
    pins the exact commit checked out within it. `path` is the public path this row expects to
    publish at. For a `kind: docs` row, the sidecar the row's own repository carries is
    authoritative, and this field is only an assertion checked against it: a mismatch is an error
    naming both. For a `kind: external` or `kind: skill` row, which has no sidecar, this field
    and `title` are authoritative outright.

    `enabled` admits a whole repository. `exclude` is the same admission decision at page
    granularity, and both belong here rather than in the sidecar: the sidecar is authoritative on
    what a source's documentation *is*, and sources.yaml decides what this corpus takes from it.
    """

    name: str
    repo: str
    kind: SourceKind = SourceKind.DOCS
    ref: str | None = "main"
    commit: str | None = None
    docs_dir: str | None = "docs"
    path: str | None = None
    url: str | None = None
    title: str | None = None
    enabled: bool = True
    reason: str | None = None
    exclude: tuple[str, ...] = ()
    """Glob patterns, matched against a nav entry's docs-root-relative path, kept out of the corpus.

    A pattern matching nothing is an error rather than a no-op, so a pattern left behind by an
    upstream rename is reported instead of silently admitting the pages it used to hold out.
    """


@dataclass(frozen=True)
class HubNode:
    """One node in hub.yaml's nav tree, a hub page, a grouping heading, or a mount point.

    Exactly one of `page`, `mount`, or `external` is set on a leaf. `mount` and `external` carry a
    Source.name to look up in the registry. A pure grouping heading (for example "bblocks" or
    "ODA", which exist in no source repository) sets none of them and carries `children` instead.

    A mount or external leaf's own display title comes from its source (a sidecar's title for a
    docs source, `Source.title` for an external one) rather than from this tree, so a leaf
    ordinarily leaves `title` unset.
    """

    title: str | None = None
    page: str | None = None
    mount: str | None = None
    external: str | None = None
    children: tuple[HubNode, ...] = ()


@dataclass(frozen=True)
class NavEntry:
    """One page in a source repository's own sidecar nav, in nav order.

    `breadcrumb` carries the titles of the nav groups this entry is nested under within its own
    repository (empty for a top-level entry). `manifest.build_pages` rebuilds the published nav
    tree's nesting from consecutive runs of it.
    """

    file: str
    title: str | None
    breadcrumb: tuple[str, ...]


@dataclass(frozen=True)
class Sidecar:
    """A parsed docs sidecar, carrying the public path, the display title, and the nav it declares."""

    path: str
    title: str
    description: str | None
    nav: tuple[NavEntry, ...]
    docs_root: Path
    excluded: tuple[str, ...] = ()
    """Files the sidecar navigates that `Source.exclude` kept out of `nav`, in nav order.

    Recorded so `guards.check_nav_drift` can tell a deliberately excluded file from one the
    source's own nav forgot. Without it every excluded file would warn on every build.
    """
    docs_url: str | None = None
    """The fully resolved base URL of the source's own published documentation, read from
    `extra.dfo.docs_url` and nowhere else.

    Absent is legal: most sources carry no excluded page, so nothing ever needs it. There is
    no fallback to `site_url`, which a source's own generator may serve from a version-pinned
    segment (`mike`'s `latest/`, for tossd-reader) that `site_url` itself does not carry; a
    fallback that is silently wrong in its only known case is worse than none.
    `normalise.normalise_links` raises when a link into `Sidecar.excluded` needs this and
    finds it unset.
    """


@dataclass(frozen=True)
class Fetched:
    """The result of fetching one Source, where it landed on disk and what commit it resolved to."""

    source: Source
    repo_root: Path
    docs_root: Path
    commit: str


@dataclass(frozen=True)
class Page:
    """One manifest.json entry.

    Field names match the published manifest contract exactly, plus
    `corpus_path`, the corpus-relative location of the file, which is what lets the site resolve a
    corpus-internal `.md` link target to a route. `source_path`, `source_commit`, `last_modified`,
    and `corpus_path` are all `None` for a `kind=external` entry, which carries `url` instead.

    Carries neither an ordering field nor a breadcrumb. The nav tree (`NavNode`) is the sole
    authority on where a page sits, and a consumer that needs a breadcrumb walks that tree, which
    it already walks to render a sidebar. Publishing a second, flattened copy of a page's position
    would invite a consumer to trust it over the tree it came from.
    """

    id: str
    path: str
    title: str
    kind: PageKind
    description: str
    source_repo: str
    source_path: str | None
    source_commit: str | None
    last_modified: str | None
    corpus_path: str | None
    url: str | None = None


class NavKind(StrEnum):
    """The `kind` discriminator on a manifest.json nav node."""

    GROUP = "group"
    """A grouping heading or a mounted source, carrying `children`."""

    PAGE = "page"
    """A leaf pointing at a `Page`. Its `id` is that page's `id`."""

    EXTERNAL = "external"
    """A leaf pointing at a `kind: external` `Page`. Its `id` is that page's `id`."""


@dataclass(frozen=True)
class NavNode:
    """One node of the manifest's `nav` tree, the sole ordering authority for the published
    artefact.

    A `page` or `external` node's `id` joins to the `Page` it renders. A `group` node's `id` is
    opaque, `group:` followed by a `/`-joined key path from the nav root, and carries `page_id`
    (the same join, onto a `Page`) only when the group has a landing page.

    A node carries `title` and no address. A group's title is a real declaration, coming from
    hub.yaml or a source's sidecar, and five of the six groups that have a landing page are titled
    differently from it, so it survives nowhere else. An address is the `Page`'s, reached by the
    `id` join this contract already tells consumers to use; carrying `path` here too would put the
    join it warns against on the very record that warns about it.
    """

    id: str
    title: str
    kind: NavKind
    page_id: str | None = None
    children: tuple[NavNode, ...] = ()


@dataclass(frozen=True)
class Manifest:
    """The published manifest.json envelope.

    `schema_version` (see `SCHEMA_VERSION`) is the sole compatibility signal a consumer checks.
    `nav` is the authority on navigation and on where every page sits, and the `pages` array's own
    order carries no meaning.
    """

    schema_version: int
    generated_at: str
    generator_commit: str | None
    nav: tuple[NavNode, ...]
    pages: tuple[Page, ...]


class EntryStatus(StrEnum):
    """The closed value set of a roadmap entry's `status`, matching roadmap-track.schema.json's
    `status` enum exactly.

    Which view and which section an entry renders in, and the one field a track document carries
    whose value set is closed: RELEASED renders in the released view, and the other three are the
    upcoming view's three sections, in that order. Status is the sole axis; there is no separate
    view field, which is what stops an entry being marked both upcoming and released at once. A
    fifth value here is a breaking change to the published contract and bumps
    ROADMAP_TRACK_SCHEMA_VERSION; adding a category does not.
    """

    UNDER_CONSIDERATION = "under-consideration"
    PLANNED = "planned"
    IN_DEVELOPMENT = "in-development"
    RELEASED = "released"


@dataclass(frozen=True)
class RoadmapCategory:
    """One filter chip declared by a track document.

    `id` is what a `RoadmapEntry.categories` entry references and what any stored state (chip
    counts, a future vote store) keys on; `label` is display text and may be changed freely. A
    track declares this list rather than the loader deriving it from the entries it holds,
    because a label like "Aid & ODA" does not survive the round trip through an id like
    `aid-oda`, because display order here is an editorial choice rather than an alphabetisation,
    and because a category id an entry names but this list omits is a build error rather than a
    chip silently labelled with a typo.
    """

    id: str
    label: str


@dataclass(frozen=True)
class RoadmapEntry:
    """One roadmap item, published inside its track's document.

    An entry keeps its `id` for its whole life as `status` moves it from under-consideration to
    released, which is what lets votes and any other state a consumer stores against the id
    survive that move. `title` and `description` carry no version and no date, even once
    released; the site composes those from `version` and `released_on`. `expected` is required
    on a `planned` or `in-development` entry and forbidden on `released`, which carries
    `released_on` (required) and `version` (optional) instead; an `under-consideration` entry may
    carry none of the three, being by definition unscheduled. The track schema enforces these
    combinations; this dataclass only carries the fields, so a caller that skips the loader's
    validation can still construct a shape the schema would reject.
    """

    id: str
    title: str
    description: str
    status: EntryStatus
    categories: tuple[str, ...] = ()
    expected: str | None = None
    released_on: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class RoadmapTrack:
    """One track document, published at the path its `RoadmapIndex` entry names, such as
    `roadmap/data.json`.

    Holds one tab's own category vocabulary and every entry in it, upcoming and released
    together; `entries`' own order carries no meaning; a consumer splits it by `status` into the
    upcoming and released views, then groups and sorts within each. `track` is this document's own
    id, matching the `RoadmapIndex` entry that points here; the build checks the two agree, since
    an entry carries no `track` field of its own and this is the single authority on which tab it
    belongs to. `schema_version` is versioned independently of the index (see
    `ROADMAP_TRACK_SCHEMA_VERSION`), since each is a separate document a consumer may fetch and
    validate on its own.
    """

    schema_version: int
    generated_at: str
    generator_commit: str | None
    track: str
    categories: tuple[RoadmapCategory, ...]
    entries: tuple[RoadmapEntry, ...]


@dataclass(frozen=True)
class RoadmapTrackRef:
    """One tab in the published roadmap index, and a pointer to the `RoadmapTrack` document
    behind it.

    `id` matches the `track` field of the document at `file`, which the build checks. `label` is
    this tab's display text and may be changed freely, since `id` is what anything stored keys
    on. A track stays listed here while its document holds no entries, so an empty tab renders an
    empty state rather than vanishing.
    """

    id: str
    label: str
    file: str
    description: str | None = None


@dataclass(frozen=True)
class RoadmapIndex:
    """The published roadmap.json envelope, fetched first so the site can render the tabs and
    then load a track's own document when its tab is opened.

    `tracks` is in the order tabs render, first as the default tab. This index carries no entry
    counts: a count declared here could disagree with the document it describes, so a consumer
    fetches a track's own document to learn what is in it. `schema_version` is versioned
    independently of a track document's own (see `ROADMAP_INDEX_SCHEMA_VERSION`); adding or
    removing a track leaves it alone, since tracks are this document's own data rather than a
    fixed enum.
    """

    schema_version: int
    generated_at: str
    generator_commit: str | None
    tracks: tuple[RoadmapTrackRef, ...]
