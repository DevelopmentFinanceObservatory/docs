---
description: Upload an exported bundle to Google Cloud Storage, trigger the Data Commons Platform ingestion workflow, check the upload, and fix common settings errors.
---

# How to upload and load data into a Data Commons Platform instance

Upload an exported data bundle to Google Cloud Storage, then trigger the Data Commons Platform (DCP) workflow that ingests it into your custom knowledge graph and serves it.

## Before you start

- A Data Commons Platform 1.1.6 instance with the DCP ingestion pipeline already deployed. `dcp-tools` 1.1 starts ingestion the way DCP 1.1.6 expects and can't start it on an older stack. `dcp-tools` doesn't provision instances. Follow Google's [guide to deploying a custom instance ↗](https://docs.datacommons.org/custom_dc/deploy_cloud.html) first.

- An exported bundle: a local directory holding `config.json`, your CSV data files, and any `.mcf` files, built with `CustomDataManager.export_all` (see [Preparing data](preparing-data.md)).

- The settings `dcp-tools` needs to reach GCP and your ingestion resources, gathered into a `KGSettings` object:

  - `local_path` (`LOCAL_PATH`, optional): local directory to upload when you don't pass one to `upload_to_cloud_storage`. This is the bundle directory from the step above.
  - `gcp_project_id` (`GCP_PROJECT_ID`): your GCP project ID.
  - `gcp_region` (`GCP_REGION`): region the ingestion resources are deployed in.
  - `gcp_credentials` (`GCP_CREDENTIALS`, optional): GCP service account credentials as a JSON string. Leave unset to use Application Default Credentials (after `gcloud auth application-default login`). Only the Cloud Storage calls use it. Starting an ingestion always uses Application Default Credentials.
  - `gcs_bucket_name` (`GCS_BUCKET_NAME`): the Cloud Storage bucket the DCP pipeline reads from.
  - `gcs_input_folder_path` (`GCS_INPUT_FOLDER_PATH`, optional): folder in that bucket to upload the bundle to. Defaults to `ingestion/input`, the DCP Terraform default.
  - `gcs_output_folder_path` (`GCS_OUTPUT_FOLDER_PATH`, optional): folder the pipeline writes its output to.
  - `ingestion_workflow_name` (`INGESTION_WORKFLOW_NAME`): name of the Cloud Workflow that runs the ingestion.
  - `ingestion_service_account` (`INGESTION_SERVICE_ACCOUNT`, optional): service account that Application Default Credentials impersonate to read and start the workflow. Leave unset to start it as your Application Default Credentials identity.

## Steps

1. **Build a `KGSettings` object.** `dcp-tools` reads these settings through `KGSettings`, a `pydantic-settings` model. Build one from a `.env` file, a JSON file, or directly, whichever fits how you manage secrets. A `.env` file can hold other variables too: `KGSettings` ignores any it doesn't define. A JSON file or constructor call rejects unknown keys.

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
       INGESTION_WORKFLOW_NAME="dc-ingestion-workflow",
   )
   ```

   Using the CLI instead of the Python API? Skip building a `KGSettings` object yourself and pass `--env-file customDC.env` or `--settings-file customDC.json` to any of the commands in the next two steps.

1. **Upload the bundle to Cloud Storage.** This pushes every `.csv`, `.json`, and `.mcf` file under `settings.local_path` to `gs://<gcs_bucket_name>/<gcs_input_folder_path>/`, preserving the directory structure. Other file types are skipped with a warning. A file whose MD5 matches the blob already at its remote path isn't uploaded again.

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

`run_ingestion_workflow` returns as soon as the workflow execution starts. To wait for it to finish, use `wait_for_ingestion`, or `--wait` on the CLI. Under the hood it calls `datacommons-admin`'s `IngestionJobClient`, which starts the Cloud Workflow (`ingestion_workflow_name`) with the list of imports to load. The workflow runs preprocessing as a Cloud Batch job it creates itself, ingests the uploaded data, and serves it. There's nothing further to trigger from `dcp-tools`.

Before starting the workflow, `run_ingestion_workflow` calls `check_ingestion_workflow_contract`, which reads the workflow's definition from the Workflows API and checks that it comes from a DCP 1.1.6 stack: the 1.1.6 workflow creates its preprocessing job on Cloud Batch, and older workflows run a Cloud Run job that needs arguments `dcp-tools` 1.1 no longer sends. When the workflow is older, or its definition can't be read, it raises `WorkflowContractError` and nothing starts. `dcp-tools pipeline` runs the check before uploading, so an older stack receives no files. Call `check_ingestion_workflow_contract(settings)` yourself to do the same before your own upload. The identity that starts the ingestion (the `ingestion_service_account` when it is set, otherwise your Application Default Credentials) needs `roles/workflows.viewer` for the check, as well as `roles/workflows.invoker` to start the workflow. `roles/workflows.invoker` grants `workflows.executions.create` and `workflows.executions.get`, but not the `workflows.workflows.get` permission that reading the definition needs. If you can't grant `roles/workflows.viewer` and know the stack is on 1.1.6, pass `skip_workflow_contract_check=True`, or `--skip-workflow-contract-check` on the CLI, to skip the check.

`run_ingestion_workflow` returns the execution's resource name. Pass it to `get_ingestion_execution_state` to follow the run:

```python
from dcp_tools.gcp_utilities import get_ingestion_execution_state, run_ingestion_workflow

execution = run_ingestion_workflow(settings=settings)
state = get_ingestion_execution_state(settings, execution)
print(state.state)          # "ACTIVE", then "SUCCEEDED", "FAILED" or "CANCELLED"
print(state.current_steps)  # ("main.run_preprocessing", ...) while it runs
print(state.error)          # the error payload when it failed, otherwise None
print(state.state_error)    # why the data is unavailable ("UNAVAILABLE" state), otherwise None
```

To block until the run finishes, pass the resource name to `wait_for_ingestion`. It polls every 30 seconds by default, logs the state and current steps when they change, and returns the terminal state: `SUCCEEDED`, `FAILED` or `CANCELLED`. `UNAVAILABLE` means the API can't read the execution's data, for example after its KMS key permissions were revoked. The execution may still be running, so polling continues and logs a warning with `state_error`. A failed run is returned, not raised, so check the state yourself:

```python
from dcp_tools.gcp_utilities import run_ingestion_workflow, wait_for_ingestion

execution = run_ingestion_workflow(settings=settings)
state = wait_for_ingestion(settings, execution, timeout=2 * 60 * 60)
if state.state != "SUCCEEDED":
    raise RuntimeError(f"Ingestion ended {state.state}: {state.error}")
```

Without `timeout` it waits indefinitely, including on an execution that stays `UNAVAILABLE`. With one, it raises `TimeoutError` once that many seconds pass, and the execution keeps running. On the CLI, `--wait` does the same and exits non-zero if the run does not succeed:

```bash
dcp-tools pipeline --env-file customDC.env --wait --timeout 7200
```

> [!NOTE]
> `ingestion_prep_job_name` (`INGESTION_PREP_JOB_NAME`) is deprecated and ignored, and will be removed in 2.0. Setting it emits a `FutureWarning`. Delete it from your settings.

> [!NOTE]
> Versions before 1.0 required a separate `redeploy` call after ingestion, plus a set of `CLOUD_SQL_*` settings to reach the underlying database. Both are gone. The ingestion workflow serves the new data itself, and there's no Cloud SQL in the current architecture.

## Verify it worked

Compare what's registered in `config.json` against what actually landed in the bucket:

```python
import json
from pathlib import Path

from dcp_tools.gcp_utilities import get_missing_csv_files, get_unregistered_csv_files
from dcp_tools.gcp_utilities.clients import get_gcs_client

config = json.loads(Path("path/to/output/folder/config.json").read_text())
client = get_gcs_client(settings.gcp_credentials, project=settings.gcp_project_id)
bucket = client.get_bucket(settings.gcs_bucket_name)

print(get_missing_csv_files(bucket, config, gcs_folder_name=settings.gcs_input_folder_path))
print(get_unregistered_csv_files(bucket, config, gcs_folder_name=settings.gcs_input_folder_path))
```

Both should return `[]`. A non-empty `get_missing_csv_files` result means a file the config expects never made it to GCS (upload failed, or it ran against the wrong folder). A non-empty `get_unregistered_csv_files` result means there's a stray CSV in the bucket that no `inputFiles` entry points at.

Ingestion itself runs as a Cloud Workflow execution (`ingestion_workflow_name` in `gcp_region`). `get_ingestion_execution_state` reports its state, `wait_for_ingestion` waits for it to finish, and its run history and logs are in the Google Cloud Console under Workflows.

## Troubleshooting

- **`KGSettings`/`get_kg_settings` raises a `pydantic.ValidationError` listing several fields as "Field required".** One or more required settings are missing from your `.env`/JSON file, or weren't passed to the constructor. The required fields are `gcp_project_id`, `gcs_bucket_name`, `gcp_region`, and `ingestion_workflow_name`. Check the list under [Before you start](#before-you-start).
- **`GCP_CREDENTIALS` raises `Invalid JSON`.** `gcp_credentials` expects the *contents* of a service-account key as a JSON string, not a file path. Read the key file and pass its contents (`Path("key.json").read_text()`), or leave the setting unset to use Application Default Credentials.
- **`get_missing_csv_files` reports every registered CSV as missing, even though the upload succeeded.** Both functions treat a `gcs_folder_name` that doesn't match anything in the bucket as an empty folder rather than raising: `get_missing_csv_files` then reports every `inputFiles` entry as missing, and `get_unregistered_csv_files` reports nothing (there's nothing to compare against). Check `gcs_input_folder_path` for a typo, or confirm the upload step ran first. Leading and trailing slashes are stripped automatically, so those aren't the issue.
- **`run_ingestion_workflow` raises `RuntimeError: Failed to start ingestion workflow: ...`.** The underlying `IngestionJobClient` call failed, most often from a wrong `ingestion_workflow_name`/`gcp_region`, or an `ingestion_service_account` that isn't allowed to invoke the workflow.
- **`run_ingestion_workflow` raises `WorkflowContractError`.** The workflow comes from a DCP stack older than 1.1.6, or its definition couldn't be read. Use `dcp-tools` 1.0 with DCP stacks up to 1.1.5. If the message says the definition couldn't be read, grant `roles/workflows.viewer` to the identity starting the ingestion, or pass `skip_workflow_contract_check=True` (`--skip-workflow-contract-check` on the CLI) once you've confirmed the stack is on 1.1.6.

## See also

- [Preparing data](preparing-data.md): build the `config.json`, CSV, and MCF bundle before uploading it.
- [CLI tools](cli-tools.md): full flag reference for `upload`, `ingest`, and `pipeline`.
