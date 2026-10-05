---
description: How each DFO figure traces back to its source file, what the DFO changes as it loads the data into the knowledge graph, and how to check a figure against its source.
---

# Where the numbers come from

Every figure in the DFO starts as a file its source publishes. The DFO fetches that file, checks it, maps its codes onto shared concepts, and loads the result into one [knowledge graph](knowledge-graph.md). Search on [/data](/data), DFO Studio, the DFO API and the DFO MCP server all read that graph, so the same question returns the same numbers on every surface.

```mermaid
flowchart TD
    file["the source's file<br/>as its publisher releases it"]
    checks["checks<br/>a failed check stops the release"]
    codes["codes mapped to shared concepts<br/>e.g. CRS purpose 12220 → CRSPurposeCode12220"]
    graph["the knowledge graph"]
    search["/data search"]
    studio["DFO Studio"]
    api["the DFO API"]
    mcp["the DFO MCP server"]
    file --> checks --> codes --> graph
    graph --> search
    graph --> studio
    graph --> api
    graph --> mcp
```

Some series enter the graph through a different route. Data Commons, which underlies the DFO's graph, runs its own imports of datasets such as the World Bank's World Development Indicators. Those series carry a provenance that begins `dc/base/`, and [Methods](methods.md) shows how to read it.

The rest of this page uses the OECD's Creditor Reporting System (CRS), a record of each aid activity donors report, as its worked example.

## What the DFO changes and preserves

Values keep the currency and prices their source reports. In the CRS, for example, amounts are in current US dollars, so each CRS amount has the unit `CurrencyUSD` and a StatVar whose dcid ends in `Nominal` to mark current prices.

The DFO stores amounts in whole units. Where a source reports in thousands or millions, the DFO multiplies to whole values. The CRS reports amounts in millions, so France's 2008 basic health care grants to Togo total 3.97253 in the CRS file and 3,972,530 in the graph.

<!-- TODO: confirm unit scaling for each source as its pipeline starts loading into the graph; the CRS is the one verified case. -->

The DFO maps each source's codes to shared concepts, so the same country or purpose has one identifier across sources. In the CRS, purpose 12220 becomes `CRSPurposeCode12220`, and OECD Development Assistance Committee (DAC) donor code 4 becomes `country/FRA`. [The development finance ontology](ontology.md) explains how a source code becomes a graph identifier and where to look codes up.

A source that reports individual records is summed into series over its coded dimensions. The CRS file, for example, has one row per reported activity, with the agency, channel, and project behind it. For the CRS, the DFO keeps seven coded columns: year, donor, recipient, flow type, finance type, modality, and purpose. It sums every record that shares all seven. France's basic health care grants to Togo in 2008 appear in the graph as one figure, however many projects France reported. A DFO figure from a record-level source is the sum of the rows that share its codes. Agency, channel, and project details remain in the source.

<!-- TODO: name the summed dimensions for each further record-level source as its pipeline loads into the graph. -->

Every other measure passes through as the source reports it. From the CRS, the DFO calculates net disbursement. The CRS reports gross disbursements and amounts received back in separate columns, and the DFO subtracts amounts received back from gross disbursements. A record that reports a repayment without a disbursement counts as a negative net disbursement. Commitments, gross disbursements, and grant equivalents pass through as reported.

The DFO converts currencies only when a request asks for it. [Methods](methods.md) describes conversion requests and the formula used.

## How to check a figure against its source

Start with the source's page on [Sources](/data/sources). Its "License & Updates" block gives the licence, the update cadence, and the last update, which is the day the DFO downloaded the release in the graph. The page also links to the publisher's own page for the data.

Take a snapshot link from /data. It pins the exact rows behind the figure, so you compare against the release the DFO used.

Compare the figure with the same release from the source. Keep the source's rows that match the figure's codes, sum the column for the figure's measure, and scale to whole units.

For a CRS figure, use the CRS file from the same release and keep rows with the figure's year, donor, recipient, flow type, finance type, modality, and purpose. Sum the column for that measure: `usd_disbursement` for gross disbursements, `usd_commitment` for commitments, or `usd_grant_equiv` for grant equivalents. Multiply by a million. The result matches the DFO figure within rounding. The DFO holds each CRS amount to five decimal places in millions, the nearest ten dollars.

## How fresh the data is

Each source publishes on its own calendar, and its page on [Sources](/data/sources) shows its update cadence. The OECD, for example, publishes the CRS four times a year, in April, June, September and December.

The DFO checks each source daily for a new release. It reads the publisher's release marker, such as the version on the OECD's CRS bulk file or the release date of the IMF's World Economic Outlook. A changed marker triggers the pipeline to download the data, rerun its checks and models, and rebuild the files the graph loads. A failed check stops the release, so the graph keeps the previous release.

<!-- TODO: verify how long a rebuilt import takes to reach the graph, and say so here. -->

A live link reruns the question against the graph and returns the new release once the graph has loaded it. A snapshot keeps the rows it captured.

## What's open

The ontology is public. Every concept the graph uses, from a purpose code to a type of finance, is an item in the Wikibase at [developmentfinance.wikibase.cloud](https://developmentfinance.wikibase.cloud/wiki/Main_Page), with its definition, its place in the hierarchy, and the source code it represents. CRS purpose 12220, for example, is [Q44](https://developmentfinance.wikibase.cloud/wiki/Item:Q44). [The development finance ontology](ontology.md) explains how the items are organised.

The packages the pipelines use to fetch sources are open source. The OECD's DAC statistics, including the CRS, come through the [ODA reader](../../oda_reader/index.md), and you can run the same `bulk_download_crs` call yourself. The IMF's World Economic Outlook comes through the [IMF reader](../../imf-reader/index.md). [DCP tools](../../dcp-tools/index.md) writes the files the graph loads.

## Next

- [The knowledge graph](knowledge-graph.md) follows the 2008 French grant to Togo from its CRS row to a graph observation, column by column.
- [Versions and snapshots](versions.md) explains the snapshot link to cite and the ids that reproduce the exact rows in code.
