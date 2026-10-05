---
description: Short definitions of the DFO's own terms, from bundle to Wikibase, each linked to the page that explains it.
---

# Glossary

This glossary defines terms used by the DFO, in alphabetical order. The [ontology](ontology.md) defines development finance terms such as ODA and grant equivalent, and the skills explain how to use them.

## Artifact digest

The SHA-256 of one downloadable file, written `sha256:` and 64 hex characters. One `content_version` can have several artifacts, such as a CSV file, a zipped bundle, and a per-series summary in Parquet. See [Versions and snapshots](versions.md).

## Bundle

The zip a download comes in by default: the data file plus `datapackage.json`, `CITATION.cff` and a README. See [The data bundle](bundle.md).

## Classification

A coded list a source uses to describe its data, such as CRS purpose codes or finance types. Each code is a node in the knowledge graph, for example `CRSPurposeCode12220` for basic health care. See [The development finance ontology](ontology.md#source-codes).

## Collection

A set of specs registered together under one `col_` id. A collection downloads as one bundle with a data file per member. See [The data bundle](bundle.md#collections).

## `content_version`

The identifier for one materialised result of a spec, written `cv_` and 32 hex characters, for example `cv_5b7870b8161a6995a2b87d1bde5427ab`. It changes when the rows, selected facets, graph or source revisions, or conversion inputs change. See [Versions and snapshots](versions.md).

## Data Commons

The open-source graph platform, from Google, that serves the DFO knowledge graph. The DFO reuses its nodes for places, such as `country/NGA`, and adds its own for development finance. See [The knowledge graph](knowledge-graph.md).

## dcid

The id of a node in the knowledge graph, for example `country/FRA` or `CRSTypeOfFinance110`. Every entity, classification value, StatVar and provenance has one. See [The knowledge graph](knowledge-graph.md).

## Definition

A spec fetched by its `spec_id` alone. It re-runs the question against the live graph, so it can return newer data than last time. See [Versions and snapshots](versions.md).

## Entity

A party an observation is about, such as a country or an organisation, named by its dcid. See [The knowledge graph](knowledge-graph.md).

## Facet

One edition of a number, told apart from other editions by its provenance, unit and measurement method. See [The knowledge graph](knowledge-graph.md#facets).

## Frame reference

The pair `{spec_id, content_version}`, which identifies one saved data table. The Data MCP's `get_data` tool returns one and the analysis tools take one. See [Versions and snapshots](versions.md).

## Grant equivalent

A development finance measure defined in the ontology. In the graph it is the measured property `grantEquivalent`, so a CRS grant equivalent is a separate StatVar from a disbursement. See [The knowledge graph](knowledge-graph.md#what-each-column-becomes).

## Knowledge graph

The graph that holds every source the DFO ingests, with provenance on every observation. See [The knowledge graph](knowledge-graph.md).

## Live link

A share link that re-runs its query each time it opens, so it shows the latest data. The alternative is a snapshot link. See [Share live data or a snapshot](../build/share.md).

## Observation

One number in the graph: a StatVar, its entities in their roles, a date, a value and a unit. See [The knowledge graph](knowledge-graph.md#the-observation).

## Ontology

The DFO's model of development finance includes the classes, properties, and classification values used to build StatVars. The DFO edits the model in a public Wikibase. See [The development finance ontology](ontology.md).

## Pin

Pinning has two meanings. In Studio, it puts a card on the canvas. On the Datasets API, it keeps a snapshot's file with no expiry. See [Use Studio](../get-started/use-studio.md) and [Versions and snapshots](versions.md).

## Price basis

Whether money is in current prices, as the source reported it, or in constant prices of a base year. See [Methods](methods.md).

## Provenance

A provenance is the graph node that records a number's publisher, licence, and last refresh. `provenance/OECDCreditorReportingSystem` is the CRS one. See [The knowledge graph](knowledge-graph.md#facets).

## Reproducing call

The API call stored inside a bundle's `datapackage.json` that rebuilds the dataset from its `spec_id`. See [The data bundle](bundle.md#the-reproducing-call).

## Role

The position an entity holds on an observation, such as `financingProvider` or `financingRecipient`. A spec keys roles by flow axis, `origin` or `destination`. See [The knowledge graph](knowledge-graph.md#roles).

## Skill

A package of domain knowledge, such as definitions, methodological rules and analytical recipes, that an assistant can load for a development finance question. See [What a skill is](../skills/what-a-skill-is.md).

## Slot

One property a spec constrains, such as `crsPurpose`, with its binding: a value, a set of values, or unbound. See [Versions and snapshots](versions.md).

## Snapshot

A spec fetched by the pair `spec_id` and `content_version`. It serves the stored rows exactly as first retrieved, for 30 days or with no expiry once pinned. See [Versions and snapshots](versions.md).

## Spec

The DFO's exact reading of a data request, written as graph references. It names a region of the knowledge graph and holds no data. See [Versions and snapshots](versions.md).

## `spec_id`

The id of a spec, written `spec_` and 32 hex characters, for example `spec_19e75bf0f03c57ec5445816962ae3896`. It hashes the request, so the same question always gets the same id. See [Versions and snapshots](versions.md).

## StatVar

A statistical variable (StatVar) defines one kind of number precisely enough to compare observations, such as ODA gross disbursements for basic health care as standard grants. See [The knowledge graph](knowledge-graph.md#the-statvar).

## Wikibase

The public site, [developmentfinance.wikibase.cloud](https://developmentfinance.wikibase.cloud), where the DFO ontology is edited. Its items compile into the concepts the knowledge graph uses. See [The development finance ontology](ontology.md).

## Next

- [The knowledge graph](knowledge-graph.md) follows one CRS record into StatVars and observations, where most of these terms appear together.
- [Versions and snapshots](versions.md) explains specs, content versions and artifact digests.
