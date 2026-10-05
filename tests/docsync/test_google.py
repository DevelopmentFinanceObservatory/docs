"""Tests for the Google REST client, run against a fake HTTP transport.

The fake is a `requests` adapter mounted on a plain `Session`, so each test sees the
request exactly as `requests` would put it on the wire: method, URL, query string,
headers and body.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import requests
from requests.adapters import HTTPAdapter

from dfo_docs.docsync import google

DRIVE = "0APT8uPN8rOyGUk9PVA"
ALL_DRIVES = {"supportsAllDrives": "true"}
LISTING = {
    "corpora": "drive",
    "driveId": DRIVE,
    "includeItemsFromAllDrives": "true",
    "supportsAllDrives": "true",
    "fields": "nextPageToken,files(id,name,properties)",
    "pageSize": "1000",
}


@dataclass
class Expect:
    """One expected request and the response the fake returns for it."""

    method: str
    url: str
    params: dict[str, str] = field(default_factory=dict)
    json: Any = None
    check: Callable[[requests.PreparedRequest], None] | None = None
    status: int = 200
    reply: Any = None
    text: str | None = None
    raises: Exception | None = None


class FakeTransport(HTTPAdapter):
    """Answers requests from a script, asserting each matches the next `Expect`."""

    def __init__(self, script: list[Expect]) -> None:
        super().__init__()
        self.script = list(script)

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        assert self.script, f"unexpected request {request.method} {request.url}"
        expect = self.script.pop(0)
        assert request.url is not None
        parts = urlsplit(request.url)
        assert request.method == expect.method
        assert f"{parts.scheme}://{parts.netloc}{unquote(parts.path)}" == expect.url
        params = {key: values[0] for key, values in parse_qs(parts.query).items()}
        assert params == expect.params
        if expect.json is not None:
            assert request.headers["Content-Type"] == "application/json"
            assert request.body is not None
            assert json.loads(request.body) == expect.json
        if expect.check is not None:
            expect.check(request)
        if expect.raises is not None:
            raise expect.raises

        response = requests.Response()
        response.status_code = expect.status
        response.request = request
        response.url = request.url
        if expect.text is not None:
            response._content = expect.text.encode("utf-8")
            response.headers["Content-Type"] = "text/markdown"
        else:
            response._content = json.dumps(expect.reply or {}).encode()
            response.headers["Content-Type"] = "application/json"
        return response


def session_for(script: list[Expect]) -> tuple[requests.Session, FakeTransport]:
    transport = FakeTransport(script)
    session = requests.Session()
    session.mount("https://", transport)
    return session, transport


def run(script: list[Expect], call: Callable[[requests.Session], Any]) -> Any:
    session, transport = session_for(script)
    result = call(session)
    assert transport.script == [], "expected requests were never made"
    return result


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every wait the client asks for instead of sleeping."""
    waits: list[float] = []
    monkeypatch.setattr(google.time, "sleep", waits.append)
    return waits


# Errors


def test_google_error_carries_status_and_message() -> None:
    session, _ = session_for(
        [
            Expect(
                "GET",
                f"{google.DRIVE_FILES}/doc1/export",
                params={"mimeType": "text/markdown"},
                status=403,
                reply={"error": {"code": 403, "message": "Insufficient permissions"}},
            )
        ]
    )
    with pytest.raises(google.GoogleApiError) as caught:
        google.export_markdown(session, "doc1")
    assert caught.value.status == 403
    assert caught.value.message == "Insufficient permissions"
    assert "403" in str(caught.value)


def test_google_error_falls_back_to_body_text() -> None:
    session, _ = session_for(
        [
            Expect(
                "GET",
                f"{google.DRIVE_FILES}/doc1/export",
                params={"mimeType": "text/markdown"},
                status=400,
                text="Bad request",
            )
        ]
    )
    with pytest.raises(google.GoogleApiError) as caught:
        google.export_markdown(session, "doc1")
    assert (caught.value.status, caught.value.message) == (400, "Bad request")


EXPORT_URL = f"{google.DRIVE_FILES}/doc1/export"
EXPORT_PARAMS = {"mimeType": "text/markdown"}


def export_expect(**kwargs: Any) -> Expect:
    return Expect("GET", EXPORT_URL, params=EXPORT_PARAMS, **kwargs)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_status_is_retried_with_backoff(
    status: int, sleeps: list[float]
) -> None:
    script = [
        export_expect(status=status, text="busy"),
        export_expect(status=status, text="busy"),
        export_expect(text="# Done\n"),
    ]
    assert run(script, lambda s: google.export_markdown(s, "doc1")) == "# Done\n"
    assert len(sleeps) == 2
    assert 0.5 <= sleeps[0] <= 1.0
    assert 1.0 <= sleeps[1] <= 2.0


def drive_403(reason: str) -> dict[str, Any]:
    return {
        "error": {
            "code": 403,
            "message": "Rate limit or permission",
            "errors": [{"domain": "usageLimits", "reason": reason}],
        }
    }


@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
def test_rate_limit_403_is_retried_with_backoff(
    reason: str, sleeps: list[float]
) -> None:
    script = [
        export_expect(status=403, reply=drive_403(reason)),
        export_expect(status=403, reply=drive_403(reason)),
        export_expect(text="# Done\n"),
    ]
    assert run(script, lambda s: google.export_markdown(s, "doc1")) == "# Done\n"
    assert len(sleeps) == 2
    assert 0.5 <= sleeps[0] <= 1.0
    assert 1.0 <= sleeps[1] <= 2.0


def test_other_403_is_not_retried(sleeps: list[float]) -> None:
    session, transport = session_for(
        [export_expect(status=403, reply=drive_403("insufficientFilePermissions"))]
    )
    with pytest.raises(google.GoogleApiError) as caught:
        google.export_markdown(session, "doc1")
    assert caught.value.status == 403
    assert transport.script == []
    assert sleeps == []


def test_final_status_is_not_retried(sleeps: list[float]) -> None:
    session, transport = session_for([export_expect(status=404, text="gone")])
    with pytest.raises(google.GoogleApiError) as caught:
        google.export_markdown(session, "doc1")
    assert caught.value.status == 404
    assert transport.script == []
    assert sleeps == []


def test_retries_stop_after_five_attempts(sleeps: list[float]) -> None:
    session, transport = session_for(
        [export_expect(status=503, text="Backend Error")] * 5
    )
    with pytest.raises(google.GoogleApiError) as caught:
        google.export_markdown(session, "doc1")
    assert (caught.value.status, caught.value.message) == (503, "Backend Error")
    assert transport.script == []
    assert len(sleeps) == 4


@pytest.mark.parametrize(
    "error",
    [
        requests.ConnectionError("connection reset"),
        requests.ReadTimeout("read timed out"),
    ],
)
def test_transport_error_is_retried_then_raised_as_google_error(
    error: Exception,
) -> None:
    session, transport = session_for([export_expect(raises=error)] * 5)
    with pytest.raises(google.GoogleApiError) as caught:
        google.export_markdown(session, "doc1")
    assert caught.value.status == 0
    assert caught.value.message == str(error)
    assert transport.script == []


def test_transport_error_then_success() -> None:
    script = [
        export_expect(raises=requests.ConnectionError("reset")),
        export_expect(text="# Done\n"),
    ]
    assert run(script, lambda s: google.export_markdown(s, "doc1")) == "# Done\n"


def test_other_requests_error_is_wrapped_without_retry() -> None:
    session, transport = session_for(
        [export_expect(raises=requests.TooManyRedirects("loop"))]
    )
    with pytest.raises(google.GoogleApiError) as caught:
        google.export_markdown(session, "doc1")
    assert (caught.value.status, caught.value.message) == (0, "loop")
    assert transport.script == []


# Drive


def test_get_drive_id() -> None:
    script = [
        Expect(
            "GET",
            f"{google.DRIVE_FILES}/folder1",
            params={**ALL_DRIVES, "fields": "id,driveId"},
            reply={"id": "folder1", "driveId": DRIVE},
        )
    ]
    assert run(script, lambda s: google.get_drive_id(s, "folder1")) == DRIVE


def test_get_drive_id_refuses_my_drive_file() -> None:
    session, _ = session_for(
        [
            Expect(
                "GET",
                f"{google.DRIVE_FILES}/folder1",
                params={**ALL_DRIVES, "fields": "id,driveId"},
                reply={"id": "folder1"},
            )
        ]
    )
    with pytest.raises(google.GoogleStateError, match="not in a shared drive"):
        google.get_drive_id(session, "folder1")


def folder_query(parent: str, name: str) -> str:
    return (
        f"'{parent}' in parents and name = '{name}'"
        " and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )


def test_ensure_folder_path_reuses_and_creates() -> None:
    script = [
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": folder_query("root1", "DFO docs")},
            reply={"files": [{"id": "dfo", "name": "DFO docs"}]},
        ),
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": folder_query("dfo", "Hub")},
            reply={"files": []},
        ),
        Expect(
            "POST",
            google.DRIVE_FILES,
            params={**ALL_DRIVES, "fields": "id"},
            json={
                "name": "Hub",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": ["dfo"],
            },
            reply={"id": "hub"},
        ),
    ]
    result = run(
        script,
        lambda s: google.ensure_folder_path(
            s, drive_id=DRIVE, parent_id="root1", names=["DFO docs", "Hub"]
        ),
    )
    assert result == "hub"


def test_ensure_folder_path_escapes_quotes() -> None:
    script = [
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": folder_query("root1", "Editor\\'s notes")},
            reply={"files": [{"id": "notes", "name": "Editor's notes"}]},
        )
    ]
    result = run(
        script,
        lambda s: google.ensure_folder_path(
            s, drive_id=DRIVE, parent_id="root1", names=["Editor's notes"]
        ),
    )
    assert result == "notes"


def test_ensure_folder_path_refuses_duplicate_names() -> None:
    session, _ = session_for(
        [
            Expect(
                "GET",
                google.DRIVE_FILES,
                params={**LISTING, "q": folder_query("root1", "Hub")},
                reply={
                    "files": [{"id": "a", "name": "Hub"}, {"id": "b", "name": "Hub"}]
                },
            )
        ]
    )
    with pytest.raises(google.GoogleStateError, match="2 folders named 'Hub'"):
        google.ensure_folder_path(
            session, drive_id=DRIVE, parent_id="root1", names=["Hub"]
        )


def test_create_doc_uploads_markdown_with_properties() -> None:
    markdown = "# Get data\n\nCurly “quotes” survive.\n"

    def check(request: requests.PreparedRequest) -> None:
        content_type = request.headers["Content-Type"]
        assert content_type.startswith("multipart/related; boundary=")
        boundary = content_type.split("boundary=", 1)[1]
        assert isinstance(request.body, bytes)
        parts = request.body.split(f"--{boundary}".encode())
        assert parts[0] == b""
        assert parts[-1] == b"--\r\n"
        meta_head, meta_body = parts[1].split(b"\r\n\r\n", 1)
        assert meta_head == b"\r\nContent-Type: application/json; charset=UTF-8"
        assert json.loads(meta_body) == {
            "name": "Get data",
            "mimeType": "application/vnd.google-apps.document",
            "parents": ["hub"],
            "properties": {"dfo_page_id": "hub/get-data"},
        }
        media_head, media_body = parts[2].split(b"\r\n\r\n", 1)
        assert media_head == b"\r\nContent-Type: text/markdown; charset=UTF-8"
        assert media_body == markdown.encode() + b"\r\n"

    script = [
        Expect(
            "POST",
            google.DRIVE_UPLOAD,
            params={**ALL_DRIVES, "uploadType": "multipart", "fields": "id"},
            check=check,
            reply={"id": "doc1"},
        )
    ]
    result = run(
        script,
        lambda s: google.create_doc(
            s,
            name="Get data",
            markdown=markdown,
            parent_id="hub",
            properties={"dfo_page_id": "hub/get-data"},
        ),
    )
    assert result == "doc1"


def test_replace_doc_content_uploads_multipart_with_empty_metadata() -> None:
    def check(request: requests.PreparedRequest) -> None:
        content_type = request.headers["Content-Type"]
        assert content_type.startswith("multipart/related; boundary=")
        boundary = content_type.split("boundary=", 1)[1]
        assert isinstance(request.body, bytes)
        parts = request.body.split(f"--{boundary}".encode())
        meta_head, meta_body = parts[1].split(b"\r\n\r\n", 1)
        assert meta_head == b"\r\nContent-Type: application/json; charset=UTF-8"
        assert json.loads(meta_body) == {}
        media_head, media_body = parts[2].split(b"\r\n\r\n", 1)
        assert media_head == b"\r\nContent-Type: text/markdown; charset=UTF-8"
        assert media_body == b"# New\n\r\n"

    script = [
        Expect(
            "PATCH",
            f"{google.DRIVE_UPLOAD}/doc1",
            params={**ALL_DRIVES, "uploadType": "multipart", "fields": "id"},
            check=check,
            reply={"id": "doc1"},
        )
    ]
    run(
        script,
        lambda s: google.replace_doc_content(s, file_id="doc1", markdown="# New\n"),
    )


def test_export_markdown_decodes_utf8() -> None:
    script = [
        Expect(
            "GET",
            f"{google.DRIVE_FILES}/doc1/export",
            params={"mimeType": "text/markdown"},
            text="Côte d\u2019Ivoire\n",
        )
    ]
    assert (
        run(script, lambda s: google.export_markdown(s, "doc1"))
        == "Côte d\u2019Ivoire\n"
    )


def test_list_open_comments_pages_and_filters() -> None:
    params = {
        "fields": (
            "nextPageToken,comments(id,content,resolved,deleted,"
            "author(displayName),quotedFileContent(value))"
        ),
        "includeDeleted": "false",
        "pageSize": "100",
    }
    script = [
        Expect(
            "GET",
            f"{google.DRIVE_FILES}/doc1/comments",
            params=params,
            reply={
                "comments": [
                    {
                        "id": "c1",
                        "content": "Reword?",
                        "resolved": False,
                        "author": {"displayName": "Ada"},
                        "quotedFileContent": {"value": "the gap"},
                    },
                    {"id": "c2", "content": "Done", "resolved": True},
                ],
                "nextPageToken": "p2",
            },
        ),
        Expect(
            "GET",
            f"{google.DRIVE_FILES}/doc1/comments",
            params={**params, "pageToken": "p2"},
            reply={
                "comments": [
                    {"id": "c3", "content": "", "deleted": True},
                    {"id": "c4", "content": "Source?"},
                ]
            },
        ),
    ]
    comments = run(script, lambda s: google.list_open_comments(s, "doc1"))
    assert comments == [
        google.Comment(id="c1", content="Reword?", author="Ada", quoted="the gap"),
        google.Comment(id="c4", content="Source?", author="", quoted=""),
    ]


def test_find_docs_by_page_id() -> None:
    query = (
        "properties has { key='dfo_page_id' and value='hub/get-data' }"
        " and mimeType = 'application/vnd.google-apps.document' and trashed = false"
    )
    script = [
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": query},
            reply={
                "files": [
                    {
                        "id": "doc1",
                        "name": "Get data",
                        "properties": {"dfo_page_id": "hub/get-data"},
                    }
                ]
            },
        )
    ]
    docs = run(
        script, lambda s: google.find_docs(s, drive_id=DRIVE, page_id="hub/get-data")
    )
    assert docs == [
        google.DriveFile(
            id="doc1", name="Get data", properties={"dfo_page_id": "hub/get-data"}
        )
    ]


def test_list_synced_docs_groups_by_page_id_across_pages() -> None:
    query = "mimeType = 'application/vnd.google-apps.document' and trashed = false"
    script = [
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": query},
            reply={
                "files": [
                    {"id": "d1", "name": "A", "properties": {"dfo_page_id": "a"}},
                    {"id": "d2", "name": "Loose"},
                ],
                "nextPageToken": "t2",
            },
        ),
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": query, "pageToken": "t2"},
            reply={
                "files": [
                    {"id": "d3", "name": "A copy", "properties": {"dfo_page_id": "a"}}
                ]
            },
        ),
    ]
    synced = run(script, lambda s: google.list_synced_docs(s, drive_id=DRIVE))
    assert {page: [doc.id for doc in docs] for page, docs in synced.items()} == {
        "a": ["d1", "d3"]
    }


# Docs


def document_expect(reply: dict[str, Any]) -> Expect:
    return Expect(
        "GET",
        f"{google.DOCS_DOCUMENTS}/doc1",
        params={
            "suggestionsViewMode": "SUGGESTIONS_INLINE",
            "includeTabsContent": "true",
        },
        reply=reply,
    )


def text_tab(tab_id: str, text_run: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "tabProperties": {"tabId": tab_id},
        "documentTab": {
            "body": {"content": [{"paragraph": {"elements": [{"textRun": text_run}]}}]}
        },
        **extra,
    }


def test_open_suggestion_ids_scans_every_tab() -> None:
    document = {
        "documentId": "doc1",
        "tabs": [
            text_tab(
                "t.0",
                {"content": "Clean\n"},
                childTabs=[
                    text_tab(
                        "t.child",
                        {"content": "new", "suggestedInsertionIds": ["ins-child"]},
                    )
                ],
            ),
            text_tab("t.1", {"content": "old", "suggestedDeletionIds": ["del-tab2"]}),
        ],
    }
    ids = run(
        [document_expect(document)], lambda s: google.open_suggestion_ids(s, "doc1")
    )
    assert ids == {"ins-child", "del-tab2"}


def test_open_suggestion_ids_scans_body() -> None:
    document = {
        "documentId": "doc1",
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {
                                "textRun": {
                                    "content": "new",
                                    "suggestedInsertionIds": ["ins1"],
                                }
                            },
                            {
                                "textRun": {
                                    "content": "old",
                                    "suggestedDeletionIds": ["del1"],
                                    "suggestedTextStyleChanges": {
                                        "sty1": {"textStyle": {"bold": True}}
                                    },
                                }
                            },
                        ]
                    }
                },
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {
                                        "content": [
                                            {
                                                "paragraph": {
                                                    "elements": [],
                                                    "suggestedParagraphStyleChanges": {
                                                        "par1": {}
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                },
            ]
        },
    }
    ids = run(
        [document_expect(document)], lambda s: google.open_suggestion_ids(s, "doc1")
    )
    assert ids == {"ins1", "del1", "sty1", "par1"}


def test_open_suggestion_ids_empty_for_clean_doc() -> None:
    document = {
        "documentId": "doc1",
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
        "body": {
            "content": [
                {"paragraph": {"elements": [{"textRun": {"content": "Hello\n"}}]}}
            ]
        },
    }
    ids = run(
        [document_expect(document)], lambda s: google.open_suggestion_ids(s, "doc1")
    )
    assert ids == frozenset()


# Sheets

COLUMNS = ["Page id", "Title", "Owner", "Status"]


def test_create_sheet_in_shared_drive_with_header_and_validation() -> None:
    script = [
        Expect(
            "POST",
            google.DRIVE_FILES,
            params={**ALL_DRIVES, "fields": "id"},
            json={
                "name": "DFO docs tracker",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents": ["dfo"],
            },
            reply={"id": "sheet1"},
        ),
        Expect(
            "GET",
            f"{google.SHEETS}/sheet1",
            params={"fields": "sheets.properties.sheetId"},
            reply={"sheets": [{"properties": {"sheetId": 0}}]},
        ),
        Expect(
            "POST",
            f"{google.SHEETS}/sheet1:batchUpdate",
            json={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": 0,
                                "title": "Pages",
                                "gridProperties": {"frozenRowCount": 1},
                            },
                            "fields": "title,gridProperties.frozenRowCount",
                        }
                    },
                    {
                        "updateCells": {
                            "start": {"sheetId": 0, "rowIndex": 0, "columnIndex": 0},
                            "rows": [
                                {
                                    "values": [
                                        {"userEnteredValue": {"stringValue": column}}
                                        for column in COLUMNS
                                    ]
                                }
                            ],
                            "fields": "userEnteredValue",
                        }
                    },
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": 0,
                                "startRowIndex": 1,
                                "startColumnIndex": 3,
                                "endColumnIndex": 4,
                            },
                            "rule": {
                                "condition": {
                                    "type": "ONE_OF_LIST",
                                    "values": [
                                        {"userEnteredValue": "Not started"},
                                        {"userEnteredValue": "Editing"},
                                    ],
                                },
                                "strict": True,
                                "showCustomUi": True,
                            },
                        }
                    },
                ]
            },
        ),
    ]
    result = run(
        script,
        lambda s: google.create_sheet(
            s,
            name="DFO docs tracker",
            parent_id="dfo",
            tab="Pages",
            columns=COLUMNS,
            validations={"Status": ["Not started", "Editing"]},
        ),
    )
    assert result == "sheet1"


def test_create_sheet_refuses_unknown_validation_column_before_any_call() -> None:
    session, transport = session_for([])
    with pytest.raises(google.GoogleStateError, match="Reviewer"):
        google.create_sheet(
            session,
            name="x",
            parent_id="dfo",
            tab="Pages",
            columns=COLUMNS,
            validations={"Reviewer": ["a"]},
        )
    assert transport.script == []


def test_add_text_tab() -> None:
    script = [
        Expect(
            "POST",
            f"{google.SHEETS}/sheet1:batchUpdate",
            json={"requests": [{"addSheet": {"properties": {"title": "How to edit"}}}]},
        ),
        Expect(
            "PUT",
            f"{google.SHEETS}/sheet1/values/'How to edit'!A1",
            params={"valueInputOption": "RAW"},
            json={
                "range": "'How to edit'!A1",
                "majorDimension": "ROWS",
                "values": [["Open the Doc."], ["Edit the text."]],
            },
        ),
    ]
    run(
        script,
        lambda s: google.add_text_tab(
            s, "sheet1", tab="How to edit", lines=["Open the Doc.", "Edit the text."]
        ),
    )


def values_get(values: list[list[str]]) -> Expect:
    return Expect(
        "GET",
        f"{google.SHEETS}/sheet1/values/'Pages'",
        params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
        reply={"range": "Pages!A1:D3", "majorDimension": "ROWS", "values": values},
    )


def test_read_rows_pads_short_rows_and_skips_blank_ones() -> None:
    grid = [COLUMNS, ["hub/a", "A", "Ada"], [], ["hub/b", "B", "", "Editing"]]
    rows = run([values_get(grid)], lambda s: google.read_rows(s, "sheet1", tab="Pages"))
    assert rows == [
        {"Page id": "hub/a", "Title": "A", "Owner": "Ada", "Status": ""},
        {"Page id": "hub/b", "Title": "B", "Owner": "", "Status": "Editing"},
    ]


def test_read_rows_refuses_tab_without_header() -> None:
    session, _ = session_for([values_get([])])
    with pytest.raises(google.GoogleStateError, match="no header row"):
        google.read_rows(session, "sheet1", tab="Pages")


def test_upsert_rows_writes_only_named_columns() -> None:
    grid = [COLUMNS, ["hub/a", "Old title", "Ada", "Editing"], [], ["hub/b", "B"]]
    script = [
        values_get(grid),
        Expect(
            "POST",
            f"{google.SHEETS}/sheet1/values:batchUpdate",
            json={
                "valueInputOption": "RAW",
                "data": [
                    {"range": "'Pages'!A2", "values": [["hub/a"]]},
                    {"range": "'Pages'!B2", "values": [["New title"]]},
                    {"range": "'Pages'!A5", "values": [["hub/c"]]},
                    {"range": "'Pages'!B5", "values": [["C"]]},
                    {"range": "'Pages'!D4", "values": [["PR open"]]},
                    {"range": "'Pages'!A4", "values": [["hub/b"]]},
                ],
            },
        ),
    ]
    run(
        script,
        lambda s: google.upsert_rows(
            s,
            "sheet1",
            tab="Pages",
            key_column="Page id",
            rows=[
                {"Page id": "hub/a", "Title": "New title"},
                {"Page id": "hub/c", "Title": "C"},
                {"Status": "PR open", "Page id": "hub/b"},
            ],
        ),
    )


def test_upsert_rows_refuses_unknown_column_before_writing() -> None:
    session, transport = session_for([values_get([COLUMNS])])
    with pytest.raises(google.GoogleStateError, match="Notes"):
        google.upsert_rows(
            session,
            "sheet1",
            tab="Pages",
            key_column="Page id",
            rows=[{"Page id": "hub/a", "Notes": "x"}],
        )
    assert transport.script == []


def test_upsert_rows_refuses_duplicate_keys_in_tab() -> None:
    session, _ = session_for([values_get([COLUMNS, ["hub/a"], ["hub/a"]])])
    with pytest.raises(google.GoogleStateError, match="rows 2 and 3"):
        google.upsert_rows(
            session,
            "sheet1",
            tab="Pages",
            key_column="Page id",
            rows=[{"Page id": "hub/a", "Title": "A"}],
        )


@pytest.mark.parametrize(
    ("index", "letters"), [(0, "A"), (25, "Z"), (26, "AA"), (51, "AZ"), (702, "AAA")]
)
def test_column_letter(index: int, letters: str) -> None:
    assert google._column_letter(index) == letters


def test_find_files_with_property_in_folder() -> None:
    query = (
        "'root1' in parents and properties has { key='dfo_role' and"
        " value='tracking-sheet' } and mimeType ="
        " 'application/vnd.google-apps.spreadsheet' and trashed = false"
    )
    script = [
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": query},
            reply={"files": [{"id": "sheet1", "name": "DFO docs tracker"}]},
        )
    ]
    files = run(
        script,
        lambda s: google.find_files_with_property(
            s,
            drive_id=DRIVE,
            parent_id="root1",
            mime_type=google.SHEET_MIME,
            key="dfo_role",
            value="tracking-sheet",
        ),
    )
    assert files == [
        google.DriveFile(id="sheet1", name="DFO docs tracker", properties={})
    ]


def test_set_properties_patches_metadata() -> None:
    script = [
        Expect(
            "PATCH",
            f"{google.DRIVE_FILES}/sheet1",
            params={**ALL_DRIVES, "fields": "id"},
            json={"properties": {"dfo_role": "tracking-sheet"}},
            reply={"id": "sheet1"},
        )
    ]
    run(
        script,
        lambda s: google.set_properties(s, "sheet1", {"dfo_role": "tracking-sheet"}),
    )


def test_trash_file() -> None:
    script = [
        Expect(
            "PATCH",
            f"{google.DRIVE_FILES}/doc1",
            params={**ALL_DRIVES, "fields": "id"},
            json={"trashed": True},
            reply={"id": "doc1"},
        )
    ]
    run(script, lambda s: google.trash_file(s, "doc1"))


def test_tab_titles() -> None:
    script = [
        Expect(
            "GET",
            f"{google.SHEETS}/sheet1",
            params={"fields": "sheets.properties.title"},
            reply={
                "sheets": [
                    {"properties": {"title": "Pages"}},
                    {"properties": {"title": "How to edit"}},
                ]
            },
        )
    ]
    assert run(script, lambda s: google.tab_titles(s, "sheet1")) == [
        "Pages",
        "How to edit",
    ]


def test_doc_revision_id() -> None:
    script = [
        Expect(
            "GET",
            f"{google.DOCS_DOCUMENTS}/doc1",
            params={"fields": "revisionId"},
            reply={"revisionId": "ALm37BW"},
        )
    ]
    assert run(script, lambda s: google.doc_revision_id(s, "doc1")) == "ALm37BW"


# Settled export


def test_export_settled_returns_once_two_exports_agree(sleeps: list[float]) -> None:
    script = [
        export_expect(text="Use search.\n"),
        export_expect(text="Use `search`.\n"),
        export_expect(text="Use `search`.\n"),
    ]
    assert run(script, lambda s: google.export_settled(s, "doc1")) == (
        "Use `search`.\n"
    )
    assert sleeps == [2.0, 4.0]


def test_export_settled_takes_two_exports_when_stable(sleeps: list[float]) -> None:
    script = [export_expect(text="# Same\n"), export_expect(text="# Same\n")]
    assert run(script, lambda s: google.export_settled(s, "doc1")) == "# Same\n"
    assert sleeps == [2.0]


def test_export_settled_refuses_exports_that_never_agree(
    sleeps: list[float],
) -> None:
    session, transport = session_for(
        [export_expect(text=f"version {number}\n") for number in range(6)]
    )
    with pytest.raises(google.ExportNotSettledError, match="doc1") as caught:
        google.export_settled(session, "doc1")
    assert caught.value.file_id == "doc1"
    assert isinstance(caught.value, google.GoogleStateError)
    assert transport.script == []
    assert sleeps == [2.0, 4.0, 8.0, 16.0, 32.0]


# Retried creates


DOC_PROPERTIES = {"dfo_page_id": "hub/get-data"}
DOC_LOOKUP = (
    "'hub' in parents and mimeType = 'application/vnd.google-apps.document'"
    " and trashed = false"
    " and properties has { key='dfo_page_id' and value='hub/get-data' }"
)
UPLOAD_PARAMS = {**ALL_DRIVES, "uploadType": "multipart", "fields": "id"}


def drive_id_expect(file_id: str) -> Expect:
    return Expect(
        "GET",
        f"{google.DRIVE_FILES}/{file_id}",
        params={**ALL_DRIVES, "fields": "id,driveId"},
        reply={"id": file_id, "driveId": DRIVE},
    )


def create_get_data_doc(session: requests.Session) -> str:
    return google.create_doc(
        session,
        name="Get data",
        markdown="# Get data\n",
        parent_id="hub",
        properties=DOC_PROPERTIES,
    )


def test_retried_create_doc_adopts_the_doc_the_failed_attempt_made() -> None:
    script = [
        Expect("POST", google.DRIVE_UPLOAD, params=UPLOAD_PARAMS, status=500),
        drive_id_expect("hub"),
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": DOC_LOOKUP},
            reply={
                "files": [
                    {"id": "doc1", "name": "Get data", "properties": DOC_PROPERTIES}
                ]
            },
        ),
    ]
    assert run(script, create_get_data_doc) == "doc1"


def test_retried_create_doc_creates_when_nothing_was_made() -> None:
    script = [
        Expect(
            "POST",
            google.DRIVE_UPLOAD,
            params=UPLOAD_PARAMS,
            raises=requests.ReadTimeout("read timed out"),
        ),
        drive_id_expect("hub"),
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": DOC_LOOKUP},
            reply={"files": []},
        ),
        Expect("POST", google.DRIVE_UPLOAD, params=UPLOAD_PARAMS, reply={"id": "doc2"}),
    ]
    assert run(script, create_get_data_doc) == "doc2"


def test_retried_create_doc_refuses_two_matching_docs() -> None:
    session, _ = session_for(
        [
            Expect("POST", google.DRIVE_UPLOAD, params=UPLOAD_PARAMS, status=503),
            drive_id_expect("hub"),
            Expect(
                "GET",
                google.DRIVE_FILES,
                params={**LISTING, "q": DOC_LOOKUP},
                reply={
                    "files": [
                        {"id": "doc1", "name": "Get data"},
                        {"id": "doc2", "name": "Get data"},
                    ]
                },
            ),
        ]
    )
    with pytest.raises(google.GoogleStateError, match="doc1, doc2"):
        create_get_data_doc(session)


def test_create_doc_is_not_retried_on_a_final_error() -> None:
    session, transport = session_for(
        [Expect("POST", google.DRIVE_UPLOAD, params=UPLOAD_PARAMS, status=403)]
    )
    with pytest.raises(google.GoogleApiError):
        create_get_data_doc(session)
    assert transport.script == []


def test_retried_folder_create_looks_up_by_name_in_the_known_drive() -> None:
    folder = {
        "name": "Hub",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": ["dfo"],
    }
    script = [
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={**LISTING, "q": folder_query("dfo", "Hub")},
            reply={"files": []},
        ),
        Expect(
            "POST",
            google.DRIVE_FILES,
            params={**ALL_DRIVES, "fields": "id"},
            json=folder,
            status=502,
        ),
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={
                **LISTING,
                "q": (
                    "'dfo' in parents"
                    " and mimeType = 'application/vnd.google-apps.folder'"
                    " and trashed = false and name = 'Hub'"
                ),
            },
            reply={"files": [{"id": "hub", "name": "Hub"}]},
        ),
    ]
    result = run(
        script,
        lambda s: google.ensure_folder_path(
            s, drive_id=DRIVE, parent_id="dfo", names=["Hub"]
        ),
    )
    assert result == "hub"


def test_create_sheet_sets_properties_in_the_create_request() -> None:
    sheet = {
        "name": "DFO docs tracker",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": ["dfo"],
        "properties": {"dfo_role": "tracker"},
    }
    script = [
        Expect(
            "POST",
            google.DRIVE_FILES,
            params={**ALL_DRIVES, "fields": "id"},
            json=sheet,
            raises=requests.ConnectionError("reset"),
        ),
        drive_id_expect("dfo"),
        Expect(
            "GET",
            google.DRIVE_FILES,
            params={
                **LISTING,
                "q": (
                    "'dfo' in parents"
                    " and mimeType = 'application/vnd.google-apps.spreadsheet'"
                    " and trashed = false"
                    " and properties has { key='dfo_role' and value='tracker' }"
                ),
            },
            reply={"files": [{"id": "sheet1", "name": "DFO docs tracker"}]},
        ),
        Expect(
            "GET",
            f"{google.SHEETS}/sheet1",
            params={"fields": "sheets.properties.sheetId"},
            reply={"sheets": [{"properties": {"sheetId": 0}}]},
        ),
        Expect("POST", f"{google.SHEETS}/sheet1:batchUpdate"),
    ]
    result = run(
        script,
        lambda s: google.create_sheet(
            s,
            name="DFO docs tracker",
            parent_id="dfo",
            tab="Pages",
            columns=COLUMNS,
            validations={},
            properties={"dfo_role": "tracker"},
        ),
    )
    assert result == "sheet1"
