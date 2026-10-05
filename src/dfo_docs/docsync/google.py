"""Thin REST client for the Drive v3, Docs v1 and Sheets v4 calls docsync makes.

Every call goes through a `requests.Session`. In production that is google-auth's
`AuthorizedSession` from `default_session`. Every Drive call that names or lists files
sets `supportsAllDrives`, and every listing searches one shared drive
(`corpora=drive`), because the DFO docs tree lives in the ONE Data shared drive and a
service account has no My Drive.

Every request retries 429, 500, 502, 503 and 504 responses and connection errors and
timeouts, up to five attempts with jittered exponential backoff. A non-2xx response
that is final, or the last failed attempt, raises `GoogleApiError` with Google's status
and message (status 0 for a transport error), so no `requests` exception leaves the
module. Creates are not idempotent, so before a create is retried the client looks for
the file the failed attempt may have made and returns it if found.

A response that is well formed but leaves the client unable to continue (two folders
with one name, a Sheet without a header row) raises `GoogleStateError`.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import google.auth
import google.auth.exceptions
import requests
from google.auth.transport.requests import AuthorizedSession

SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
)

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DOCS_DOCUMENTS = "https://docs.googleapis.com/v1/documents"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
MARKDOWN_MIME = "text/markdown"

PAGE_ID_PROPERTY = "dfo_page_id"

_TIMEOUT_SECONDS = 60
_ALL_DRIVES = {"supportsAllDrives": "true"}

_ATTEMPTS = 5
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
_BACKOFF_SECONDS = 1.0
_TRANSPORT_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    google.auth.exceptions.TransportError,
)

_SETTLE_EXPORTS = 6
_SETTLE_FIRST_WAIT_SECONDS = 2.0


class GoogleApiError(RuntimeError):
    """A request to Google failed with a non-2xx status or a transport error.

    `status` is the HTTP status code and `message` Google's error message (or the
    start of the response body when it is not Google's JSON error shape). A transport
    error (no response) has `status` 0 and the exception text as `message`.
    """

    def __init__(self, *, status: int, message: str, method: str, url: str) -> None:
        self.status = status
        self.message = message
        self.method = method
        self.url = url
        super().__init__(f"{method} {url} failed with {status}: {message}")


class GoogleStateError(RuntimeError):
    """Drive or a Sheet holds something the client cannot act on safely."""


class ExportNotSettledError(GoogleStateError):
    """Consecutive Markdown exports of a Doc kept differing."""

    def __init__(self, file_id: str, exports: int) -> None:
        self.file_id = file_id
        super().__init__(
            f"Doc {file_id} gave a different Markdown export each time "
            f"across {exports} exports"
        )


@dataclass
class DriveFile:
    """A Drive file as listed: id, name and its Drive `properties`."""

    id: str
    name: str
    properties: dict[str, str]


@dataclass
class Comment:
    """An open Drive comment on a file."""

    id: str
    content: str
    author: str
    quoted: str


def default_session() -> AuthorizedSession:
    """Return an authorised session from Application Default Credentials.

    Raises:
        google.auth.exceptions.DefaultCredentialsError: No credentials are configured.
    """
    credentials, _ = google.auth.default(scopes=list(SCOPES))
    return AuthorizedSession(credentials)


# Drive


def get_drive_id(session: requests.Session, file_id: str) -> str:
    """Return the id of the shared drive that holds `file_id`.

    Raises:
        GoogleStateError: The file is not in a shared drive.
    """
    payload = _request(
        session,
        "GET",
        f"{DRIVE_FILES}/{file_id}",
        params={**_ALL_DRIVES, "fields": "id,driveId"},
    ).json()
    drive_id = payload.get("driveId")
    if not drive_id:
        raise GoogleStateError(f"file {file_id} is not in a shared drive")
    return drive_id


def ensure_folder_path(
    session: requests.Session,
    *,
    drive_id: str,
    parent_id: str,
    names: Sequence[str],
) -> str:
    """Return the id of folder `names[-1]` under `parent_id`, creating missing folders.

    Each name is one level, so `["DFO docs", "Hub"]` is `<parent>/DFO docs/Hub`.

    Raises:
        GoogleStateError: Two folders at one level share a name.
    """
    folder_id = parent_id
    for name in names:
        matches = _list_files(
            session,
            drive_id=drive_id,
            q=(
                f"{_quote(folder_id)} in parents and name = {_quote(name)}"
                f" and mimeType = {_quote(FOLDER_MIME)} and trashed = false"
            ),
        )
        if len(matches) > 1:
            ids = ", ".join(match.id for match in matches)
            raise GoogleStateError(
                f"folder {folder_id} holds {len(matches)} folders named {name!r}: {ids}"
            )
        if matches:
            folder_id = matches[0].id
            continue
        folder_id = _create_file(
            session,
            metadata={"name": name, "mimeType": FOLDER_MIME, "parents": [folder_id]},
            drive_id=drive_id,
        )
    return folder_id


def create_doc(
    session: requests.Session,
    *,
    name: str,
    markdown: str,
    parent_id: str,
    properties: Mapping[str, str],
) -> str:
    """Upload `markdown` as a new Google Doc in `parent_id` and return its id.

    Drive converts the Markdown to a Doc. `properties` are Drive `properties`, which
    every OAuth client can read, so state lookups work from CI and a laptop alike.
    They are set by the create request itself, so a Doc never exists untagged, and a
    retried create returns the Doc in `parent_id` that carries them if one exists.

    Raises:
        GoogleStateError: A retried create found two Docs carrying `properties`.
    """
    return _create_file(
        session,
        metadata={
            "name": name,
            "mimeType": DOC_MIME,
            "parents": [parent_id],
            "properties": dict(properties),
        },
        media=markdown.encode(),
    )


def replace_doc_content(
    session: requests.Session, *, file_id: str, markdown: str
) -> None:
    """Replace the whole content of Doc `file_id` with converted `markdown`.

    The file id, name, properties, comments and sharing stay as they were.
    """
    body, content_type = _multipart_related({}, markdown.encode())
    _request(
        session,
        "PATCH",
        f"{DRIVE_UPLOAD}/{file_id}",
        params={**_ALL_DRIVES, "uploadType": "multipart", "fields": "id"},
        data=body,
        headers={"Content-Type": content_type},
    )


def trash_file(session: requests.Session, file_id: str) -> None:
    """Move `file_id` to the trash of its shared drive."""
    _request(
        session,
        "PATCH",
        f"{DRIVE_FILES}/{file_id}",
        params={**_ALL_DRIVES, "fields": "id"},
        json_body={"trashed": True},
    )


def export_markdown(session: requests.Session, file_id: str) -> str:
    """Return Doc `file_id` exported as Markdown."""
    response = _request(
        session,
        "GET",
        f"{DRIVE_FILES}/{file_id}/export",
        params={"mimeType": MARKDOWN_MIME},
    )
    # Drive sends text/markdown without a charset, and requests would then guess
    # ISO-8859-1. The export is UTF-8.
    return response.content.decode("utf-8")


def export_settled(session: requests.Session, file_id: str) -> str:
    """Return Doc `file_id` exported as Markdown once two exports in a row agree.

    An export taken shortly after an upload can differ from the one Drive settles on
    (inline code losing its backticks, for one). This exports, waits, and exports
    again, doubling the wait from 2 seconds, until two consecutive exports are
    identical, for at most six exports.

    Raises:
        ExportNotSettledError: No two consecutive exports agreed.
    """
    previous = export_markdown(session, file_id)
    wait = _SETTLE_FIRST_WAIT_SECONDS
    for _ in range(_SETTLE_EXPORTS - 1):
        time.sleep(wait)
        current = export_markdown(session, file_id)
        if current == previous:
            return current
        previous = current
        wait *= 2
    raise ExportNotSettledError(file_id, _SETTLE_EXPORTS)


def list_open_comments(session: requests.Session, file_id: str) -> list[Comment]:
    """Return every comment on `file_id` that is neither resolved nor deleted."""
    comments: list[Comment] = []
    params: dict[str, str] = {
        "fields": (
            "nextPageToken,comments(id,content,resolved,deleted,"
            "author(displayName),quotedFileContent(value))"
        ),
        "includeDeleted": "false",
        "pageSize": "100",
    }
    while True:
        payload = _request(
            session, "GET", f"{DRIVE_FILES}/{file_id}/comments", params=params
        ).json()
        comments.extend(
            Comment(
                id=item["id"],
                content=item.get("content", ""),
                author=item.get("author", {}).get("displayName", ""),
                quoted=item.get("quotedFileContent", {}).get("value", ""),
            )
            for item in payload.get("comments", [])
            if not item.get("resolved") and not item.get("deleted")
        )
        if not (token := payload.get("nextPageToken")):
            return comments
        params["pageToken"] = token


def find_docs(
    session: requests.Session, *, drive_id: str, page_id: str
) -> list[DriveFile]:
    """Return every untrashed Doc whose `dfo_page_id` property is `page_id`."""
    return _list_files(
        session,
        drive_id=drive_id,
        q=(
            f"properties has {{ key={_quote(PAGE_ID_PROPERTY)}"
            f" and value={_quote(page_id)} }}"
            f" and mimeType = {_quote(DOC_MIME)} and trashed = false"
        ),
    )


def find_files_with_property(
    session: requests.Session,
    *,
    drive_id: str,
    parent_id: str,
    mime_type: str,
    key: str,
    value: str,
) -> list[DriveFile]:
    """Return every untrashed `mime_type` file in `parent_id` whose property `key` is `value`."""
    return _list_files(
        session,
        drive_id=drive_id,
        q=(
            f"{_quote(parent_id)} in parents"
            f" and properties has {{ key={_quote(key)} and value={_quote(value)} }}"
            f" and mimeType = {_quote(mime_type)} and trashed = false"
        ),
    )


def set_properties(
    session: requests.Session, file_id: str, properties: Mapping[str, str]
) -> None:
    """Add or overwrite Drive `properties` on `file_id`, keeping its other properties."""
    _request(
        session,
        "PATCH",
        f"{DRIVE_FILES}/{file_id}",
        params={**_ALL_DRIVES, "fields": "id"},
        json_body={"properties": dict(properties)},
    )


def list_synced_docs(
    session: requests.Session, *, drive_id: str
) -> dict[str, list[DriveFile]]:
    """Return every untrashed Doc in the drive that carries `dfo_page_id`, by page id.

    Drive search cannot ask whether a property key exists, so this lists every Doc in
    the drive and keeps those with the property.
    """
    synced: dict[str, list[DriveFile]] = {}
    for doc in _list_files(
        session,
        drive_id=drive_id,
        q=f"mimeType = {_quote(DOC_MIME)} and trashed = false",
    ):
        if page_id := doc.properties.get(PAGE_ID_PROPERTY):
            synced.setdefault(page_id, []).append(doc)
    return synced


# Docs


def open_suggestion_ids(session: requests.Session, document_id: str) -> frozenset[str]:
    """Return the ids of every open suggestion in Doc `document_id`.

    Reads the document with suggestions inline and the content of every tab, child
    tabs included, and collects every value under a key that starts with `suggested`:
    `suggestedInsertionIds`, `suggestedDeletionIds`, `suggestedTextStyleChanges`, and
    the paragraph, bullet, table and positioned object variants. An empty set means
    the Doc has no open suggestions.
    """
    document = _request(
        session,
        "GET",
        f"{DOCS_DOCUMENTS}/{document_id}",
        params={
            "suggestionsViewMode": "SUGGESTIONS_INLINE",
            "includeTabsContent": "true",
        },
    ).json()
    ids: set[str] = set()
    _collect_suggestion_ids(document, ids)
    return frozenset(ids)


def doc_revision_id(session: requests.Session, document_id: str) -> str:
    """Return the Docs API `revisionId` of Doc `document_id`.

    The id changes whenever the Doc's content changes, so two equal ids taken at two
    moments mean nobody edited the Doc in between.
    """
    return _request(
        session,
        "GET",
        f"{DOCS_DOCUMENTS}/{document_id}",
        params={"fields": "revisionId"},
    ).json()["revisionId"]


def _collect_suggestion_ids(node: object, ids: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_suggestion_ids(item, ids)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key.startswith("suggested"):
            if isinstance(value, list):
                ids.update(item for item in value if isinstance(item, str))
            elif isinstance(value, dict):
                ids.update(value)
        _collect_suggestion_ids(value, ids)


# Sheets


def create_sheet(
    session: requests.Session,
    *,
    name: str,
    parent_id: str,
    tab: str,
    columns: Sequence[str],
    validations: Mapping[str, Sequence[str]],
    properties: Mapping[str, str] | None = None,
) -> str:
    """Create a Sheet in `parent_id` whose first tab holds `columns` as a header row.

    The Sheet is created through Drive so it lands in the shared drive, with
    `properties` as Drive `properties` set by the create request itself. A retried
    create returns the Sheet in `parent_id` that carries `properties` (or, with no
    `properties`, the Sheet named `name`) if one exists. `validations` maps a column
    name to the values its cells may take, shown as a dropdown below the header.
    Returns the spreadsheet id.

    Raises:
        GoogleStateError: A validation names a column absent from `columns`, or a
            retried create found two matching Sheets.
    """
    unknown = sorted(set(validations) - set(columns))
    if unknown:
        raise GoogleStateError(f"validations name unknown columns: {unknown}")

    metadata: dict[str, Any] = {
        "name": name,
        "mimeType": SHEET_MIME,
        "parents": [parent_id],
    }
    if properties:
        metadata["properties"] = dict(properties)
    spreadsheet_id = _create_file(session, metadata=metadata)
    sheets = _request(
        session,
        "GET",
        f"{SHEETS}/{spreadsheet_id}",
        params={"fields": "sheets.properties.sheetId"},
    ).json()["sheets"]
    sheet_id = sheets[0]["properties"]["sheetId"]

    batch: list[dict[str, Any]] = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "title": tab,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "title,gridProperties.frozenRowCount",
            }
        },
        {
            "updateCells": {
                "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                "rows": [
                    {
                        "values": [
                            {"userEnteredValue": {"stringValue": column}}
                            for column in columns
                        ]
                    }
                ],
                "fields": "userEnteredValue",
            }
        },
    ]
    for column, values in validations.items():
        index = columns.index(column)
        batch.append(
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": index,
                        "endColumnIndex": index + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": value} for value in values],
                        },
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            }
        )
    _request(
        session,
        "POST",
        f"{SHEETS}/{spreadsheet_id}:batchUpdate",
        json_body={"requests": batch},
    )
    return spreadsheet_id


def tab_titles(session: requests.Session, spreadsheet_id: str) -> list[str]:
    """Return the title of every tab of the spreadsheet, in tab order."""
    sheets = _request(
        session,
        "GET",
        f"{SHEETS}/{spreadsheet_id}",
        params={"fields": "sheets.properties.title"},
    ).json()["sheets"]
    return [sheet["properties"]["title"] for sheet in sheets]


def add_text_tab(
    session: requests.Session,
    spreadsheet_id: str,
    *,
    tab: str,
    lines: Sequence[str],
) -> None:
    """Add tab `tab` to the spreadsheet holding `lines`, one per row in column A."""
    _request(
        session,
        "POST",
        f"{SHEETS}/{spreadsheet_id}:batchUpdate",
        json_body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
    )
    cell = f"{_sheet_range(tab)}!A1"
    _request(
        session,
        "PUT",
        f"{SHEETS}/{spreadsheet_id}/values/{quote(cell, safe='')}",
        params={"valueInputOption": "RAW"},
        json_body={
            "range": cell,
            "majorDimension": "ROWS",
            "values": [[line] for line in lines],
        },
    )


def read_rows(
    session: requests.Session, spreadsheet_id: str, *, tab: str
) -> list[dict[str, str]]:
    """Return every non-blank row of `tab` as a mapping from header to cell text.

    Raises:
        GoogleStateError: The tab has no header row.
    """
    header, *rows = _read_grid(session, spreadsheet_id, tab=tab)
    return [dict(zip(header, row, strict=True)) for row in rows if any(row)]


def upsert_rows(
    session: requests.Session,
    spreadsheet_id: str,
    *,
    tab: str,
    key_column: str,
    rows: Sequence[Mapping[str, str]],
) -> None:
    """Write `rows` into `tab`, matching existing rows on `key_column`.

    Each row writes only the columns it names, cell by cell, so a column a row leaves
    out (Owner, Status, Notes) keeps whatever an editor typed. A row whose key is not
    in the tab is added below the last row.

    Raises:
        GoogleStateError: The tab has no header row, a row names a column the header
            lacks or omits `key_column`, or two tab rows share a key.
    """
    header, *existing = _read_grid(session, spreadsheet_id, tab=tab)
    column_index = {column: index for index, column in enumerate(header) if column}
    if key_column not in column_index:
        raise GoogleStateError(f"tab {tab!r} has no {key_column!r} column")
    for row in rows:
        unknown = sorted(set(row) - set(column_index))
        if unknown:
            raise GoogleStateError(f"tab {tab!r} has no columns {unknown}")
        if not row.get(key_column):
            raise GoogleStateError(f"row {dict(row)} has no {key_column!r}")

    key_index = column_index[key_column]
    row_number: dict[str, int] = {}
    for offset, cells in enumerate(existing):
        key = cells[key_index]
        if not key:
            continue
        if key in row_number:
            raise GoogleStateError(
                f"tab {tab!r} has {key_column} {key!r} on rows "
                f"{row_number[key]} and {offset + 2}"
            )
        row_number[key] = offset + 2

    next_row = len(existing) + 2
    data: list[dict[str, Any]] = []
    sheet = _sheet_range(tab)
    for row in rows:
        key = row[key_column]
        if key not in row_number:
            row_number[key] = next_row
            next_row += 1
        number = row_number[key]
        data.extend(
            {
                "range": f"{sheet}!{_column_letter(column_index[column])}{number}",
                "values": [[value]],
            }
            for column, value in row.items()
        )
    if not data:
        return
    _request(
        session,
        "POST",
        f"{SHEETS}/{spreadsheet_id}/values:batchUpdate",
        json_body={"valueInputOption": "RAW", "data": data},
    )


def _read_grid(
    session: requests.Session, spreadsheet_id: str, *, tab: str
) -> list[list[str]]:
    """Return `tab` as rows of cell text, every row padded to the header's width."""
    sheet = _sheet_range(tab)
    values = (
        _request(
            session,
            "GET",
            f"{SHEETS}/{spreadsheet_id}/values/{quote(sheet, safe='')}",
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
        )
        .json()
        .get("values", [])
    )
    if not values or not any(values[0]):
        raise GoogleStateError(f"tab {tab!r} has no header row")
    width = len(values[0])
    return [[*row, *[""] * (width - len(row))][:width] for row in values]


def _sheet_range(tab: str) -> str:
    """Quote a tab name for A1 notation."""
    return "'" + tab.replace("'", "''") + "'"


def _column_letter(index: int) -> str:
    """Return the A1 column letters for zero-based column `index`."""
    letters = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


# Transport


class _TransientError(Exception):
    """A failed attempt worth retrying. `error` is what to raise if none is left."""

    def __init__(self, error: GoogleApiError) -> None:
        super().__init__(str(error))
        self.error = error


def _retrying[T](attempt: Callable[[int], T]) -> T:
    """Call `attempt(n)` for n = 0, 1, ... until it stops raising `_TransientError`.

    Waits between attempts with exponential backoff and jitter. After the last
    attempt, raises the `GoogleApiError` of its failure.
    """
    for number in range(_ATTEMPTS):
        if number:
            ceiling = _BACKOFF_SECONDS * 2 ** (number - 1)
            time.sleep(random.uniform(ceiling / 2, ceiling))
        try:
            return attempt(number)
        except _TransientError as transient:
            failure = transient.error
    raise failure


def _request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    json_body: Mapping[str, Any] | None = None,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> requests.Response:
    """Send one request, retrying transient failures. Use only for idempotent calls."""
    return _retrying(
        lambda _: _send(
            session,
            method,
            url,
            params=params,
            json_body=json_body,
            data=data,
            headers=headers,
        )
    )


def _send(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    json_body: Mapping[str, Any] | None = None,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> requests.Response:
    """Send one attempt. Raise `_TransientError` for a failure worth retrying."""
    try:
        response = session.request(
            method,
            url,
            params=params,
            json=json_body,
            data=data,
            headers=headers,
            timeout=_TIMEOUT_SECONDS,
        )
    except _TRANSPORT_ERRORS as error:
        failure = GoogleApiError(status=0, message=str(error), method=method, url=url)
        raise _TransientError(failure) from error
    except requests.RequestException as error:
        raise GoogleApiError(
            status=0, message=str(error), method=method, url=url
        ) from error
    if response.ok:
        return response
    failure = GoogleApiError(
        status=response.status_code,
        message=_error_message(response),
        method=method,
        url=url,
    )
    if response.status_code in _RETRY_STATUSES or _is_rate_limit(response):
        raise _TransientError(failure)
    raise failure


def _is_rate_limit(response: requests.Response) -> bool:
    """Whether `response` is a Drive 403 that reports a rate limit, as a 429 does."""
    if response.status_code != 403:
        return False
    try:
        errors = response.json()["error"]["errors"]
    except (ValueError, KeyError, TypeError):
        return False
    return isinstance(errors, list) and any(
        isinstance(item, dict) and item.get("reason") in _RATE_LIMIT_REASONS
        for item in errors
    )


def _create_file(
    session: requests.Session,
    *,
    metadata: Mapping[str, Any],
    media: bytes | None = None,
    drive_id: str | None = None,
) -> str:
    """Create a Drive file from `metadata` (and `media`, converted) and return its id.

    A failed create may still have made the file, so each retry first looks for it in
    the parent and returns its id when found. `drive_id` saves the lookup a call to
    find the parent's shared drive.
    """

    def attempt(number: int) -> str:
        if number and (found := _find_created(session, metadata, drive_id)):
            return found
        if media is None:
            response = _send(
                session,
                "POST",
                DRIVE_FILES,
                params={**_ALL_DRIVES, "fields": "id"},
                json_body=metadata,
            )
        else:
            body, content_type = _multipart_related(metadata, media)
            response = _send(
                session,
                "POST",
                DRIVE_UPLOAD,
                params={**_ALL_DRIVES, "uploadType": "multipart", "fields": "id"},
                data=body,
                headers={"Content-Type": content_type},
            )
        return response.json()["id"]

    return _retrying(attempt)


def _find_created(
    session: requests.Session, metadata: Mapping[str, Any], drive_id: str | None
) -> str | None:
    """Return the id of the file in `metadata`'s parent that matches it, if any.

    A file matches on parent, MIME type and every Drive property, or on name when
    `metadata` sets no properties.

    Raises:
        GoogleStateError: More than one file matches.
    """
    (parent_id,) = metadata["parents"]
    clauses = [
        f"{_quote(parent_id)} in parents",
        f"mimeType = {_quote(metadata['mimeType'])}",
        "trashed = false",
    ]
    if properties := metadata.get("properties"):
        clauses.extend(
            f"properties has {{ key={_quote(key)} and value={_quote(value)} }}"
            for key, value in properties.items()
        )
    else:
        clauses.append(f"name = {_quote(metadata['name'])}")
    matches = _list_files(
        session,
        drive_id=drive_id or get_drive_id(session, parent_id),
        q=" and ".join(clauses),
    )
    if len(matches) > 1:
        ids = ", ".join(match.id for match in matches)
        raise GoogleStateError(
            f"folder {parent_id} holds {len(matches)} files matching a retried "
            f"create of {metadata['name']!r}: {ids}"
        )
    return matches[0].id if matches else None


def _error_message(response: requests.Response) -> str:
    try:
        error = response.json().get("error", {})
    except ValueError:
        return response.text[:500]
    if isinstance(error, dict) and error.get("message"):
        return error["message"]
    return response.text[:500]


def _list_files(session: requests.Session, *, drive_id: str, q: str) -> list[DriveFile]:
    files: list[DriveFile] = []
    params: dict[str, str] = {
        "q": q,
        "corpora": "drive",
        "driveId": drive_id,
        "includeItemsFromAllDrives": "true",
        **_ALL_DRIVES,
        "fields": "nextPageToken,files(id,name,properties)",
        "pageSize": "1000",
    }
    while True:
        payload = _request(session, "GET", DRIVE_FILES, params=params).json()
        files.extend(
            DriveFile(
                id=item["id"],
                name=item["name"],
                properties=item.get("properties", {}),
            )
            for item in payload.get("files", [])
        )
        if not (token := payload.get("nextPageToken")):
            return files
        params["pageToken"] = token


def _quote(value: str) -> str:
    """Quote `value` as a Drive search string literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _multipart_related(metadata: Mapping[str, Any], media: bytes) -> tuple[bytes, str]:
    """Return a multipart/related upload body and its Content-Type header."""
    boundary = f"dfo-docsync-{uuid.uuid4().hex}"
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            json.dumps(metadata).encode(),
            f"\r\n--{boundary}\r\nContent-Type: {MARKDOWN_MIME}; charset=UTF-8\r\n\r\n".encode(),
            media,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/related; boundary={boundary}"
