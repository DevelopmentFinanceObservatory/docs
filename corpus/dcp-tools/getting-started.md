---
description: Install dcp-tools and build a complete climate finance import bundle from Python, then export it and check the config, MCF, and CSV files.
---

# Build your first Data Commons Platform import

> A working import bundle for a Data Commons Platform instance, built with `dcp-tools` and verified by loading it back.

## What you'll build

By the end, you'll have a complete import bundle on disk: a `config.json`, two MCF files, and a CSV of climate finance data, generated entirely from Python. This is the same shape of bundle a Data Commons Platform instance loads from Google Cloud Storage.

```
one_climate_finance/
├── config.json
├── custom_nodes.mcf
├── provenance.mcf
└── climate_finance/
    └── one_cf_provider_commitments.csv
```

## What you'll learn

- How to register a source and a provenance as MCF nodes
- How to register an input CSV file with column mappings
- How to declare a StatVar for a data file
- How to export a complete bundle with `export_all`
- How to verify an exported bundle by loading it back

## What you'll need

- Python 3.13 or later
- `pip install dcp-tools` (installs `pandas` and `pydantic` alongside it)
- No GCP account or credentials. This tutorial stops at a bundle on disk. [Loading data](./loading-data.md) covers uploading it.
- About 15-20 minutes

## Step 1: Install dcp-tools and create a manager

Install the package, then create a `CustomDataManager`. It's the object you'll register everything on (sources, variables, input files) before anything gets written to disk.

```bash
pip install dcp-tools
```

```python
from dcp_tools import CustomDataManager

manager = CustomDataManager()
print(manager)
```

You should see a manager with nothing registered yet:

```
<CustomDataManager config:
0 inputFiles, with 0 containing data
0 sources
0 provenances
0 variables
0 vertical specs
flags: importName=None, includeInputSubdirs=None, groupStatVarsByProperty=None, defaultCustomRootStatVarGroupName=None, customIdNamespace=None, customSvgPrefix=None, svHierarchyPropsBlocklist=None, dataDownloadUrl=None, verticalSpecsFile=None>
```

## Step 2: Register a source and a provenance

Register where the data comes from: a Source (the publishing organisation) and a Provenance (this specific dataset). Every input file you register later points back at a Provenance dcid, so it has to exist first.

```python
manager.add_source(dcid="ONEData", url="https://data.one.org")
manager.add_provenance(
    dcid="ONEClimateFinance",
    url="https://datacommons.one.org/data/climate-finance-files",
    source="ONEData",
)
```

> [!NOTE]
> `dcid` is the node's identifier, so it can't contain spaces. `add_source` mints `"ONEData"` into `dcid:source/ONEData`. For a human-readable label (spaces allowed), pass the optional `name`.

Both calls add MCF nodes in memory. Export them to see what they'll look like on disk:

```python
manager.export_mcf_file("one_climate_finance", mcf_file_name="provenance.mcf")
print(open("one_climate_finance/provenance.mcf").read())
```

This also creates the `one_climate_finance/` directory, since it doesn't exist yet. You should see:

```
Node: dcid:source/ONEData
typeOf: dcid:Source
url: "https://data.one.org"

Node: dcid:provenance/ONEClimateFinance
typeOf: dcid:Provenance
url: "https://datacommons.one.org/data/climate-finance-files"
source: dcid:source/ONEData
```

## Step 3: Register the input CSV file

Register a CSV of bilateral climate finance commitments, one row per observation. `columnMappings` tells `dcp-tools` which column holds which piece of an observation. The Kenya and Fiji figures below are illustrative, not published commitments.

```python
import pandas as pd

data = pd.DataFrame({
    "country": ["Kenya", "Kenya", "Fiji", "Fiji"],
    "year": [2022, 2023, 2022, 2023],
    "variable": ["climateFinanceProvidedCommitments"] * 4,
    "value": [12.4, 15.8, 3.1, 4.6],
})

manager.add_input_file(
    file_name="climate_finance/one_cf_provider_commitments.csv",
    provenance="ONEClimateFinance",
    data=data,
    column_mappings={
        "observationAbout": "country",
        "date": "year",
        "variable": "variable",
        "value": "value",
    },
)
```

`file_name` can include a subdirectory, like `climate_finance/one_cf_provider_commitments.csv` above, and `export_all` creates that subdirectory for you later. Check what landed in the config with `config_to_dict`:

```python
import json

print(json.dumps(manager.config_to_dict()["inputFiles"], indent=2))
```

You should see one entry, with `provenance` minted to a dcid and each mapping rewritten to its `dcid:` form:

```json
[
  {
    "filename": "climate_finance/one_cf_provider_commitments.csv",
    "provenance": "dcid:provenance/ONEClimateFinance",
    "columnMappings": {
      "dcid:variableMeasured": "variable",
      "dcid:observationDate": "year",
      "dcid:value": "value",
      "dcid:observationAbout": "country"
    },
    "format": "variablePerRow"
  }
]
```

## Step 4: Declare the StatVar

The `variable` column holds `climateFinanceProvidedCommitments`, a dcid that has to resolve to a real StatVar node, or the importer has nothing to attach the observations to. Declare it with `add_variable_to_mcf`.

```python
manager.add_variable_to_mcf(
    dcid="climateFinanceProvidedCommitments",
    name="Climate finance provided (commitments)",
    description="Bilateral climate finance commitments reported by the provider country.",
    provenance="ONEClimateFinance",
    population_type="Thing",
    measured_property="amount",
)
```

`dcid` is a bare token here, so `dcp-tools` normalises it to `dcid:climateFinanceProvidedCommitments` for you. It must match the `variable` column values exactly. Export the checkpoint and take a look:

```python
manager.export_mcf_file("one_climate_finance", mcf_file_name="custom_nodes.mcf")
print(open("one_climate_finance/custom_nodes.mcf").read())
```

```
Node: dcid:climateFinanceProvidedCommitments
name: "Climate finance provided (commitments)"
typeOf: dcid:StatisticalVariable
description: "Bilateral climate finance commitments reported by the provider country."
provenance: "ONEClimateFinance"
statType: dcid:measuredValue
populationType: dcid:Thing
measuredProperty: dcid:amount
```

The `provenance` field here is the bare name you passed in, stored as a plain quoted string on the node, not the minted dcid you saw on the input file entry in Step 3.

## Step 5: Declare the MCF files

The importer only reads files listed in `config.json`'s `inputFiles`, so the MCF files written next to the config need an entry too, naming the provenance their nodes belong to. One glob covers both files in this import:

```python
manager.add_mcf_file("*.mcf", provenance="ONEClimateFinance")
```

## Step 6: Export the bundle and verify it

`export_all` empties the target directory, then writes the config, the data, and any MCF files
you've registered.

```python
manager.export_all("one_climate_finance")
```

List the directory to confirm the full bundle landed:

```python
import os

for root, _, files in os.walk("one_climate_finance"):
    for f in sorted(files):
        print(os.path.relpath(os.path.join(root, f)))
```

```
one_climate_finance/config.json
one_climate_finance/custom_nodes.mcf
one_climate_finance/provenance.mcf
one_climate_finance/climate_finance/one_cf_provider_commitments.csv
```

`config.json` now has an `importName`, defaulted from the export directory name since we never called `set_import_name`:

```json
{
    "importName": "one_climate_finance",
    "inputFiles": [
        {
            "filename": "climate_finance/one_cf_provider_commitments.csv",
            "provenance": "dcid:provenance/ONEClimateFinance",
            "columnMappings": {
                "dcid:variableMeasured": "variable",
                "dcid:observationDate": "year",
                "dcid:value": "value",
                "dcid:observationAbout": "country"
            },
            "format": "variablePerRow"
        },
        {
            "pattern": "*.mcf",
            "provenance": "dcid:provenance/ONEClimateFinance"
        }
    ]
}
```

Now confirm the bundle is self-consistent by loading it into a fresh manager:

```python
reloaded = CustomDataManager(
    config_file="one_climate_finance/config.json",
    mcf_files=[
        "one_climate_finance/provenance.mcf",
        "one_climate_finance/custom_nodes.mcf",
    ],
)
print(reloaded)
```

```
<CustomDataManager config:
2 inputFiles, with 0 containing data
1 sources
1 provenances
1 variables
0 vertical specs
flags: importName=one_climate_finance, includeInputSubdirs=None, groupStatVarsByProperty=None, defaultCustomRootStatVarGroupName=None, customIdNamespace=None, customSvgPrefix=None, svHierarchyPropsBlocklist=None, dataDownloadUrl=None, verticalSpecsFile=None>
```

2 input files (the CSV and the `*.mcf` declaration), 1 source, 1 provenance, 1 variable. `with 0 containing data` is expected. Reloading from `config_file`/`mcf_files` restores the config and MCF nodes, not the CSV data. That data lives in the CSV file on disk, never in `config.json`.

## What you learned

- You registered a source and a provenance as MCF nodes
- You registered an input CSV file with column mappings
- You declared a StatVar for a data file
- You declared the MCF files so the importer reads them
- You exported a complete bundle with `export_all`
- You verified an exported bundle by loading it back

## What's next

- **[Preparing data](./preparing-data.md)**. The full `CustomDataManager` catalogue: schema-node builders, multi-entity dimensions, vertical specs, config merging.
- **[Why config.json and MCF](./dc-schemas.md)**. The reasoning behind the `config.json`/MCF split and the column-mapping shapes.
- **[Loading data](./loading-data.md)**. Upload `one_climate_finance/` to Google Cloud Storage and trigger the ingestion workflow.
