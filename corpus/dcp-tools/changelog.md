---
description: Read dcp-tools release notes from version 0.0.1 onwards, including changes to the API, settings and exported files.
---

# Changelog

## Unreleased

- dcp-tools leaves logging to the importing application: its module loggers sit under `dcp_tools`, propagate to the root logger and set no handler or level, so unconfigured applications see only warnings. `LOG_LEVEL` now applies to the `dcp-tools` CLI only, which still prints its messages.
- Deprecated `dcp_tools.logger` and the `dcp-tools` logger name, to be removed in 2.0. Until then both resolve to the `dcp_tools` package logger, provided `dcp-tools` is configured after dcp-tools is imported.

## v1.0.1 (2026-10-13)

- Fixed a fresh install failing to import `dcp_tools.gcp_utilities`, which broke the `dcp-tools` CLI and `run_ingestion_workflow`. `datacommons-admin` 1.1.3 moved `IngestionJobClient` to a new module, and 1.1.6 removed the `job_name` argument dcp-tools passes. The dependency is now capped at `datacommons-admin<1.1.3` until dcp-tools supports the new client.

## v1.0.0 (2026-10-13)

First stable release under the name `dcp-tools`. The API is unchanged since v1.0.0a5, and from this release on, breaking changes wait for a new major version. To upgrade from `bblocks-datacommons-tools` 0.1.1, follow the migration notes in the v1.0.0a1 to v1.0.0a5 entries below, which describe each change in detail.

- **Breaking:** renamed the package from `bblocks-datacommons-tools` to `dcp-tools`, the import path to `dcp_tools` and the CLI to `dcp-tools`. The old distribution installs `dcp-tools` and re-exports it with a `DeprecationWarning`.
- **Breaking:** ingestion runs on the Data Commons Platform. `run_data_load` is now `run_ingestion_workflow`, the ingestion settings are renamed, and the Cloud SQL and redeploy settings and commands are removed.
- **Breaking:** the Python API is snake_case throughout, the node models drop their `MCF` prefix, and `add_source` and `add_provenance` take separate `dcid` and `name` parameters.
- **Breaking:** `export_all` writes the complete bundle and empties the target directory first.
- **Breaking:** the variable-per-column (implicit schema) input format and the `redeploy` command are removed.
- Added `add_node`, `add_mcf_file`, Source and Provenance nodes with licence, refresh and coverage metadata, multi-entity observations through `custom:<name>` dimensions, and `constraint_properties` on StatVars.
- Minimum supported Python is 3.13.

## v1.0.0a5 (2026-09-10)

- **Breaking:** `license_type` and `curator` are now DCID references, written as
  `licenseType: dcid:<token>` instead of a quoted string. Bare tokens passed to `add_source` /
  `add_provenance` are minted; `SourceNode` / `ProvenanceNode` still require the `dcid:` prefix.
- **Breaking:** renamed the ingestion settings to match the DCP Terraform outputs:
  `LOAD_JOB_NAME` -> `INGESTION_PREP_JOB_NAME`, `LOAD_JOB_REGION` -> `GCP_REGION`, and
  `LOAD_JOB_SERVICE_ACCOUNT` -> `INGESTION_SERVICE_ACCOUNT`. The old names are no longer accepted.
- **Breaking:** renamed `run_data_load` to `run_ingestion_workflow`, and the `dataload` CLI
  command to `ingest`. `imports` is now keyword-only, so `run_data_load(settings, "climateFinance")`
  becomes `run_ingestion_workflow(settings, imports="climateFinance")`.
- **Breaking:** `export_all` now empties the target directory before writing.
- Added `license_type` and `license_attribution` to `add_source`, and `source_data_url` and
  `license_attribution` to `add_provenance`.

## v1.0.0a4 (2026-09-07)

- `add_provenance` now warns instead of raising when `source` isn't registered in the bundle,
  so a `Provenance` can reference a `Source` that already exists in base Data Commons.

## v1.0.0a3 (2026-08-19)

- Added `add_node(dcid=..., name=..., type_of=...)` to `CustomDataManager`, for MCF nodes with a
  caller-supplied `typeOf` e.g. entity instances (e.g. an organisation) or constraint-value
  classes (e.g. `Commitment`) the typed builders don't cover.
- `gcs_input_folder_path` (`GCS_INPUT_FOLDER_PATH`) is now optional and defaults to
  `ingestion/input`, the DCP Terraform default.
- Fixed `KGSettings` rejecting its snake_case field names; `KGSettings(local_path=...)` now works
  alongside `KGSettings(LOCAL_PATH=...)`.

## v1.0.0a2 (2026-08-10)

- **Breaking:** `ProvenanceNode.source_link` is renamed to `source`, so a provenance's parent
  source now serializes as `source: dcid:source/<name>` (was `sourceLink:`), the property name
  Data Commons ingestion preprocessing expects.
- Added `add_mcf_file(file_name, provenance=...)` to declare an MCF file in `config.json`'s
  `inputFiles`. `add_mcf_file("*.mcf", provenance=...)` covers them all in a single-provenance
  import; declare each file separately when an import has more than one provenance.
- Added `constraint_properties` to `StatVarNode` and as a parameter on `add_variable_to_mcf`,
  for the DCID(s) of properties that constrain the StatisticalVariable. Bare tokens are minted
  to `dcid:<token>`.
- **Breaking:** `datacommons-admin` was bumped to `>=1.1.1` and now required a
  `ingestion_workflow_name` (`INGESTION_WORKFLOW_NAME`) setting.
- Fixed `run_data_load` and the `dataload`/`pipeline` commands not loading every import when
  none are named.

## v1.0.0a1 (2026-07-27)

- First alpha of the `dcp-tools` package, the first release under the new name.
- Renamed the package from `bblocks-datacommons-tools` to `dcp-tools`. The import path is
  now `dcp_tools` (was `bblocks.datacommons_tools`). Installing the old
  `bblocks-datacommons-tools` distribution now pulls in `dcp-tools` and re-exports it with a
  `DeprecationWarning`; update imports to `dcp_tools` at your convenience.
- Minimum supported Python is now 3.13 (was 3.11).
- Packaging now follows the `bblocks-projects` copier template (ruff lint preset, `ty` type
  checking, pre-commit hooks, PyPI trusted publishing).
- **Breaking:** removed support for the second, implicit import mechanism —
  `add_implicit_schema_file`, `add_variable_to_config`, and the `ImplicitSchemaFile` /
  `Variable` model classes are gone. `ObservationProperties` is retained but repurposed: it's
  no longer nested under a variable definition, and now carries the file-level constant
  observation properties on `InputFile`; it also accepts custom keys (`extra="allow"`, was
  `extra="forbid"`), and the four standard fields are unchanged. Loading a legacy
  `variablePerColumn` config now raises `ValueError`. Migrate by using `add_input_file` with
  `column_mappings`; see
  [Data Commons custom data docs](https://docs.datacommons.org/custom_dc/custom_data.html).
- **Breaking:** with a single import format left, the input-file API drops the "explicit"
  qualifier: `ExplicitSchemaFile` is now `InputFile` and `add_explicit_schema_file` is now
  `add_input_file`. The arguments are the same ones (in the snake_case spelling below) and the
  generated `config.json` is unchanged.
- **Breaking:** `Config.input_files` is now `list[InputFile]` (was a dict keyed by file name).
  `InputFile` also rejects unknown keys now (`extra="forbid"`).
- **Breaking:** `export_mfc_file` is now spelled `export_mcf_file`, and
  `csv_metadata_to_mfc_file` is now `csv_metadata_to_mcf_file`.
- **Breaking:** removed the `entity` key on `ColumnMappings`. Use `observationAbout` for
  single-entity data or `custom:<name>` for multi-entity dimensions.
- Added support for multi-entity observations using custom dimensions: declare each
  dimension with `custom:<name>` in `ColumnMappings` and a matching `dcid:<name>` in the
  StatVar's `observation_properties`.
- Single-entity StatVars no longer emit `observationProperties` by default.
- Fixed `rename_variable`, which left the `Nodes` lookup index keyed by the old name, so a
  following variable removal raised "not found" for the renamed node and still resolved
  the old name. The rename now goes through a new `Nodes.rename`, which keeps the index
  in step.
- Fixed `export_data`, `export_mcf_file`, and `export_vertical_specs` raising `OSError`
  when the target file name nested in a subdirectory that did not yet exist (for example
  an `add_input_file` name such as `"sub/gdp.csv"`). Each now creates the parent
  directory before writing.
- Fixed `add_variable_to_mcf`, which did not normalize a bare `dcid` to `dcid:<token>`
  like the schema-node builders do, so a bare token raised a `ValidationError` there
  while working everywhere else. Its `population_type`, `measured_property`,
  `measurement_qualifier` and `measurement_denominator` arguments had the same gap and
  now accept bare tokens too.
- Fixed `DcidOrListDcid`, which used a `PlainValidator` that replaced the wrapped `Dcid`
  schema rather than running before it, so the `dcid:` prefix check never ran. Any
  string, prefixed or not, passed through and landed in the MCF verbatim. This affected
  `type_of` on every node, `relevant_variable`, `observation_properties` and `member` on
  StatVar nodes, and `included_in`, `sub_class_of`, `domain_includes`, `range_includes` and
  `sub_property_of` on the schema-node builders. These fields now normalize a bare token to
  `dcid:<token>` and reject anything empty or whitespace-bearing, and a non-string value
  now raises rather than being accepted silently. Breaking for anyone
  passing a bare token to one of these fields today and relying on it staying bare.
- **Breaking:** `member_of` on a StatVar now has to be a real group dcid. It had the same
  bypass, so any string reached the MCF verbatim; it now requires a `g/` segment, so
  `one/g/economy` is minted to `dcid:one/g/economy` and `dcid:economy` is rejected. Check the
  values you pass to `add_variable_to_mcf` and the `memberOf` column of your StatVar CSVs.
- **Breaking:** `relevant_variable` on a Topic node is now plain `DcidOrListDcid`. Its type used
  to combine the fixed variant with two unfixed ones, so a value the fixed one rejected still
  got through the others. It accepts the same StatVar, group and topic dcids as before, and
  now rejects the malformed values that used to slip past.
- **Breaking:** nodes now validate on assignment, not only on construction. Setting a
  field to an invalid value, for example `node.member_of = "garbage"` or renaming a node to a
  token with no `dcid:` prefix, raises instead of quietly writing it to the MCF file.
- **Breaking:** `build_stat_var_groups_from_strings` is replaced by `resolve_group_paths`. It
  used `member_of` to hold an unresolved group path such as `"Economic/Employment"` until it
  was overwritten, which is what blocked validating the field. Group paths are now resolved
  before the nodes are built. If you call it directly, use
  `csv_metadata_to_nodes(..., parse_groups=True, group_namespace=...)` instead.
  `add_variables_to_mcf_from_csv` is unchanged.
- Fixed `add_variables_to_mcf_from_csv(parse_groups=True)` raising `AttributeError` when the
  CSV had no `memberOf` column or a row left it blank. The missing column now raises a clear
  `ValueError`, and a blank value leaves that node's `member_of` unset. A group path holding a
  whitespace-only segment, such as a stray tab between two slashes, also used to mint a group
  with an empty name; those segments are now dropped.
- **Breaking:** a Topic node's `dcid` now has to carry the `dcid:` prefix. The old check
  looked for a `topic/` segment anywhere in the string and never required the prefix, so
  `topic/x` validated and was written to the MCF unprefixed. Add `dcid:` to the `Node` column
  of any topic CSV. Data Commons rejects unprefixed node ids on load, so those files were not
  loading correctly to begin with.
- **Breaking:** re-pointed the data load flow at the DCP prep job, using the
  `IngestionJobClient`. `run_data_load` now triggers the prep job. The `redeploy`
  CLI command and the `redeploy_service`
  and `redeploy_cloud_run_service` functions are removed; the service restart is now owned
  by the ingestion workflow. Load-job settings are renamed: `CLOUD_RUN_JOB_NAME` →
  `LOAD_JOB_NAME`, `CLOUD_JOB_REGION` → `LOAD_JOB_REGION`, plus a new optional
  `LOAD_JOB_SERVICE_ACCOUNT` that sets which service account the load job impersonates
  (when unset, the caller's credentials are used). The unused Cloud SQL and Cloud Run
  service settings are removed too: `CLOUD_SQL_DB_NAME`, `CLOUD_SQL_REGION`,
  `CLOUD_SERVICE_REGION`, `CLOUD_RUN_SERVICE_NAME`, and `DATACOMMONS_SERVICE_IMAGE`.
- Added an `imports` argument on `run_data_load` and a matching `--imports` flag on the
  `dataload` CLI command, to trigger a load of specific imports rather than all imports.
- **Breaking:** renamed the node model classes to drop the `MCF` qualifier — `MCFNode` →
  `Node`, `MCFNodes` → `Nodes`, and every subclass. MCF is now treated as one serialization
  of a Data Commons graph node.
- **Breaking:** a node's identifier is now a single `dcid` property — the duplicate
  `Node`/`dcid` pair is collapsed. Access it via `node.dcid`; it still serializes to the
  `Node:` line in MCF.
- **Breaking:** `Node.mcf` is now the `Node.to_mcf()` method.
- **Breaking:** the Python API is snake_case throughout — node/`Config` attributes, builder
  keyword arguments and the `set_*` methods. Serialisation still uses camelCase using
  pydantic's `alias_generator=to_camel`.
- **Breaking:** `export_all` writes and overwrites the complete bundle, and no longer takes
  `mcf_file_names` or `override`. It writes `config.json`, the data CSVs, `vertical_specs.json`
  (when specs were added), and every MCF file you've added nodes to, overwriting what's already
  there. Pass nothing for the full bundle; use `export_mcf_file` for a single file.
- **Breaking:** `override` is renamed to `overwrite` on `export_mcf_file`, `Nodes.export_to_mcf_file`
  and `csv_metadata_to_mcf_file`, and now defaults to overwriting.
- **Breaking:** `csv2mcf` replaces `--override` with `--append`. It overwrites the output file by
  default; pass `--append` to add to an existing file instead.
- **Breaking:** `add_source` and `add_provenance` take separate `dcid` (identifier, minted with the
  slug prefix), optional `name` (label), and `description` parameters. Previously `name` was the
  identifier and no `name` property was set — pass the identifier as `dcid=` now.
- **Breaking:** `CustomDataManager.remove_indicator` is renamed to `remove_variable` (parameter
  `indicator_id` → `dcid`), matching the `variable` terminology used elsewhere.

## v0.1.1 (2026-02-19)

- Added a `--sync` flag to the `upload` and `pipeline` CLI commands, which deletes remote
  blobs that no longer have a local counterpart after uploading.
- Added `sync_directory_to_gcs` in `storage.py`, which composes upload and stale blob cleanup.
- Added a `sync` parameter on `upload_to_cloud_storage`.

## v0.1.0 (2026-02-13)

- Initial release of the `dcp-tools` package for external preview and testing

## v0.0.9 (2025-09-17)

- Added new configuration options, including `set_customIdNamespace`, `set_customSvgPrefix`,
  `set_defaultCustomRootStatVarGroupName` and `set_svHierarchyPropsBlocklist`.

## v0.0.8 (2025-09-03)

- Removed white space between quoted items to defend against a bug with data loading on
  the DC side.

## v0.0.7 (2025-08-27)

- Handle linebreaks and trailing spaces by removing them. This prevents errors when serialising
  to MCF which could (quietly) break the data loading job.

## v0.0.6 (2025-08-14)

- Node name is now an optional attribute. This enables easily appending data to existing Base DC Nodes.

## v0.0.5 (2025-08-14)

- Nodes can now contain a single `dcid` or a list of `dcids`

## v0.0.4 (2025-07-22)

- Improved how groups strings are transformed to camelCase by dealing with
  additional special characters
- Removed option to override input and output folders on the data load job.

## v0.0.3 (2025-07-18)

- Fixes two bugs related to MCF files. It now enforces the `dcid:` prefix for Node and
  automatically trims spaces between `dcid:` and the start of the id string.

## v0.0.2 (2025-07-07)

- Minor update to documentation and release to PyPI

## v0.0.1 (2025-07-07)

- Initial release of the `dcp-tools`
