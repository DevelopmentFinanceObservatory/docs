---
description: Why dcp-tools writes both config.json and MCF files, how a CSV column becomes an observation predicate, and how custom dimensions carry bilateral data.
---

# Why `config.json` and MCF, not one file

## The question this page answers

`CustomDataManager.export_all` writes a `config.json` and one or more `.mcf` files side by
side. Why two formats instead of one, and how does a CSV column end up as a predicate on a
Data Commons observation? For the mechanics of calling `add_input_file`, `add_variable_to_mcf`,
and friends, see [Preparing data](preparing-data.md).

## The short answer

`config.json` and `.mcf` do different jobs. `config.json` tells the importer how to *read your
CSVs*: which column holds the variable, which holds the date, which holds the entity a row is
about. MCF tells the importer what *new graph nodes exist* that aren't already in the base Data
Commons graph: your StatVars, your groups, your sources and provenances, and, for genuinely new
concepts, custom entity types, event types, properties, units, and measurement methods. Every
input file dcp-tools produces is variable-per-row (one observation per row). That's the only
layout the current importer accepts, so there's no format to choose. The `columnMappings` block
in `config.json` uses `dcid:observationAbout` for a row about one entity, and `custom:<name>` for a
row about several. That split exists because a single dcid reference can't represent a bilateral
relationship.

## What a Data Commons Platform deployment needs

A Data Commons Platform instance serves an organisation's own data next to the base Data Commons
knowledge graph. The
platform's ingestion workflow reads a declarative bundle (config, CSVs, MCF) and turns it into
graph nodes and observations. `dcp-tools` builds that bundle. It doesn't talk to a database and it
doesn't run the ingestion workflow itself. `CustomDataManager` assembles the files, and
[`run_ingestion_workflow`](loading-data.md) hands them to the platform.

The full shape of the bundle format, including fields not covered here, is documented at
[docs.datacommons.org/custom_dc/custom_data.html](https://docs.datacommons.org/custom_dc/custom_data.html).
The part `dcp-tools` exists to make easier to construct is narrower: how a CSV column becomes a
predicate, and why the schema-defining nodes live in a separate file format.

## The reasoning

### `config.json` declares column roles, not data

Every entry in `config.json`'s `inputFiles` list points at either a CSV of observations or an
MCF file of node definitions. A CSV entry carries a `columnMappings` block. The block
doesn't hold data. It holds a role assignment, naming which column in *this specific CSV* plays
which part in *every* observation the importer will build from it. An MCF entry carries no
mappings, since it has no columns to assign. It carries only the provenance its nodes belong to.

```python
from dcp_tools import CustomDataManager
import pandas as pd

manager = CustomDataManager()
manager.add_source(dcid="ONEData", url="https://data.one.org")
manager.add_provenance(
    dcid="ONEClimateFinance",
    url="https://datacommons.one.org/data/climate-finance-files",
    source="ONEData",
)

commitments = pd.DataFrame({
    "country": ["Germany", "France", "Japan"],
    "year": [2023, 2023, 2023],
    "variable": ["climateFinanceProvidedCommitments"] * 3,
    "value": [2_100, 1_450, 3_200],
})

manager.add_input_file(
    "climate-finance/commitments.csv",
    provenance="ONEClimateFinance",
    data=commitments,
    column_mappings={
      "observationAbout": "country",
      "date": "year",
      "variable": "variable",
      "value": "value",
    },
)
```

The resulting `config.json` entry:

```json
{
    "filename": "climate-finance/commitments.csv",
    "provenance": "dcid:provenance/ONEClimateFinance",
    "columnMappings": {
        "dcid:variableMeasured": "variable",
        "dcid:observationDate": "year",
        "dcid:value": "value",
        "dcid:observationAbout": "country"
    },
    "format": "variablePerRow"
}
```

Each key in `columnMappings` is a role the importer already understands (`observationAbout`,
`date`, `variable`, `value`, `unit`, `scalingFactor`, `measurementMethod`,
`observationPeriod`). The string you supply is the name of the column that fills that role in
*this* file. `add_input_file` accepts the short names (`variable`, `date`, and so on).
`config.json` stores all but `scalingFactor` under their `dcid:`-prefixed aliases because that's the predicate
form the importer reads them as. Two files can map the same role to differently named columns (one CSV might call
its date column `year`, another `fiscal_year`) because the mapping is declared per file.

What `columnMappings` cannot do is invent a column that isn't there, or tell the importer what a
value like `climateFinanceProvidedCommitments` *means*. That's the MCF file's job. It defines
the `climateFinanceProvidedCommitments` StatVar node once, and every row across every CSV that
references it by that dcid inherits the definition.

### Why bilateral data needs a different mechanism from observationAbout

`observationAbout` takes exactly one column, because it fills exactly one predicate:
"this observation is about this entity." That works for the commitments file above, one country
per row. It stops working the moment a row describes a relationship between two entities instead
of a fact about one.

Take provider-to-recipient climate finance flows. Each row already has two country columns,
neither of which is uniquely "the" entity the row is about. Continuing with the same `manager`
from above, register a StatVar that names the two dimensions, then register the file:

```python
flows = pd.DataFrame({
    "provider": ["Germany", "France", "Japan"],
    "recipient": ["Kenya", "Senegal", "Vietnam"],
    "year": [2023, 2023, 2023],
    "variable": ["climateFinanceProvidedFlows"] * 3,
    "value": [340, 210, 480],
})

manager.add_variable_to_mcf(
    dcid="climateFinanceProvidedFlows",
    name="Climate finance provided (bilateral flow)",
    stat_type="dcid:measuredValue",
    observation_properties=["dcid:providerCountry", "dcid:recipientCountry"],
)

manager.add_input_file(
    "climate-finance/flows.csv",
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
```

A row with `custom:<name>` keys needs no `observationAbout`, as the flows file above shows. Each `custom:<name>` key becomes a `dcid:<name>` property reference on the
observation. The StatVar's own `observationProperties` list tells the importer which
properties to expect and validate against. Here that's `providerCountry` and `recipientCountry`,
declared once on the StatVar rather than re-derived per file. A single-entity StatVar doesn't
need this list at all. It's specific to the multi-entity case, because the importer has no other
way to know that a row with two country columns is deliberately structured that way and not
missing an `observationAbout`.

### Two dcid rules, and why they aren't the same rule

Names you pass to `add_source` and `add_provenance` go through a different minting rule than
names you pass to `add_entity_type`, `add_property`, `add_unit`, or `Node`/`populationType`/etc.
on `add_variable_to_mcf`. Both rules turn a bare token into a `dcid:`-prefixed one, but only one
of them inserts a namespace segment:

- `add_source(dcid="ONEData", ...)` mints `dcid:source/ONEData`.
- `add_property(dcid="providerCountry", ...)` mints `dcid:providerCountry`, no `property/`
  segment.

The difference tracks what's being identified. A source or provenance name is usually a short
organisational label: `"ONEData"`, `"WEO"`, `"IMF"`. Two different datasets, even two teams at
the same organisation, can plausibly both register a source called `"WorldBank"`. Nesting the
name under `source/` or `provenance/` means that collision has to happen inside a much smaller
namespace (one
organisation's list of sources), and it keeps a
source's identity separate from a provenance's even if someone reuses the same word for both.

A custom entity type, property, unit, or measurement method doesn't have that problem, because
defining one *is* the act of claiming a unique identifier. When you call
`add_property(dcid="providerCountry", ...)`, you declare that `dcid:providerCountry` is now a `Property` node. The
`typeOf: dcid:Property` on the node itself is what disambiguates it from a same-named source or
StatVar. That's why these builders use `ensure_dcid`, which
only adds the `dcid:` prefix, while sources and provenances use `mint_dcid`, which adds a
namespace segment too.

## Consequences

`columnMappings` is always required on a CSV entry, because it is how the importer finds your columns.

## Related

- [Preparing data](preparing-data.md) walks through `CustomDataManager` end to end: sources,
  provenances, variables, input files, and export.
- [CLI tools](cli-tools.md) covers `csv2mcf`, for building MCF node files straight from a CSV
  without going through `CustomDataManager`.
