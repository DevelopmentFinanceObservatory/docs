---
description: Build Data Commons Platform import files with the dcp-tools Python API or CLI, upload them, and trigger ingestion.
---

# dcp-tools

**Prepare and load data for Data Commons Platform instances.**

`dcp-tools` is a Python package for building the config, metadata, and data files a Data Commons
Platform instance needs, then uploading them and triggering ingestion. Use it as a library or
through the `dcp-tools` command-line tool.

A Data Commons Platform instance lets an organisation combine its own datasets with the public
knowledge graph at [datacommons.org](https://datacommons.org/), while reusing the platform's
search and visualisation tools. The official
[Custom Data Commons documentation](https://docs.datacommons.org/custom_dc/index.html) covers how
the platform itself works. This site covers the tooling that prepares and loads data into it.

> [!NOTE]
> This package was published as `bblocks-datacommons-tools` until version 0.1.1, and imported
> as `bblocks.datacommons_tools`. Installing the old distribution now pulls in `dcp-tools` and
> redirects those imports with a `DeprecationWarning`, so existing code keeps working. Update
> imports to `dcp_tools` when convenient.

**Key features**

- Build and edit `config.json` files programmatically
- Register single- and multi-entity observations from CSV data
- Declare custom schema nodes (entity types, event types, properties, units, measurement methods, StatVars, and StatVar groups) with typed builders
- Upload prepared files to Google Cloud Storage and trigger the DCP (Data Commons Platform) ingestion workflow
- Usable as a Python API or through the `dcp-tools` CLI

## Where to go next

- **[Getting started](getting-started.md)**: install `dcp-tools` and build a first import, from an empty config to files ready to upload.
- **[Preparing data](preparing-data.md)**: task recipes covering the full `CustomDataManager` surface, from input files and custom dimensions to schema nodes and config merging.
- **[Why config.json and MCF](dc-schemas.md)**: the reasoning behind the `config.json`/MCF split, dcid minting rules, and how multi-entity observations use custom dimensions.
- **[Loading data](loading-data.md)**: upload prepared files to Cloud Storage and trigger the job that loads them into your instance.
- **[CLI tools](cli-tools.md)**: reference for the `dcp-tools` command and its subcommands.
