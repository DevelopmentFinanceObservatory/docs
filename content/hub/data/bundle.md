---
description: The files in a DFO dataset download, what each one holds, and the call inside it that reproduces the dataset.
---

# The data bundle

The examples come from one download of ODA standard grants for basic health care from France to Togo, `spec_19e75bf0f03c57ec5445816962ae3896` at `cv_5b7870b8161a6995a2b87d1bde5427ab`.

A bundle is a zip file that holds the data file and metadata for citation and reproduction. It follows the [Frictionless Data Package v2](https://datapackage.org/) standard, which describes a dataset's files, fields, and sources in `datapackage.json`. Downloads are bundled by default. On `/data`, the "README" and "Sources & Citations" checkboxes in the download menu switch the bundle on and off together. On the Datasets API, the switch is the `bundle` option.

```
spec_19e75bf0f03c57ec5445816962ae3896.cv_5b7870b8161a6995a2b87d1bde5427ab.zip
├── data/data.csv
├── datapackage.json
├── CITATION.cff
└── README.md
```

```
  Length      Date    Time    Name
---------  ---------- -----   ----
    10548  01-01-1980 00:00   data/data.csv
      612  01-01-1980 00:00   CITATION.cff
      734  01-01-1980 00:00   README.md
     4098  01-01-1980 00:00   datapackage.json
---------                     -------
    15992                     4 files
```

```bash
DFO_API=https://dfo-dev-apis-zms5lj4zhq-nn.a.run.app
curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896?format=csv&bundle=true" |
  jq -r '.artifacts[] | select(.rendering.bundle == true) | .url' |
  xargs curl -s -o bundle.zip
unzip -l bundle.zip
```

The zip is named `{spec_id}.{content_version}.zip`. Every entry carries the fixed date 1 January 1980, so the same rows always produce a byte-identical zip with the same `artifact_digest`. [Versions and snapshots](versions.md) explains the two ids.

## `data/data.csv`

Each row is one observation. The file is `data.csv`, `data.xlsx` or `data.parquet`, depending on the `format` option.

```
stat_var,financingProvider,financingRecipient,time_period,value,unit,measurementMethod,provenance,status,stat_var_crsCooperationModality,stat_var_crsPurpose,stat_var_crsTypeOfFinance,stat_var_crsTypeOfFlow
dcid:Amount_FinancialFlow_Gross_Disbursement_CRSTypeOfFlow10_CRSTypeOfFinance110_CRSCooperationModalityC01_CRSPurposeCode12220_Nominal,country/FRA,country/TGO,2008,3972530.0,CurrencyUSD,,provenance/OECDCreditorReportingSystem,,project-type intervention,basic health care,standard grant,official development assistance
…
```

| Column                | Holds                                                                                         |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `stat_var`            | The StatVar dcid, with a `dcid:` prefix.                                                      |
| one column per role   | The entity dcid in that role, here `financingProvider` and `financingRecipient`.              |
| `time_period`         | The observation date.                                                                         |
| `value`               | The number.                                                                                   |
| `unit`                | The unit dcid, here `CurrencyUSD`.                                                            |
| `measurementMethod`   | The facet's measurement method, empty when the source declares none.                          |
| `provenance`          | The facet's provenance dcid.                                                                  |
| `status`              | Reserved for observation status.                                                              |
| `stat_var_<property>` | The label of each classification value in the StatVar, one column per decoded classification. |

## `datapackage.json`

The descriptor follows the Data Package v2 profile. It holds one resource per data file, the sources and licences, and a `dfo` property with the spec and reproducing call.

```json
{
  "$schema": "https://datapackage.org/profiles/2.0/datapackage.json",
  "resources": [
    {
      "name": "data-csv",
      "type": "table",
      "profile": "tabular-data-resource",
      "path": "data/data.csv",
      "mediatype": "text/csv",
      "bytes": 10548,
      "hash": "sha256:09da7e7a8b78d0c3e9c845de217e2d96101b4e6d7aa00165b650af03181608c1",
      "schema": {
        "fields": [
          {"name": "stat_var", "type": "string"},
          {"name": "financingProvider", "type": "string"},
          …
        ]
      },
      "format": "csv",
      "sources": [{"title": "provenance/OECDCreditorReportingSystem"}],
      "licenses": [{"name": "unspecified"}]
    }
  ],
  "licenses": [{"name": "unspecified"}],
  "sources": [{"title": "provenance/OECDCreditorReportingSystem"}],
  "contributors": [{"title": "Development Finance Observatory", "roles": ["publisher"]}],
  "dfo": {
    "spec": {
      "schema_version": 1,
      "spec_id": "spec_19e75bf0f03c57ec5445816962ae3896",
      "identity": { … }
    },
    "reproducing_call": {
      "method": "GET",
      "path": "/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896",
      "options": {"format": "csv", "bundle": "true"},
      "headers": {"Authorization": "Bearer $DFO_API_KEY"}
    }
  }
}
```

| Property                  | Holds                                                                                                                                                     |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$schema`                 | The Data Package v2 profile URL.                                                                                                                          |
| `resources[]`             | One entry per data file: `name`, `path`, `mediatype`, `bytes`, `hash` (the file's SHA-256), an inline Table Schema, and its own `sources` and `licenses`. |
| `resources[].profile`     | `tabular-data-resource`, kept beside `type` so Data Package v1 readers, such as the R `frictionless` package, can open the bundle.                        |
| `licenses[]`, `sources[]` | The distinct licences and sources across all resources.                                                                                                   |
| `contributors[]`          | The DFO as publisher.                                                                                                                                     |
| `dfo.spec`                | The canonical spec definition, verbatim.                                                                                                                  |
| `dfo.reproducing_call`    | The API call that rebuilds the dataset. See below.                                                                                                        |
| `dfo.members`             | Collections only: the member `spec_id`s, sorted.                                                                                                          |

## `CITATION.cff`

A [Citation File Format](https://citation-file-format.github.io/) (CFF) 1.2.0 file, a standard format for machine-readable citations. It is written as JSON, which is valid CFF.

```json
{
  "cff-version": "1.2.0",
  "message": "If you use this dataset, please cite it as below.",
  "type": "dataset",
  "title": "Development Finance Observatory dataset export (spec_19e75bf0f03c57ec5445816962ae3896)",
  "authors": [{"name": "Development Finance Observatory"}],
  "contact": [{"name": "Development Finance Observatory", "alias": "DFO"}],
  "references": [
    {
      "type": "data",
      "title": "provenance/OECDCreditorReportingSystem",
      "authors": [{"name": "Development Finance Observatory"}]
    }
  ]
}
```

Each source is a `references[]` entry. A StatVar with a processing level adds `notes: "Processing level: <level>"` to its entry. To cite the data in a report, use a snapshot link in the form [Cite and licence](../about/cite-and-licence.md) gives.

<!-- TODO: CITATION.cff lists the DFO as author of every source and titles each reference with its graph identifier, such as provenance/OECDCreditorReportingSystem. Describe the authors and titles once dfo-apis writes the publisher's name (ONEcampaign/dfo-apis#981). -->

## `README.md`

A human-readable summary, generated from the same inputs:

````markdown
# Development Finance Observatory dataset export (spec_19e75bf0f03c57ec5445816962ae3896)

Assembled by the Development Finance Observatory (DFO) from the Data Commons graph. See `datapackage.json` for the machine-readable descriptor and `CITATION.cff` for a citation-tool-readable citation.

## Citation

- provenance/OECDCreditorReportingSystem (unspecified)

## Reproducing this dataset

```
GET /api/datasets/spec_19e75bf0f03c57ec5445816962ae3896
options: {"bundle": "true", "format": "csv"}
Authorization: Bearer $DFO_API_KEY
```

## Licence

See each resource's own `sources`/`licenses` properties in `datapackage.json` for the licence covering that resource, and the package-level `licenses` property for the full distinct set.
````

When the source flags any observation as provisional or estimated, the README gains an "Observation qualifications" section, and the descriptor records the same flags on the resource as `qualifications`.

## Licences

Each source's licence is on its page on [Sources](/data/sources). The CRS, for example, is covered by the [OECD Terms and Conditions](https://www.oecd.org/en/about/terms-conditions.html).

<!-- TODO: every bundle records the licence name "unspecified" because the graph has no convention for passing each source's licence into the bundle. Say that datapackage.json carries each source's licence once it does. -->

## The reproducing call

`dfo.reproducing_call` uses the canonical definition's `spec_id` and rendering options, without the original request. Run it as a GET with the options as query parameters.

```bash
curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896?format=csv&bundle=true" | jq .content_version
```

```
"cv_5b7870b8161a6995a2b87d1bde5427ab"
```

The call fetches the definition and runs it against the live graph. The same `content_version` means the rows are unchanged. A different `content_version` means the rows, selected facets, graph or source revisions, or conversion inputs have changed since the bundle was made. The `Authorization` header uses a `$DFO_API_KEY` placeholder. The dev API accepts calls without it.

## Collections

A bundle for a collection of specs holds one resource per member. Each member's file sits under `data/{spec_id}/`, for example `data/spec_19e75bf0f03c57ec5445816962ae3896/data.csv`. The `dfo.members` field lists the member ids, and the citation title reads "Development Finance Observatory dataset collection (N members)".

## Next

- [Use DFO data in your code](../build/use-data-in-code.md) takes a downloaded file into pandas or R and keeps the citation with it.
- [Versions and snapshots](versions.md) explains the `spec_id` and `content_version` in the file name.
