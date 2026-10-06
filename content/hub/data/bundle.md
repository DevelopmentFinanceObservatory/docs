---
description: The files in a DFO dataset download, what each one holds, and how to get the same dataset again.
---

# The data bundle

The examples come from one download of ODA standard grants for basic health care from France to Togo, `spec_19e75bf0f03c57ec5445816962ae3896` at `cv_5b7870b8161a6995a2b87d1bde5427ab`.

A bundle is a zip file that holds the data file and the documents a reader needs to understand, cite, and fetch it again. It follows the [Frictionless Data Package v2](https://datapackage.org/) standard, which describes a dataset's files, fields, and sources in `datapackage.json`. Downloads are bundled by default. On `/data`, the "README" and "Sources & Citations" checkboxes in the download menu switch the bundle on and off together. On the Datasets API, the switch is the `bundle` option. Neither needs an API key.

```
dfo_oecd-creditor-reporting-system_<YYYY-MM-DD>_csv_5b7870.zip
├── README.md
├── data/oecd-creditor-reporting-system.csv
├── data/codes.csv
├── SOURCES.md
├── CITATION.cff
└── datapackage.json
```

```bash
DFO_API=https://dfo-dev-apis-zms5lj4zhq-nn.a.run.app
curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896/cv_5b7870b8161a6995a2b87d1bde5427ab" |
  jq -r 'first(.artifacts[] | select(.rendering.bundle == true and .rendering.format == "csv")) | .url' |
  xargs curl -s -OJ
unzip -l dfo_*_csv_5b7870.zip
```

The command matches the bundle by the `bundle` and `format` fields of its `rendering`. Each bundle's `rendering` also carries a `rendition` token that changes when the bundle's layout changes, so an equality test on the whole object stops matching. [Versions and snapshots](versions.md) explains the two ids.

## File names

Every download has a name that says what it holds.

| File                   | Name                                                             |
| ---------------------- | ---------------------------------------------------------------- |
| Bundle                 | `dfo_<sources>_<YYYY-MM-DD>_<format>_<version>.zip`              |
| Table without a bundle | `dfo_<sources>_<YYYY-MM-DD>_<version>.<ext>`                     |
| Per-series summary     | `dfo_<sources>_<YYYY-MM-DD>_series-statistics_<version>.parquet` |
| Studio card export     | `dfo_<card-title>_<YYYY-MM-DD>_<format>_r<revision>.zip`         |

`<sources>` is the slug of the source names: `oecd-creditor-reporting-system` for one source, `<a>-and-<b>` for two, and `<a>-and-<n>-more` for more. `<YYYY-MM-DD>` is the UTC date the DFO first prepared that version, and it stays fixed when the files are built again. `<version>` is the first six characters of the `content_version` after `cv_`. A Studio card export names the card by its title and its revision number instead.

## `README.md`

Start here. It says what the data is, describes each file and column, gives the licence and how to cite the data, and says how to get it again.

## `data/<slug>.<ext>`

Each row is one observation. The file is `.csv`, `.xlsx` or `.parquet`, depending on the `format` option, and `<slug>` comes from the source names. The README describes every column of the file it ships with.

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

## `data/codes.csv`

The plain name of every code in the table, such as `country/DEU` for Germany. `datapackage.json` links each code column to this file with a foreign key. The file is absent when the table holds no codes.

## `SOURCES.md`

For each source: its publisher, licence, attribution text, update cadence, and each step the DFO applied to the data.

## `datapackage.json`

The descriptor follows the Data Package v2 profile. It holds one resource per data file, the sources and licences, and a `dfo` property with the spec and the call that reproduces the bundle.

| Property                  | Holds                                                                                                                                                     |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$schema`                 | The Data Package v2 profile URL.                                                                                                                          |
| `resources[]`             | One entry per data file: `name`, `path`, `mediatype`, `bytes`, `hash` (the file's SHA-256), an inline Table Schema, and its own `sources` and `licenses`. |
| `resources[].profile`     | `tabular-data-resource`, kept beside `type` so Data Package v1 readers, such as the R `frictionless` package, can open the bundle.                        |
| `schema.foreignKeys`      | The links from code columns to `data/codes.csv`.                                                                                                          |
| `licenses[]`, `sources[]` | The distinct licences and sources across all resources.                                                                                                   |
| `contributors[]`          | The DFO as publisher.                                                                                                                                     |
| `dfo.spec`                | The canonical spec definition, verbatim.                                                                                                                  |
| `dfo.reproducing_call`    | The API call that rebuilds the dataset: `method`, `url` and `options`. See below.                                                                         |

## `CITATION.cff`

A [Citation File Format](https://citation-file-format.github.io/) (CFF) 1.2.0 file, a standard format for machine-readable citations. It is written as YAML. The DFO is the author of the extract. Each source publisher appears as a reference with its own licence, link, and attribution text. To cite the data in a report, use a snapshot link in the form [Cite and licence](../about/cite-and-licence.md) gives.

## Licences

`SOURCES.md` gives each source's licence, and `datapackage.json` records it on the resource and in the package-level `licenses`. A source's licence is also on its page on [Sources](/data/sources). The CRS, for example, is covered by the [OECD Terms and Conditions](https://www.oecd.org/en/about/terms-conditions.html).

## Get the data again

The README lists the ways to get the data again. None needs a key.

- On the website, the dataset page for this version. The README prints the link when the bundle is for a single dataset and the website serves it. The website keeps that version's rows as Parquet, so the link keeps working after the API's copy of the files is gone.
- The exact version, from the snapshot route `GET /api/datasets/{spec_id}/{content_version}`, which returns fresh download links. The DFO keeps files fetched through the API for 30 days from when they were made, and a download does not extend that.
- The latest data for the same definition, from `GET /api/datasets/{spec_id}`, with the bundle's options as query parameters.
- A rebuild, by sending the request body the README prints to `POST /api/datasets`.

`dfo.reproducing_call` in `datapackage.json` names the latest-data route and its options. Run it as a GET.

```bash
curl -s "$DFO_API/api/datasets/spec_19e75bf0f03c57ec5445816962ae3896?format=csv&bundle=true" | jq .content_version
```

```
"cv_5b7870b8161a6995a2b87d1bde5427ab"
```

The call fetches the definition and runs it against the live graph. The same `content_version` means the rows are unchanged. A different `content_version` means the rows, selected facets, graph or source revisions, or conversion inputs have changed since the bundle was made.

## Next

- [Use DFO data in your code](../build/use-data-in-code.md) takes a downloaded file into pandas or R and keeps the citation with it.
- [Versions and snapshots](versions.md) explains the `spec_id` and `content_version` behind the file name.
