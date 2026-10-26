---
description: Use the dcp-tools CLI reference to convert CSV files to MCF, upload bundles, trigger ingestion, and check command options.
---

# `dcp-tools` CLI

`dcp-tools` is the command-line entry point for the functions documented under
[Preparing data](preparing-data.md) and [Loading data](loading-data.md). It converts a CSV into
MCF, uploads a prepared export directory to Google Cloud Storage, and triggers the Data Commons Platform (DCP) ingestion
workflow. Each subcommand parses its arguments and calls straight into the Python API. It adds no
behaviour of its own.

There are four subcommands and no subcommand groups: `csv2mcf`, `upload`, `ingest`, and
`pipeline`. Run any of them as `dcp-tools <command> ...` or `python -m dcp_tools <command> ...`.
Every command, including `dcp-tools` itself, accepts `-h`/`--help` for its full option list.

## Global options

`upload`, `ingest`, and `pipeline` connect to Google Cloud through a `KGSettings` object (see
[Loading data](loading-data.md)). Two flags control where those settings come from:

- **`--settings-file PATH`**: a JSON file using the settings' alias keys, all uppercase
  (`LOCAL_PATH`, `GCP_PROJECT_ID`, `GCS_BUCKET_NAME`, and so on).
- **`--env-file PATH`**: a `.env` file using the same keys. Other variables in the file are
  ignored.

If both are given, `--settings-file` wins and `--env-file` is ignored. If neither is given,
settings are read from a `.env` file in the current directory.

`csv2mcf` takes neither flag. It doesn't talk to Google Cloud, so it has no settings to load.

```json title="customDC.json"
{
  "LOCAL_PATH": "./export",
  "GCP_PROJECT_ID": "one-climate-finance",
  "GCP_REGION": "us-central1",
  "GCS_BUCKET_NAME": "one-dcp-import",
  "GCS_INPUT_FOLDER_PATH": "climate-finance",
  "GCS_OUTPUT_FOLDER_PATH": "climate-finance/output",
  "INGESTION_WORKFLOW_NAME": "dcp-ingestion-workflow"
}
```

```bash title="customDC.env"
LOCAL_PATH=./export
GCP_PROJECT_ID=one-climate-finance
GCP_REGION=us-central1
GCS_BUCKET_NAME=one-dcp-import
GCS_INPUT_FOLDER_PATH=climate-finance
GCS_OUTPUT_FOLDER_PATH=climate-finance/output
INGESTION_WORKFLOW_NAME=dcp-ingestion-workflow
```

> [!NOTE]
> `GCP_CREDENTIALS` and `INGESTION_SERVICE_ACCOUNT` are optional and omitted above. Without
> `GCP_CREDENTIALS`, GCP calls fall back to Application Default Credentials
> (`gcloud auth application-default login`). `LOCAL_PATH`, `GCS_INPUT_FOLDER_PATH` and
> `GCS_OUTPUT_FOLDER_PATH` are optional too.

## Exit status

All four subcommands return `0` on success. Argument errors, such as a missing required argument
or an invalid `--node-type` choice, print a usage message to stderr and exit non-zero before any
subcommand code runs. Errors raised by the underlying Python API (a pydantic validation error from
a malformed CSV, a Google Cloud auth failure) propagate as an uncaught exception and also exit
non-zero. The CLI does not catch or reformat them.

## `dcp-tools csv2mcf`

Converts a CSV of node metadata into an `.mcf` file, wrapping `csv_metadata_to_mcf_file`.

```
dcp-tools csv2mcf <CSV> <MCF>
                  [--node-type {Node,StatVar,StatVarGroup,Topic,StatVarPeerGroup}]
                  [--column-mapping CSV_COL=MCF_PROP]
                  [--csv-option KEY=VALUE]
                  [--ignore-column COLUMN]
                  [--append]
```

**Arguments**

- **`<CSV>`**: path to the input CSV file. Required.
- **`<MCF>`**: path to write the generated MCF file. Required, must end in `.mcf`.

**Options**

- **`--node-type {Node,StatVar,StatVarGroup,Topic,StatVarPeerGroup}`** (default: `Node`): the MCF
  node type to build, one per CSV row. `StatVar`, `StatVarGroup`, `Topic`, and `StatVarPeerGroup`
  map to the typed node models under `dcp_tools.custom_data.models`. `Node` builds the untyped base
  model and accepts any column as an extra property.
- **`--column-mapping CSV_COL=MCF_PROP`** (repeatable): rename a CSV column to an MCF property
  before building nodes, e.g. `--column-mapping identifier=Node`. Pass the flag once per column.
- **`--csv-option KEY=VALUE`** (repeatable): an extra keyword argument forwarded to
  `pandas.read_csv`, e.g. `--csv-option delimiter=";"`.
- **`--ignore-column COLUMN`** (repeatable): drop a CSV column before building nodes. Pass the
  flag once per column.
- **`--append`**: append to `<MCF>` if it already exists instead of overwriting it. Without this
  flag, `csv2mcf` overwrites the file (or creates it if it doesn't exist).

CSV values that map to a `dcid:`-typed field (`Node`, `populationType`, `measuredProperty`,
`measurementQualifier`, `measurementDenominator`) must already carry the `dcid:` prefix. `csv2mcf`
builds the node objects directly from the CSV, and unlike `CustomDataManager`'s `add_*` methods it
does not mint the prefix for you. A bare value such as `climateFinanceProvidedCommitments` in the
`Node` column fails with a pydantic `string_pattern_mismatch` error.

`typeOf` isn't in that list: for `--node-type Node` it's a required column, but a bare value there
is minted to `dcid:<value>` automatically; for the other four node types it defaults to a fixed
value (`dcid:StatisticalVariable`, `dcid:StatVarGroup`, `dcid:Topic`, `dcid:StatVarPeerGroup`) that
a CSV `typeOf` column doesn't need to repeat.

**Example**

```csv title="variables.csv"
Node,name,populationType,measuredProperty,statType,description
dcid:climateFinanceProvidedCommitments,Climate finance provided (commitments),dcid:Thing,dcid:amount,dcid:measuredValue,"Bilateral climate finance commitments reported by the provider country, in current USD."
```

```
$ dcp-tools csv2mcf variables.csv custom_nodes.mcf --node-type StatVar
$ cat custom_nodes.mcf
Node: dcid:climateFinanceProvidedCommitments
name: "Climate finance provided (commitments)"
typeOf: dcid:StatisticalVariable
description: "Bilateral climate finance commitments reported by the provider country, in current USD."
statType: dcid:measuredValue
populationType: dcid:Thing
measuredProperty: dcid:amount
```

`--column-mapping`, `--csv-option`, and `--ignore-column` combine to read a differently-shaped
source file:

```
$ dcp-tools csv2mcf variables_raw.csv custom_nodes.mcf \
    --node-type StatVar \
    --column-mapping node_id=Node \
    --column-mapping label=name \
    --column-mapping pop_type=populationType \
    --column-mapping measured_prop=measuredProperty \
    --csv-option delimiter=";" \
    --ignore-column source_note
```

That reads a semicolon-delimited `variables_raw.csv`, drops its `source_note` column, and renames
the rest to the properties named on the right of each `=`.

## `dcp-tools upload`

Uploads every `.csv`, `.json`, and `.mcf` file under a directory to the configured GCS bucket,
wrapping `upload_to_cloud_storage`.

```
dcp-tools upload [--settings-file PATH] [--env-file PATH] [--directory PATH] [--sync]
```

**Options**

- **`--settings-file PATH`**, **`--env-file PATH`**: see [Global options](#global-options).
- **`--directory PATH`** (default: the directory configured as `LOCAL_PATH` in settings): local
  directory to upload. Required when `LOCAL_PATH` is unset. Files are matched recursively.
  Anything under it that isn't `.csv`, `.json`, or `.mcf` is skipped with a warning. The local
  directory structure is preserved under the bucket's input folder. A file whose MD5 matches the
  blob already at its remote path is skipped and logged as unchanged.
- **`--sync`** (default: off): after uploading, delete remote blobs that no longer have a local
  counterpart. Deletion is scoped to import subdirectories that have local files present. An
  import missing from `--directory` entirely, or present but empty, is left untouched remotely. When `--directory` holds `.csv`, `.json`, or `.mcf` files at its top level, stale blobs directly under the input folder are deleted too.

**Example**

```
$ dcp-tools upload --settings-file customDC.json --directory export/
2026-07-21 09:14:02 | INFO     | dcp-tools | Uploaded export/config.json to climate-finance/config.json
2026-07-21 09:14:02 | INFO     | dcp-tools | Uploaded export/provenance.mcf to climate-finance/provenance.mcf
2026-07-21 09:14:03 | INFO     | dcp-tools | Uploaded export/custom_nodes.mcf to climate-finance/custom_nodes.mcf
2026-07-21 09:14:03 | INFO     | dcp-tools | Uploaded 3 files to climate-finance in GCS bucket one-dcp-import, skipped 0 unchanged
```

## `dcp-tools ingest`

Triggers the DCP ingestion workflow that loads uploaded files into the knowledge graph, wrapping
`run_ingestion_workflow`.
`ingest` and `pipeline` need a DCP 1.1.6 instance.

```
dcp-tools ingest [--settings-file PATH] [--env-file PATH] [--imports a,b,c]
                 [--skip-workflow-contract-check]
```

**Options**

- **`--settings-file PATH`**, **`--env-file PATH`**: see [Global options](#global-options).
- **`--imports a,b,c`** (default: every import): comma-separated import names to scope the run
  to. Omit it to ingest everything under the configured GCS input folder.
- **`--skip-workflow-contract-check`**: start the workflow without first reading its definition
  to confirm it comes from a DCP 1.1.6 stack. Use it only when the identity starting the
  ingestion can't be granted `roles/workflows.viewer` and you know the stack runs 1.1.6. See
  [Loading data](loading-data.md).

**Example**

```
$ dcp-tools ingest --settings-file customDC.json --imports climate-finance
2026-07-21 09:15:10 | INFO     | dcp-tools | Starting data ingestion workflow 'dcp-ingestion-workflow'
2026-07-21 09:15:11 | INFO     | dcp-tools | Started workflow execution 'projects/one-climate-finance/locations/us-central1/workflows/dcp-ingestion-workflow/executions/a1b2c3'
```

> [!NOTE]
> `ingest` only triggers the ingestion workflow. It doesn't upload anything first, so the files
> it loads must already be in Cloud Storage (run `upload` beforehand, or use `pipeline`). Once
> the workflow finishes, the platform serves the new data on its own. There's no separate
> redeploy or restart command to run.

## `dcp-tools pipeline`

Runs `upload` followed by `ingest` for every import in one call, wrapping
`upload_to_cloud_storage` then `run_ingestion_workflow`.

```
dcp-tools pipeline [--settings-file PATH] [--env-file PATH] [--directory PATH] [--sync]
                   [--skip-workflow-contract-check]
```

**Options**

- **`--settings-file PATH`**, **`--env-file PATH`**, **`--directory PATH`**, **`--sync`**: same
  flags and defaults as [`upload`](#dcp-tools-upload).
- **`--skip-workflow-contract-check`**: same as for [`ingest`](#dcp-tools-ingest). Without it,
  `pipeline` checks the workflow before uploading, so it uploads nothing to an older stack.

> [!WARNING]
> `pipeline` has no `--imports` flag. It always calls `ingest` with no import filter, loading
> everything. To load a subset of imports, run `upload` and `ingest --imports=...` as two
> separate commands instead.

**Example**

```
$ dcp-tools pipeline --settings-file customDC.json --directory export/
2026-07-21 09:16:40 | INFO     | dcp-tools | Uploaded export/config.json to climate-finance/config.json
2026-07-21 09:16:40 | INFO     | dcp-tools | Uploaded export/provenance.mcf to climate-finance/provenance.mcf
2026-07-21 09:16:41 | INFO     | dcp-tools | Uploaded export/custom_nodes.mcf to climate-finance/custom_nodes.mcf
2026-07-21 09:16:41 | INFO     | dcp-tools | Uploaded 3 files to climate-finance in GCS bucket one-dcp-import
2026-07-21 09:16:41 | INFO     | dcp-tools | Starting data ingestion workflow 'dcp-ingestion-workflow'
2026-07-21 09:16:42 | INFO     | dcp-tools | Started workflow execution 'projects/one-climate-finance/locations/us-central1/workflows/dcp-ingestion-workflow/executions/a1b2c3'
```

## Related

- **[Preparing data](preparing-data.md)**: build the `config.json`, CSVs, and `.mcf` files that
  `csv2mcf`, `upload`, and `pipeline` operate on.
- **[Loading data](loading-data.md)**: the `KGSettings` model and the Python functions these
  commands wrap.
