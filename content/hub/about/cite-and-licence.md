---
description: How to cite data from the DFO, credit its original publisher, and find each source's licence.
---

# Cite and licence

When you want to cite data from the DFO, credit the organisation that first published the data, then cite the Development Finance Observatory as the route through which you found it.

## Cite a result from /data

Use the short form in a chart caption or footnote:

```
OECD Creditor Reporting System (2026), via the Development Finance Observatory
```

Use the full form in a reference list:

```
OECD, Creditor Reporting System (2026), via the Development Finance Observatory. "Gross disbursements (nominal) for basic health care for standard grant for official development assistance to Togo from France" [dataset]. Retrieved 28 September 2026 from https://developmentfinance.org/s/{id} (snapshot, data as of 28 Sep 2026).
```

<!-- TODO: replace {id} with the id of a real snapshot link once the production site is public. -->

<!-- TODO: verify whether a source's "Last Update" on /data/sources is the publisher's release date or the day the DFO last pulled the file, and state which year the citation uses. -->

## Live and snapshot links

Cite a snapshot link, made with **Share** and the **Snapshot** tab. It keeps the cited numbers fixed and opens with the banner "Snapshot · data as of 28 Sep 2026", the day the data was captured. A live link reruns the search and can show different numbers after a source refresh. Use the day you read the data as the retrieval date. [Share live data or a snapshot](../build/share.md) shows how to make both.

## When to write "via"

Use "via" when the DFO passes the source's figures through unchanged. When the DFO has changed the figures, for example by converting them to another currency, write "processed by the Development Finance Observatory".

<!-- TODO: add a worked "processed by" example once the Datasets API performs currency conversion; it refuses conversion requests today. -->

## Cite a Studio card

Cite a Studio card in the same form. Use its title as the dataset title, the source named on its source line or in its "More Info" panel, and the day you read the data as the retrieval date.

## Licences

Each source's licence governs its data. Find it on the source's page on [Sources](/data/sources), under "License & Updates". The [CRS page](/data/sources/provenance/OECDCreditorReportingSystem), for example, links to the [OECD Terms and Conditions](https://www.oecd.org/en/about/terms-conditions.html).

A bundle carries each source's licence in `SOURCES.md` and `datapackage.json`.

ONE Data's Python packages, such as [oda_reader](https://github.com/ONEcampaign/oda_reader) and [imf-reader](https://github.com/ONEcampaign/imf-reader), state their licences in their GitHub repositories.

<!-- TODO: state the licence of the DFO skills and the ontology Wikibase once each declares one. -->

## Next

- [Share live data or a snapshot](../build/share.md) shows how to make the snapshot link you cite.
- [Versions and snapshots](../data/versions.md) explains the ids that fetch the exact rows in code.
- [The data bundle](../data/bundle.md) lists every file in a download.
