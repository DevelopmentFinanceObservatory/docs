---
description: What spec_id and content_version name, how a definition differs from a snapshot, and which ids reproduce the exact rows in code.
---

# Versions and snapshots

A StatVar defines one kind of number, and a dcid identifies a graph node. [The knowledge graph](knowledge-graph.md) explains both.

Every DFO dataset carries two ids. The `spec_id` names the question. The `content_version` names one answer to it, the exact rows retrieved at one moment. Share links, downloads and analysis tools use both ids.

```
spec_19e75bf0f03c57ec5445816962ae3896   ODA standard grants for basic health care, France to Togo
cv_5b7870b8161a6995a2b87d1bde5427ab     the 33 rows it returns until the OECD revises the data
```

## The spec and its `spec_id`

A spec is the DFO's exact reading of a data request, written as graph references. It names a region of the knowledge graph and holds no data. Here is the identity of the spec above, taken from a Search response:

```json
{
  "identity_version": "spec1",
  "shape": {
    "kind": "statvar_schema",
    "population_type": "FinancialFlow",
    "measured_property": "amount",
    "stat_type": "measuredValue",
    "measurement_qualifier": "Nominal"
  },
  "slots": [
    {"property": "crsCooperationModality", "binding": {"state": "unbound"}},
    {"property": "crsPurpose", "binding": {"state": "value", "ref": "CRSPurposeCode12220"}},
    {"property": "crsTypeOfFinance", "binding": {"state": "value", "ref": "CRSTypeOfFinance110"}},
    {"property": "crsTypeOfFlow", "binding": {"state": "value", "ref": "CRSTypeOfFlow10"}},
    {"property": "financialFlowType", "binding": {"state": "value", "ref": "Disbursement"}},
    {"property": "nettingBasis", "binding": {"state": "value", "ref": "Gross"}}
  ],
  "entities": {"destination": ["country/TGO"], "origin": ["country/FRA"]},
  "requested_window": {"kind": "all"}
}
```

The `spec_id` is `spec_` followed by the first 32 hex characters of a SHA-256 over the canonical form of that identity. Canonical means aliases resolved to graph references, strings normalised, sets sorted, and the result serialised with JSON Canonicalization (RFC 8785). Different wording can produce the same `spec_id` when the requests resolve to the same canonical form. A general grants request binds finance type to `CRSTypeOfFinance100`. The request for standard grants binds it to `CRSTypeOfFinance110`, so the ids differ:

```
{"spec_id":"spec_19e75bf0f03c57ec5445816962ae3896","finance":"CRSTypeOfFinance110"}
{"spec_id":"spec_49b9c86d57db2e6b708c2187ddfb4307","finance":"CRSTypeOfFinance100"}
```

```bash
DFO_API=https://dfo-dev-apis-zms5lj4zhq-nn.a.run.app
for q in "ODA standard grants for basic health care from France to Togo" \
         "ODA grants for basic health care from France to Togo"; do
  curl -s -X POST "$DFO_API/api/search/resolve" \
    -H 'Content-Type: application/json' \
    -d "{\"input\":{\"kind\":\"raw_text\",\"query\":\"$q\"}}" |
    jq -c '.parts[0].spec | {spec_id, finance: (.definition.identity.slots[] | select(.property=="crsTypeOfFinance") | .binding.ref)}'
done
```

The hash covers the request's canonical identity. It excludes the StatVars the spec resolves to, the years with data and the facet the platform picks. This keeps the id stable when a source adds a year or the graph gains a StatVar. Here `requested_window` is `all`, so the same `spec_id` covers 2025 when the CRS publishes it.

Searching only computes a `spec_id`. The first download, share link or explicit registration writes the definition to the registry, where anyone can fetch it by id.

## The `content_version`

A `content_version` is `cv_` followed by 32 hex characters. It digests the materialised rows themselves, together with the facet chosen on each axis, the graph and source revisions read, and any currency conversion applied with its rate-table versions. The same rows, facet choices, graph and source revisions, and conversion inputs yield the same `content_version`. Fetching the spec above twice on the same day returns `cv_5b7870b8161a6995a2b87d1bde5427ab` both times. When the OECD revises a figure, the next fetch returns a new one.

One `spec_id` collects many `content_version`s over time. One `content_version` can be rendered as CSV, Excel, Parquet or a zipped [bundle](bundle.md), and each rendering is a separate file named by its own `artifact_digest` (`sha256:` and 64 hex characters).

<!-- TODO: the dev deployment reports graph_revision as "unavailable:dfo-dcp-revision-endpoint-absent" with a revision_unavailable warning in every manifest. Describe graph_revision here once the revision endpoint exists. -->

## Definitions and snapshots

A definition and a snapshot retrieve data in different ways.

A definition is the `spec_id` alone. Fetching it re-runs the question against the live graph and can return newer data:

```json
{
  "content_version": "cv_5b7870b8161a6995a2b87d1bde5427ab",
  "window": {
    "kind": "all",
    "origin": "default",
    "end_year": 2024,
    "start_year": 2003
  }
}
```

```bash
curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896" |
  jq '{content_version, window: .coverage.window}'
```

A snapshot is the pair. Fetching it serves the stored record and files exactly as first materialised from storage alone:

```json
{
  "spec_id": "spec_19e75bf0f03c57ec5445816962ae3896",
  "content_version": "cv_5b7870b8161a6995a2b87d1bde5427ab",
  "rows": 33,
  "artifacts": [
    {
      "artifact_digest": "sha256:341d3709615fba52131ca035a05fc641986a3548be8661fa69ddd77ca1b95e79",
      "tier": "working",
      "url_expires_at": "2026-09-28T06:45:35.518765+00:00"
    },
    …
  ]
}
```

```bash
curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896/cv_5b7870b8161a6995a2b87d1bde5427ab" |
  jq '{spec_id: .definition.spec_id, content_version, rows: .coverage.rows, artifacts: [.artifacts[] | {artifact_digest, tier, url_expires_at}]}'
```

Each artifact carries a signed download URL that lasts 15 minutes. Fetch the snapshot again for a fresh one.

Snapshot files live in two tiers. The working tier keeps them for 30 days from storage. Downloads do not reset the clock. After 30 days, the snapshot returns `410` with code `artifact_expired` and points to the definition. Pinning copies an artifact to the pinned tier, where it has no expiry. The API supports pinning as a first-party operation. Its route requires a principal header granted by the DFO, and the API's capabilities report `programmatic_pinning: false`.

!!! warning
    The snapshot route serves stored files only. After expiry, fetch the definition to retrieve current rows. The `content_version` stays the same while those rows are unchanged.

## Where the ids appear

- Share links on `/data` are short `/s/…` links. A live link stores the `spec_id` and replays the definition each time it opens. A snapshot link stores the `spec_id` and `content_version`, and the site pins the snapshot when it can. Studio links are always snapshots. [Share live data or a snapshot](../build/share.md) covers the choice.
- A download is named `{spec_id}.{content_version}.zip`, and its `CITATION.cff` title and `datapackage.json` carry the `spec_id`. [The data bundle](bundle.md) lists each file.
- The Data MCP's `get_data` tool returns a frame reference, the pair `{spec_id, content_version}`, and every analysis tool takes one. <!-- TODO: link the Data MCP guide when it is public. -->

## Reproduce the exact rows in code

Keep both ids with a script, notebook or replication package. The `content_version` fetches the exact rows you used for as long as the snapshot is kept. The `spec_id` reruns your question on current data after the snapshot expires, and those rows may differ from the ones you used.

Use a snapshot link to cite the data in a report. [Cite and licence](../about/cite-and-licence.md) shows the format.

## Next

- [The data bundle](bundle.md) lists what a download contains, including the call that reproduces it.
- [Share live data or a snapshot](../build/share.md) shows how to pick between the two kinds of link on `/data`.
