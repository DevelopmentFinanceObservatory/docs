---
description: Use CustomDataManager recipes to register data, define StatVars and schema nodes, merge configs, validate bundles, and export files.
---

# Preparing data

`CustomDataManager` builds a Data Commons Platform import bundle (a `config.json` file, CSV data,
and `.mcf` files) without hand-editing any of the three. Each section below is a recipe.
Later recipes reuse the `manager`, source, and provenance from [How to register a source and provenance](#how-to-register-a-source-and-provenance), so run that section first.

> [!NOTE]
> Assumes `dcp-tools` is installed. See [Getting started](getting-started.md) if it isn't.

## How to create a `CustomDataManager`

```python
from dcp_tools import CustomDataManager

manager = CustomDataManager()
```

This creates a blank config (an empty `inputFiles` list) and one empty MCF collection named
`custom_nodes.mcf`. Every `add_*`/`set_*` method below returns the manager, so calls chain.

To load files you already have:

```python
manager = CustomDataManager(
    config_file="path/to/config.json",
    mcf_files=["path/to/provenance.mcf", "path/to/custom_nodes.mcf"],
)
```

`mcf_files` takes one path or a list. Each file is loaded and keyed internally by its filename.
To merge several `config.json` files from a directory tree into one manager, see
[How to merge config files](#how-to-merge-config-files).

## How to register a source and provenance

Every input file must reference a provenance, and every provenance must reference a source. Add
the source first:

```python
from dcp_tools import CustomDataManager

manager = CustomDataManager()

manager.add_source(
    dcid="ONEData",
    url="https://data.one.org",
)
manager.add_provenance(
    dcid="ONEClimateFinance",
    url="https://datacommons.one.org/data/climate-finance-files",
    source="ONEData",
)
```

This writes two nodes to `provenance.mcf` (the default file for both methods): a `dcid:Source`
node at `dcid:source/ONEData`, and a `dcid:Provenance` node at `dcid:provenance/ONEClimateFinance`
linking to it. If `source` isn't registered in the bundle, `add_provenance` logs a warning and
writes the node anyway. A `Provenance` may point at a `Source` that already exists in base Data
Commons, in which case it's on you to confirm that it does.

> [!NOTE]
> `dcid` is the node's identifier and gets minted. A bare token becomes `dcid:source/<token>`
> or `dcid:provenance/<token>` (an already `dcid:`-prefixed value is used as-is), so it can't
> contain whitespace. `name` is the optional human-readable label, where spaces are fine. See
> [Why config.json and MCF](dc-schemas.md) for why the importer needs dcids shaped this way.

Both methods take `description`, `license`, `license_type`, `license_attribution`, and
`is_part_of`. `add_provenance` additionally takes `source_data_url`, `last_data_refresh_date`,
`next_data_refresh_date`, `imported_source_release_date`, `next_source_release_date`,
`source_release_frequency`, `earliest_observation_date`, `latest_observation_date`, and
`curator`. `source_data_url` takes one URL or a list of them, for a source published as several
files. `license_type` and `curator` are DCID references. A bare token becomes `dcid:<token>`. Use
`additional_properties={"someProperty": "value"}` for anything else. Pass `override=True` to
replace a node that's already registered under the same name.

## How to register a single-entity input file

Use this when each row of data is about one entity (a country, a facility, a person).

```python
import pandas as pd

df = pd.DataFrame({
    "country": ["country/KEN", "country/BGD", "country/KEN"],
    "year": [2022, 2022, 2023],
    "variable": ["climateFinanceProvidedCommitments"] * 3,
    "value": [4.2, 1.8, 5.1],
})

manager.add_input_file(
    file_name="climate_finance_commitments.csv",
    provenance="ONEClimateFinance",
    data=df,
    column_mappings={
        "observationAbout": "country",
        "date": "year",
        "variable": "variable",
        "value": "value",
    },
    observation_properties={"unit": "USDollar"},
)
```

`columnMappings` keys map a role to a CSV column name. Allowed keys: `variable`,
`observationAbout`, `date`, `value`, `unit`, `scalingFactor`, `measurementMethod`,
`observationPeriod`, plus `custom:<name>` for multi-entity data (see the next section). The
spec's `variableMeasured` and `observationDate`, and the `dcid:`-prefixed forms, work too.
`config.json` is written with `dcid:` keys. `observationAbout` is the entity column for
single-entity data. It holds a dcid per row (here, country dcids like `country/KEN`).

`observationProperties` here differs from `add_variable_to_mcf`'s parameter of the same
name. On `add_input_file` it's a dict of file-level constants applied to every row (every
observation in this file is in US dollars), not a list of dcid refs. Its standard keys,
`unit`, `scalingFactor`, `measurementMethod` and `observationPeriod`, also accept snake_case
and are written in camelCase. Other keys are written as given.

Data is optional at registration:

```python
manager.add_input_file(
    file_name="climate_finance_disbursements.csv",
    provenance="ONEClimateFinance",
    column_mappings={
        "observationAbout": "country",
        "date": "year",
        "variable": "variable",
        "value": "value",
    },
)
# ...later, once the DataFrame is ready:
manager.add_data(df, "climate_finance_disbursements.csv")
```

`add_data` raises `ValueError` if `file_name` isn't already registered via `add_input_file`. To
register many files by glob pattern instead of one at a time, pass `pattern=` instead of
`file_name=`. Pattern entries are config-only and can't carry a `data=` DataFrame.

## How to register multi-entity observations with custom dimensions

Use this when a row of data is about more than one entity, such as a bilateral flow between a
provider and a recipient country, rather than a value about a single country.

```python
import pandas as pd

flows = pd.DataFrame({
    "provider": ["country/KEN", "country/KEN", "country/BGD"],
    "recipient": ["country/BGD", "country/UGA", "country/UGA"],
    "year": [2022, 2022, 2022],
    "variable": ["climateFinanceBilateralFlow"] * 3,
    "value": [1.4, 0.9, 0.6],
})

manager.add_input_file(
    file_name="bilateral_climate_finance_flows.csv",
    provenance="ONEClimateFinance",
    data=flows,
    column_mappings={
        "variable": "variable",
        "date": "year",
        "value": "value",
        "custom:providerCountry": "provider",
        "custom:recipientCountry": "recipient",
    },
)

manager.add_variable_to_mcf(
    dcid="climateFinanceBilateralFlow",
    name="Climate finance bilateral flow",
    description="Bilateral climate finance commitments between a provider and a recipient country.",
    stat_type="dcid:measuredValue",
    observation_properties=["dcid:providerCountry", "dcid:recipientCountry"],
)
```

There's no `observationAbout` here. Multi-entity rows use one `custom:<name>` mapping key per
dimension instead (`ColumnMappings` collects any `custom:`-prefixed key automatically, so you
don't build the `customDimensions` dict by hand). Each `custom:<name>` key must have a matching
`dcid:<name>` entry in the StatVar's `observationProperties` list. `custom:providerCountry` pairs
with `dcid:providerCountry`.

> [!NOTE]
> `providerCountry` and `recipientCountry` are properties, not entities. If they aren't already
> part of the base Data Commons schema, declare them with `add_property` first (see the next
> section).

See [Why config.json and MCF](dc-schemas.md#why-bilateral-data-needs-a-different-mechanism-from-observationabout)
for why `observationAbout` can't represent a row about two entities.

## How to declare StatVars and custom schema nodes

`CustomDataManager` has six builders for schema concepts. Use `add_variable_to_mcf` for the StatVars
themselves. Use the other five when your data needs a schema concept Data Commons doesn't already
define.

| Method                   | Emits                                                | Use when                                                                                                                 |
| ------------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `add_variable_to_mcf`    | `dcid:StatisticalVariable`                           | Declaring a StatVar (see above)                                                                                          |
| `add_entity_type`        | `dcid:Class`                                         | Your data describes something Data Commons doesn't have a `Class` for yet, such as a program type or a facility category |
| `add_event_type`         | `dcid:Class` (`subClassOf` defaults to `dcid:Event`) | Your data is about events (a pledge announcement, a policy change) rather than a state                                   |
| `add_property`           | `dcid:Property`                                      | You need a new predicate, such as a custom dimension from the previous section                                           |
| `add_unit`               | `dcid:UnitOfMeasure`                                 | Your values are in a unit Data Commons doesn't already define                                                            |
| `add_measurement_method` | `dcid:MeasurementMethodEnum`                         | You want to record how an observation was produced (survey, estimate, administrative data)                               |

All six accept a bare or `dcid:`-prefixed `Node` token. Bare tokens are normalised to
`dcid:<token>` (no namespace segment, unlike source/provenance names). `add_measurement_method` is
the only one where `name` is optional.

Declaring the StatVar the single-entity input file from earlier references:

```python
manager.add_variable_to_mcf(
    dcid="climateFinanceProvidedCommitments",
    name="Climate finance committed",
    description="Bilateral climate finance commitments provided by a country.",
    stat_type="dcid:measuredValue",
    population_type="Country",
    measured_property="amount",
)
```

This emits a `dcid:StatisticalVariable` node to `custom_nodes.mcf` (the default file for this
builder). `populationType` and `measuredProperty` go through the same bare-or-`dcid:` normalisation
as `Node`.

Declaring the two properties the multi-entity StatVar from the previous section depends on:

```python
manager.add_property(
    dcid="providerCountry",
    name="provider country",
    description="The country providing climate finance in a bilateral flow.",
    domain_includes="StatisticalVariable",
    range_includes="Country",
)
manager.add_property(
    dcid="recipientCountry",
    name="recipient country",
    description="The country receiving climate finance in a bilateral flow.",
    domain_includes="StatisticalVariable",
    range_includes="Country",
)
```

This mints `dcid:providerCountry` and `dcid:recipientCountry`. These are the same tokens the
StatVar's `observationProperties` and the input file's `custom:` columnMappings keys referenced.

`add_entity_type` and `add_event_type` take an `included_in` argument that is a bare **provenance**
name, not a dcid, unlike every other ref parameter on these builders:

```python
manager.add_entity_type(
    dcid="ClimateFinanceProgram",
    name="Climate finance program",
    description="A named climate finance program or initiative tracked by ONE.",
    included_in="ONEClimateFinance",
)
```

The provenance must already be registered via `add_provenance`, or this raises `ValueError`. The
builder expands one bare name into `includedIn` dcids for **both** the Provenance node and its
linked Source node.

## How to add StatVar groups and bulk-import variables from a CSV

Add a top-level StatVarGroup for all of an organisation's custom variables:

```python
manager.add_variable_group_to_mcf(
    dcid="dcid:one/g/ONEData",
    name="ONE Data",
    specialization_of="dcid:dc/g/Root",
)
```

`Node` must contain `g/`. `specializationOf` is `"dcid:dc/g/Root"` for a top-level group, or
another group's dcid for a sub-group. Unlike the schema-node builders above,
`add_variable_group_to_mcf` doesn't normalise a bare `Node`. Pass it already `dcid:`-prefixed.

To declare many StatVars at once instead of calling `add_variable_to_mcf` per variable, put them
in a CSV with one row per StatVar and columns matching `StatVarNode` field names:

```csv
Node,name,statType,memberOf
dcid:climateFinanceProvidedGrants,Climate finance committed as grants,dcid:measuredValue,Economic/ClimateFinance/BilateralCommitments
dcid:climateFinanceProvidedLoans,Climate finance committed as loans,dcid:measuredValue,Economic/ClimateFinance/BilateralCommitments
```

```python
manager.add_variables_to_mcf_from_csv(
    "climate_finance_variables.csv",
    parse_groups=True,
    group_namespace="one",
)
```

`parse_groups=True` treats `memberOf` as a slash-separated group path
(`"Economic/ClimateFinance/BilateralCommitments"`) instead of a dcid, and expands it into a chain
of `StatVarGroupNode`s under `group_namespace` (here, `dcid:one/g/economic`, then
`.../climatefinance`, then `.../bilateralcommitments`). Each StatVar's `memberOf` is rewritten to
the deepest group's dcid. Rename CSV columns to node field names with
`column_to_property_mapping` if your headers don't already match.

> [!NOTE]
> The groups `parse_groups` generates land in the same `mcf_file_name` as the StatVars
> (`custom_nodes.mcf` by default), not in `add_variable_group_to_mcf`'s default of
> `custom_groups.mcf`. If you export both files, this doesn't matter. If you only export one,
> it does.

The `dcp-tools csv2mcf` CLI command wraps the same conversion for a CSV that isn't going through a
`CustomDataManager` at all. See [CLI tools](cli-tools.md) for the command reference.

## How to rename and remove variables

```python
manager.rename_variable("dcid:climateFinanceProvidedCommitments", "dcid:climateFinanceCommitmentsProvided")
```

Pass the full node id on both sides, matching what's stored (the value after minting, not the bare
name you might have originally passed to `add_variable_to_mcf`). Raises `ValueError` if the old
name isn't found or the new name is already taken. Scope the search to one file with
`mcf_file_name=`. Omit it and all loaded MCF files are searched.

```python
manager.remove_variable("dcid:climateFinanceCommitmentsProvided")
```

## How to merge config files

Use this when different teams maintain separate `config.json` files for the same custom Data
Commons instance and you need one combined bundle.

```python
from dcp_tools import CustomDataManager

merged = CustomDataManager.from_config_files_in_directory("path/to/configs")
```

This recursively finds every `config.json` under the directory and merges them into one manager,
replacing whatever config the manager already had. To merge into an existing manager instead of
starting fresh, call `merge_configs_from_directory` directly:

```python
manager.merge_configs_from_directory("path/to/configs", replace_loaded_config=False)
```

To merge a single config (an object, a dict, or a path to a JSON file) rather than a whole
directory:

```python
manager.merge_config("path/to/other/config.json")
```

All three take `policy`, one of `"error"` (default, raises on any conflicting value),
`"override"` (the new config wins), or `"ignore"` (the existing value is kept). Input files are
merged by `filename`/`pattern`. Everything else (`importName`, `customIdNamespace`,
`svHierarchyPropsBlocklist`, and so on) is merged field by field.

> [!WARNING]
> `export_config` defaults an unset `importName` to the export directory's name. If two configs
> were each exported without an explicit `importName`, merging them raises a conflict on
> `importName` (`"climate"` vs. `"health"`) even though neither config set it on purpose. Call
> `set_import_name` explicitly on configs you intend to merge later.

## How to add vertical specs to guide the StatVar hierarchy

Vertical specs tell the importer which top-level groups to file matching StatVars under when
`groupStatVarsByProperty` is set. Skip this unless you're using that setting.

```python
manager.set_group_stat_vars_by_property(True)
manager.add_vertical_spec(
    verticals=["ClimateFinanceVertical"],
    population_type="Country",
    measured_properties=["amount"],
)
```

Each call appends one spec, for StatVars with the given `population_type` and
`measured_properties`, to the accumulated vertical specs. The first call also sets the config's `verticalSpecsFile` to
`"vertical_specs.json"`, unless you already set one with `set_vertical_specs_file` or passed
`file_name=` here. `export_all` (or `export_vertical_specs` directly) writes the accumulated specs
as `{"specs": [...]}` JSON. `export_vertical_specs` raises `ValueError` when no specs have been added. `export_all` writes no vertical-specs file in that case.

## How to declare MCF files for the importer

The importer only reads files listed in `config.json`'s `inputFiles`, so every MCF file in the
bundle needs an entry naming the provenance its nodes belong to. With a single provenance, one
glob covers every MCF file:

```python
manager.add_mcf_file("*.mcf", provenance="MyProvenance")
```

The entry carries no `columnMappings` and no `format`. There are no columns to map.

With more than one provenance, a single glob would attribute every node to the same one. Write
nodes to per-provenance files with `mcf_file_name`, then declare each file against its own
provenance:

```python
manager.add_provenance(
    dcid="ProvB", url="https://source.org/b", source="MySource",
    mcf_file_name="provenance_b.mcf",
)
manager.add_variable_to_mcf(dcid="dcid:VarB", name="Var B", mcf_file_name="nodes_b.mcf")

manager.add_mcf_file("provenance.mcf", provenance="ProvA")
manager.add_mcf_file("custom_nodes.mcf", provenance="ProvA")
manager.add_mcf_file("provenance_b.mcf", provenance="ProvB")
manager.add_mcf_file("nodes_b.mcf", provenance="ProvB")
```

Nothing checks that you declared every MCF file you wrote, so a file you forget is simply absent
from the bundle the importer sees.

## How to validate and export the bundle

Validate without writing anything:

```python
manager.validate_config()
```

Raises a pydantic `ValidationError` or `ValueError` if the config is invalid, including if an
input file references a provenance that was never registered.

Export everything in one call:

```python
manager.export_all("output_directory")
```

`export_all` empties the directory first, deleting every existing file and subfolder, then writes the full bundle: `config.json`
always, the data CSVs for any registered DataFrames, `vertical_specs.json` if any specs were added,
and every MCF file you've added nodes to. To write only part of the bundle, use the individual
`export_*` methods below.

Pass `validate_data=True` to raise if any declared input file has no registered DataFrame
(pattern entries are exempt, since they carry no local data by design):

```python
manager.export_all("output_directory", validate_data=True)
```

To export pieces individually instead of all at once:

- `export_config(dir_path)` writes only `config.json` (and defaults `importName` to the directory
  name if you never set one).
- `export_data(dir_path)` writes the registered DataFrames as CSVs.
- `export_mcf_file(dir_path, mcf_file_name=...)` writes one MCF file.
- `export_vertical_specs(dir_path)` writes the vertical specs file.
- `config_to_dict()` returns the validated config as a dict without writing anything, and without
  defaulting `importName`, since there's no export directory to name it after.

## See also

- [Why config.json and MCF](dc-schemas.md): why column mappings and dcids are shaped the way they
  are.
- [Loading data](loading-data.md): upload the exported bundle to Google Cloud Storage and trigger
  the ingestion workflow.
- [CLI tools](cli-tools.md): the `dcp-tools csv2mcf` command for CSV-to-MCF conversion outside a
  `CustomDataManager`.
