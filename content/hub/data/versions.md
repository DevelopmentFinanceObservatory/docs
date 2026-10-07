---
description: What spec_id and content_version name, how a definition differs from a snapshot, and which ids reproduce the exact rows in code.
---

# Versions and snapshots

A StatVar defines one kind of number, and a dcid identifies a graph node. [The knowledge graph](knowledge-graph.md) explains both.

Every DFO dataset carries two ids. The `spec_id` names the question. The `content_version` names one answer to it, the exact rows retrieved at one moment. Share links, downloads and analysis tools use both. The examples on this page use the dataset for France's basic health care grants to Togo:

```
spec_19e75bf0f03c57ec5445816962ae3896   ODA standard grants for basic health care, France to Togo
cv_bb41020eae566cb1de761425ac5cd493     the rows it returns until the data behind them changes
```

Its `content_version` changes whenever the data behind it does, so a fetch today may return a different one.

## The spec and its `spec_id`

A spec is the DFO's exact reading of a data request, written as graph references. It describes which observations to fetch and holds no data. Here is the identity of the spec above, taken from a Search response:

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

The `spec_id` is `spec_` followed by the first 32 hex characters of a SHA-256 over the canonical form of that identity. Canonical means aliases resolved to graph references, strings normalised, sets sorted, and the result serialised with JSON Canonicalization (RFC 8785). Two requests share a `spec_id` only when they resolve to the same canonical form, however they are worded. A request for grants binds finance type to `CRSTypeOfFinance100`, the code for grants in general, and a request for standard grants binds it to `CRSTypeOfFinance110`, so their ids differ:

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

The hash leaves out the StatVars the spec resolves to, the years with data and the facet the platform picks, so the id stays stable when a source adds a year or the graph gains a StatVar. Here `requested_window` is `all`, so the same `spec_id` covers each new year the CRS publishes.

Searching only computes a `spec_id`. The first download, share link or explicit registration writes the definition to the registry, where anyone can fetch it by id.

## The `content_version`

A `content_version` is `cv_` followed by 32 hex characters. It digests the materialised rows, the facet chosen on each axis, the graph and source revisions read, and any currency conversion applied with its rate-table versions. If none of those change, fetching the spec again returns the same `content_version`. When the OECD revises a figure, or the DFO changes how it processes one, the next fetch returns a new one.

One `spec_id` collects many `content_version`s over time. One `content_version` can be rendered as CSV, Excel, Parquet or a zipped [bundle](bundle.md), and each rendering is a separate file identified by its own `artifact_digest` (`sha256:` and 64 hex characters).

<!-- TODO: the dev deployment reports graph_revision as "unavailable:dfo-dcp-revision-endpoint-absent" with a revision_unavailable warning in every manifest. Describe graph_revision here once the revision endpoint exists. -->

## Definitions and snapshots

A definition is the `spec_id` alone. Fetching it re-runs the question against the live graph and can return newer data. Fetching this one returns:

```json
{
  "content_version": "cv_bb41020eae566cb1de761425ac5cd493",
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

A snapshot is the pair. Fetching it serves the stored record and files exactly as they were first made, without querying the graph. In practice you keep the `content_version` from an earlier fetch or download, and fetch the snapshot with it later. The snapshot for this dataset returns:

```json
{
  "spec_id": "spec_19e75bf0f03c57ec5445816962ae3896",
  "content_version": "cv_bb41020eae566cb1de761425ac5cd493",
  "rows": 33,
  "artifacts": [
    {
      "artifact_digest": "sha256:bf9d2f707dcee31f8ac5040666f1041c53968446bd099d1ab738af936419f57a",
      "tier": "working",
      "url_expires_at": "2026-10-06T12:01:29.901464+00:00"
    },
    …
  ]
}
```

```bash
CV=$(curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896" | jq -r .content_version)
curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896/$CV" |
  jq '{spec_id: .definition.spec_id, content_version, rows: .coverage.rows, artifacts: [.artifacts[] | {artifact_digest, tier, url_expires_at}]}'
```

Each artifact carries a signed download URL that lasts 15 minutes. Fetch the snapshot again for a fresh one.

Snapshot files live in one of two tiers. The working tier keeps them for 30 days from when they were stored, and downloading them doesn't reset the clock. After that, the snapshot returns `410` with code `artifact_expired`, pointing to the definition. Pinning copies a file to the pinned tier, where it never expires. Only the DFO's own site can pin.

## Where the ids appear

- Share links on `/data` are short `/s/…` links. A live link stores the `spec_id` and replays the definition each time it opens. A snapshot link stores the `spec_id` and `content_version`, and the site pins the snapshot when it can. A Studio canvas or card link is live or a snapshot, as its owner chose, and the choice is on the link and its embed. Existing Studio links are snapshots. [Share live data or a snapshot](../build/share.md) covers the choice.
- A download is named `dfo_<sources>_<YYYY-MM-DD>_<format>_<version>.zip`, where `<version>` is the first six characters of the `content_version` after `cv_`. Its `datapackage.json` carries the full `spec_id`. [The data bundle](bundle.md) lists each file and name.
- The DFO MCP server's `get_data` tool returns a frame reference, the pair `{spec_id, content_version}`, and every analysis tool takes one. <!-- TODO: link the DFO MCP server guide when it is public. -->

## Reproduce the exact rows in code

Keep both ids with a script, notebook or replication package. The `content_version` fetches the exact rows you used for as long as the snapshot is kept. The `spec_id` reruns your question on current data after the snapshot expires, and those rows may differ from the ones you used.

Use a snapshot link to cite the data in a report. [Cite and licence](../about/cite-and-licence.md) shows the format.

## Next

- [The data bundle](bundle.md) lists what a download contains, including the call that reproduces it.
- [Share live data or a snapshot](../build/share.md) shows how to pick between the two kinds of link on `/data`.
