---
description: Upload an exported bundle to Google Cloud Storage, trigger the Data Commons Platform ingestion workflow, check the upload, and fix common settings errors.
---

# How to upload and load data into a Data Commons Platform instance

Upload an exported data bundle to Google Cloud Storage, then trigger the Data Commons Platform (DCP) workflow that ingests it into your custom knowledge graph and serves it.

## Before you start

- A Data Commons Platform instance with the DCP ingestion pipeline already deployed. `dcp-tools` doesn't provision instances. Follow Google's [guide to deploying a custom instance ↗](https://docs.datacommons.org/custom_dc/deploy_cloud.html) first.

- An exported bundle: a local directory holding `config.json`, your CSV data files, and any `.mcf` files, built with `CustomDataManager.export_all` (see [Preparing data](preparing-data.md)).

- The settings `dcp-tools` needs to reach GCP and your ingestion resources, gathered into a `KGSettings` object:

  - `local_path` (`LOCAL_PATH`): local directory to export and upload. This is the bundle directory from the step above.
  - `gcp_project_id` (`GCP_PROJECT_ID`): your GCP project ID.
  - `gcp_region` (`GCP_REGION`): region the ingestion resources are deployed in.
  - `gcp_credentials` (`GCP_CREDENTIALS`, optional): GCP service account credentials as a JSON string. Leave unset to use Application Default Credentials (after `gcloud auth application-default login`).
  - `gcs_bucket_name` (`GCS_BUCKET_NAME`): the Cloud Storage bucket the DCP pipeline reads from.
  - `gcs_input_folder_path` (`GCS_INPUT_FOLDER_PATH`, optional): folder in that bucket to upload the bundle to. Defaults to `ingestion/input`, the DCP Terraform default.
  - `gcs_output_folder_path` (`GCS_OUTPUT_FOLDER_PATH`): folder the pipeline writes its output to.
  - `ingestion_prep_job_name` (`INGESTION_PREP_JOB_NAME`): name of the Cloud Run ingestion preprocessing job.
  - `ingestion_workflow_name` (`INGESTION_WORKFLOW_NAME`): name of the Cloud Workflow that runs the ingestion.
  - `ingestion_service_account` (`INGESTION_SERVICE_ACCOUNT`, optional): service account to impersonate when triggering the workflow. Leave unset to use your own credentials.

## Steps

1. **Build a `KGSettings` object.** `dcp-tools` reads these settings through `KGSettings`, a `pydantic-settings` model. Build one from a `.env` file, a JSON file, or directly, whichever fits how you manage secrets.

   ```python title="from a .env file"
   from dcp_tools.gcp_utilities import get_kg_settings

   settings = get_kg_settings(source="env", env_file="customDC.env")
   ```

   ```python title="from a JSON file"
   from dcp_tools.gcp_utilities import get_kg_settings

   settings = get_kg_settings(source="json", file="customDC.json")
   ```

   `customDC.json` uses the same names as the environment variables:

   ```json
   {
     "LOCAL_PATH": "path/to/output/folder",
     "GCP_PROJECT_ID": "one-campaign-dc",
     "GCP_REGION": "us-central1",
     "GCS_BUCKET_NAME": "one-campaign-dc-custom-data",
     "GCS_INPUT_FOLDER_PATH": "customdc/input",
     "GCS_OUTPUT_FOLDER_PATH": "customdc/output",
     "INGESTION_PREP_JOB_NAME": "dc-ingestion-preprocessing-job",
     "INGESTION_WORKFLOW_NAME": "dc-ingestion-workflow"
   }
   ```

   ```python title="constructing KGSettings directly"
   from pathlib import Path

   from dcp_tools.gcp_utilities import KGSettings

   settings = KGSettings(
       LOCAL_PATH=Path("path/to/output/folder"),
       GCP_PROJECT_ID="one-campaign-dc",
       GCP_REGION="us-central1",
       GCS_BUCKET_NAME="one-campaign-dc-custom-data",
       GCS_INPUT_FOLDER_PATH="customdc/input",
       GCS_OUTPUT_FOLDER_PATH="customdc/output",
       INGESTION_PREP_JOB_NAME="dc-ingestion-preprocessing-job",
       INGESTION_WORKFLOW_NAME="dc-ingestion-workflow",
   )
   ```

   Using the CLI instead of the Python API? Skip building a `KGSettings` object yourself and pass `--env-file customDC.env` or `--settings-file customDC.json` to any of the commands in the next two steps.

1. **Upload the bundle to Cloud Storage.** This pushes every `.csv`, `.json`, and `.mcf` file under `settings.local_path` to `gs://<gcs_bucket_name>/<gcs_input_folder_path>/`, preserving the directory structure. Other file types are skipped with a warning.

   ```python
   from dcp_tools.gcp_utilities import upload_to_cloud_storage

   upload_to_cloud_storage(settings=settings)
   ```

   ```bash
   dcp-tools upload --env-file customDC.env
   ```

   Pass `sync=True` (Python) or `--sync` (CLI) to also delete remote files that no longer have a local counterpart. This is useful when you've removed or renamed a CSV since the last upload. Sync prunes stale files under each import subdirectory present locally, and stale top-level files when the bundle has top-level files of its own. It won't touch an import that isn't in your local bundle at all.

   ```bash
   dcp-tools upload --env-file customDC.env --sync
   ```

1. **Trigger ingestion.** This starts the DCP ingestion workflow against whatever is currently in `gcs_input_folder_path`.

   ```python
   from dcp_tools.gcp_utilities import run_ingestion_workflow

   run_ingestion_workflow(settings=settings)                           # every import
   run_ingestion_workflow(settings=settings, imports="climateFinance")  # one import
   ```

   ```bash
   dcp-tools ingest --env-file customDC.env --imports=climateFinance
   ```

   To upload and trigger ingestion in one call, use `pipeline` instead of running `upload` and `ingest` separately:

   ```bash
   dcp-tools pipeline --env-file customDC.env --sync
   ```

   `pipeline` always loads every import. It has no `--imports` flag. If you need to load a subset, run `upload` then `ingest --imports=...` separately.

`run_ingestion_workflow` returns as soon as the workflow execution starts. It doesn't wait for it to finish. Under the hood it calls `datacommons-admin`'s `IngestionJobClient`, which starts the Cloud Workflow (`ingestion_workflow_name`) that ingests the uploaded data and serves it automatically. There's nothing further to trigger from `dcp-tools`.

> [!NOTE]
> Older versions of this package required a separate `redeploy` call after ingestion, plus a set of `CLOUD_SQL_*` settings to reach the underlying database. Both are gone. The DCP prep job now owns the restart, and there's no Cloud SQL in the current architecture.

## Verify it worked

Compare what's registered in `config.json` against what actually landed in the bucket:

```python
import json
from pathlib import Path

from dcp_tools.gcp_utilities import get_missing_csv_files, get_unregistered_csv_files
from dcp_tools.gcp_utilities.clients import get_gcs_client

config = json.loads(Path("path/to/output/folder/config.json").read_text())
bucket = get_gcs_client(settings.gcp_credentials).get_bucket(settings.gcs_bucket_name)

print(get_missing_csv_files(bucket, config, gcs_folder_name=settings.gcs_input_folder_path))
print(get_unregistered_csv_files(bucket, config, gcs_folder_name=settings.gcs_input_folder_path))
```

Both should return `[]`. A non-empty `get_missing_csv_files` result means a file the config expects never made it to GCS (upload failed, or it ran against the wrong folder). A non-empty `get_unregistered_csv_files` result means there's a stray CSV in the bucket that no `inputFiles` entry points at.

Ingestion itself runs as a Cloud Workflow execution (`ingestion_workflow_name` in `gcp_region`). Its run history and logs are visible in the Google Cloud Console under Workflows, not through `dcp-tools`.

## Troubleshooting

- **`KGSettings`/`get_kg_settings` raises a `pydantic.ValidationError` listing several fields as "Field required".** One or more required settings are missing from your `.env`/JSON file, or weren't passed to the constructor. Every field except `gcp_credentials`, `gcs_input_folder_path`, and `ingestion_service_account` is required. Check the list under [Before you start](#before-you-start).
- **`GCP_CREDENTIALS` raises `Invalid JSON`.** `gcp_credentials` expects the *contents* of a service-account key as a JSON string, not a file path. Read the key file and pass its contents (`Path("key.json").read_text()`), or leave the setting unset to use Application Default Credentials.
- **`get_missing_csv_files` reports every registered CSV as missing, even though the upload succeeded.** Both functions treat a `gcs_folder_name` that doesn't match anything in the bucket as an empty folder rather than raising: `get_missing_csv_files` then reports every `inputFiles` entry as missing, and `get_unregistered_csv_files` reports nothing (there's nothing to compare against). Check `gcs_input_folder_path` for a typo, or confirm the upload step ran first. Leading and trailing slashes are stripped automatically, so those aren't the issue.
- **`run_ingestion_workflow` raises `RuntimeError: Failed to start ingestion workflow: ...`.** The underlying `IngestionJobClient` call failed, most often from a wrong `ingestion_workflow_name`/`ingestion_prep_job_name`/`gcp_region`, or an `ingestion_service_account` that isn't allowed to invoke the workflow.

## See also

- [Preparing data](preparing-data.md): build the `config.json`, CSV, and MCF bundle before uploading it.
- [CLI tools](cli-tools.md): full flag reference for `upload`, `ingest`, and `pipeline`.
