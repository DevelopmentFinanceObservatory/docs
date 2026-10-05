# dcp-tools

**Prepare and load data for Data Commons Platform instances.**

`dcp-tools` is a Python package for building the config, metadata, and data files a Data Commons
Platform instance needs, then uploading them and triggering ingestion. Use it as a library or
through the `dcp-tools` command-line tool.

!!! note
    This package was published as `bblocks-datacommons-tools` until version 0.1.1, and imported
    as `bblocks.datacommons_tools`. Installing the old distribution now pulls in `dcp-tools` and
    redirects those imports with a `DeprecationWarning`, so existing code keeps working. Update
    imports to `dcp_tools` when convenient.

**Key features**
