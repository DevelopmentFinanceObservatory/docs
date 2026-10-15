"""Tests for dfo_docs.docsync.state: the page state files and the stores holding them.

Branch-store remotes are local bare repositories, so nothing reaches the network.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from dfo_docs.docsync.state import (
    BranchStateStore,
    DirStateStore,
    PageState,
    StateConflictError,
    StateError,
    StateFormatError,
    StateRemoteError,
    parse_state,
    render_state,
    state_from_json,
)

BRANCH = "docsync-state"

GUIDE = PageState(
    page_id="hub/guide/index",
    doc_id="doc-guide",
    repo="DevelopmentFinanceObservatory/docs",
    ref="main",
    path="docs/guide/index.md",
    source_commit="a" * 40,
    baseline="# Guide\n\nIntro.\n",
)
API = PageState(
    page_id="apis/use",
    doc_id="doc-api",
    repo="DevelopmentFinanceObservatory/apis",
    ref="main",
    path="docs/use.md",
    source_commit="b" * 40,
    baseline="# Use\n",
    applied_export="# Use\n\nFirst edit.\n",
    pulled_export="# Use\n\nEdited.\n",
    pr_url="https://github.com/DevelopmentFinanceObservatory/apis/pull/7",
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _identity(clone: Path) -> None:
    _git(clone, "config", "user.name", "Docsync Test")
    _git(clone, "config", "user.email", "docsync@example.org")


def _commits(bare: Path) -> int:
    return int(_git(bare, "rev-list", "--count", BRANCH))


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare remote with a `main` branch and no state branch."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(bare), str(seed))
    _identity(seed)
    (seed / "README.md").write_text("# dfo-docs\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", "origin", "main")
    return bare


@pytest.fixture
def clone(tmp_path: Path, remote: Path) -> Path:
    path = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(remote), str(path))
    _identity(path)
    return path


def _store(clone: Path) -> BranchStateStore:
    return BranchStateStore(repo_root=clone)


def test_render_is_stable_json() -> None:
    text = render_state(API)

    assert text.endswith("}\n")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2) + "\n"
    assert list(json.loads(text)) == sorted(json.loads(text))


def test_dir_store_round_trip_writes_nested_files(tmp_path: Path) -> None:
    store = DirStateStore(tmp_path)

    store.save({GUIDE.page_id: GUIDE, API.page_id: API}, message="push")

    file = tmp_path / "state" / "hub" / "guide" / "index.json"
    assert file.read_text() == render_state(GUIDE)
    assert store.load() == {GUIDE.page_id: GUIDE, API.page_id: API}


def test_dir_store_missing_directory_is_empty(tmp_path: Path) -> None:
    assert DirStateStore(tmp_path / "absent").load() == {}


def test_dir_store_save_removes_absent_pages_and_empty_directories(
    tmp_path: Path,
) -> None:
    store = DirStateStore(tmp_path)
    store.save({GUIDE.page_id: GUIDE, API.page_id: API}, message="push")

    store.save({API.page_id: API}, message="drop guide")

    assert store.load() == {API.page_id: API}
    assert not (tmp_path / "state" / "hub").exists()


def test_save_rejects_key_that_disagrees_with_page_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="page_id"):
        DirStateStore(tmp_path).save({"other": GUIDE}, message="push")


@pytest.mark.parametrize("page_id", ["", "../escape", "a//b", "/abs", "a/./b"])
def test_save_rejects_unusable_page_id(tmp_path: Path, page_id: str) -> None:
    state = dataclasses.replace(GUIDE, page_id=page_id)

    with pytest.raises(ValueError, match="page id"):
        DirStateStore(tmp_path).save({page_id: state}, message="push")


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("{not json", "invalid JSON"),
        ("[]", "expected a JSON object"),
        (
            json.dumps({**json.loads(render_state(GUIDE)), "extra": "x"}),
            "unknown fields: extra",
        ),
        (
            json.dumps(
                {
                    k: v
                    for k, v in json.loads(render_state(GUIDE)).items()
                    if k != "doc_id"
                }
            ),
            "missing fields: doc_id",
        ),
        (
            json.dumps({**json.loads(render_state(GUIDE)), "baseline": None}),
            "baseline must be a string",
        ),
        (
            json.dumps({**json.loads(render_state(GUIDE)), "pr_url": 7}),
            "pr_url must be a string or null",
        ),
        (
            json.dumps({**json.loads(render_state(GUIDE)), "page_id": "hub/other"}),
            "disagrees with its path",
        ),
    ],
)
def test_dir_store_load_names_the_malformed_file(
    tmp_path: Path, text: str, reason: str
) -> None:
    file = tmp_path / "state" / "hub" / "guide" / "index.json"
    file.parent.mkdir(parents=True)
    file.write_text(text)

    with pytest.raises(StateFormatError, match=reason) as caught:
        DirStateStore(tmp_path).load()

    assert caught.value.file == str(file)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"proposed_head": "c" * 40}, "unknown fields: proposed_head"),
        ({"applied_export": None}, "missing fields: applied_export"),
    ],
)
def test_state_from_json_takes_exactly_the_page_state_fields(
    change: dict[str, object], reason: str
) -> None:
    data = json.loads(render_state(API))
    for name, value in change.items():
        if value is None:
            del data[name]
        else:
            data[name] = value

    with pytest.raises(StateFormatError, match=reason):
        parse_state(json.dumps(data), file="old.json", page_id=API.page_id)


def test_state_from_json_rejects_an_unusable_page_id() -> None:
    data = {**json.loads(render_state(GUIDE)), "page_id": "../escape"}

    with pytest.raises(StateFormatError, match="not a usable page id"):
        state_from_json(data, file="unsaved.json", page_id="../escape")


def test_dir_store_load_rejects_non_json_file(tmp_path: Path) -> None:
    stray = tmp_path / "state" / "notes.txt"
    stray.parent.mkdir(parents=True)
    stray.write_text("hi\n")

    with pytest.raises(StateFormatError, match=r"not a \.json file"):
        DirStateStore(tmp_path).load()


def test_branch_store_missing_branch_is_empty(clone: Path) -> None:
    assert _store(clone).load() == {}


def test_branch_store_unreachable_remote_raises(clone: Path, tmp_path: Path) -> None:
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    with pytest.raises(StateRemoteError, match="cannot read docsync-state"):
        _store(clone).load()
    with pytest.raises(StateRemoteError):
        _store(clone).save({GUIDE.page_id: GUIDE}, message="push")


def test_branch_store_round_trip_creates_orphan_branch(
    clone: Path, remote: Path
) -> None:
    _store(clone).save({GUIDE.page_id: GUIDE, API.page_id: API}, message="push run")

    assert _commits(remote) == 1
    assert _git(remote, "log", "-1", "--format=%s", BRANCH) == "push run"
    assert _git(remote, "log", "-1", "--format=%P", BRANCH) == ""
    assert _git(remote, "ls-tree", "-r", "--name-only", BRANCH).split() == [
        "state/apis/use.json",
        "state/hub/guide/index.json",
    ]
    assert _git(remote, "show", f"{BRANCH}:state/apis/use.json") + "\n" == (
        render_state(API)
    )
    assert _store(clone).load() == {GUIDE.page_id: GUIDE, API.page_id: API}


def test_branch_store_reads_existing_branch_from_another_clone(
    clone: Path, remote: Path, tmp_path: Path
) -> None:
    _store(clone).save({GUIDE.page_id: GUIDE}, message="push")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(remote), str(other))

    assert BranchStateStore(repo_root=other).load() == {GUIDE.page_id: GUIDE}


def test_branch_store_save_removes_absent_pages(clone: Path, remote: Path) -> None:
    store = _store(clone)
    store.save({GUIDE.page_id: GUIDE, API.page_id: API}, message="push")

    store.save({API.page_id: API}, message="drop guide")

    assert _commits(remote) == 2
    assert store.load() == {API.page_id: API}
    assert _git(remote, "ls-tree", "-r", "--name-only", BRANCH) == (
        "state/apis/use.json"
    )


def test_branch_store_unchanged_save_makes_no_commit(clone: Path, remote: Path) -> None:
    store = _store(clone)
    store.save({GUIDE.page_id: GUIDE}, message="push")
    tip = _git(remote, "rev-parse", BRANCH)

    store.save({GUIDE.page_id: GUIDE}, message="push again")

    assert _git(remote, "rev-parse", BRANCH) == tip


def test_branch_store_empty_save_on_missing_branch_creates_nothing(
    clone: Path, remote: Path
) -> None:
    _store(clone).save({}, message="push")

    assert _git(remote, "branch", "--list", BRANCH) == ""


def test_branch_store_updated_page_commits_on_top(clone: Path, remote: Path) -> None:
    store = _store(clone)
    store.save({API.page_id: API}, message="push")
    first = _git(remote, "rev-parse", BRANCH)
    edited = dataclasses.replace(API, pr_url=None, pulled_export=None)

    store.save({API.page_id: edited}, message="re-push")

    assert _git(remote, "rev-parse", f"{BRANCH}^") == first
    assert store.load() == {API.page_id: edited}


def test_branch_store_names_malformed_file(
    clone: Path, remote: Path, tmp_path: Path
) -> None:
    _store(clone).save({GUIDE.page_id: GUIDE}, message="push")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", "-b", BRANCH, str(remote), str(work))
    _identity(work)
    (work / "state" / "hub" / "guide" / "index.json").write_text("{}")
    _git(work, "commit", "-q", "-am", "break")
    _git(work, "push", "-q", "origin", BRANCH)

    with pytest.raises(StateFormatError, match="missing fields") as caught:
        _store(clone).load()

    assert caught.value.file == f"{BRANCH}:state/hub/guide/index.json"


def test_branch_store_leaves_working_tree_index_and_head_alone(clone: Path) -> None:
    (clone / "README.md").write_text("# local edit\n")
    (clone / "staged.md").write_text("staged\n")
    _git(clone, "add", "staged.md")
    before = (
        _git(clone, "status", "--porcelain"),
        _git(clone, "rev-parse", "HEAD"),
        _git(clone, "symbolic-ref", "HEAD"),
        _git(clone, "diff", "--cached"),
    )

    store = _store(clone)
    store.save({GUIDE.page_id: GUIDE}, message="push")
    store.load()

    after = (
        _git(clone, "status", "--porcelain"),
        _git(clone, "rev-parse", "HEAD"),
        _git(clone, "symbolic-ref", "HEAD"),
        _git(clone, "diff", "--cached"),
    )
    assert after == before
    assert not (clone / "state").exists()


def test_branch_store_pushes_with_a_token(clone: Path, remote: Path) -> None:
    BranchStateStore(repo_root=clone, token="ghs_test").save(
        {GUIDE.page_id: GUIDE}, message="push"
    )

    assert _commits(remote) == 1
    assert "ghs_test" not in (clone / ".git" / "config").read_text()


def _second_clone(remote: Path, tmp_path: Path) -> Path:
    path = tmp_path / "second"
    _git(tmp_path, "clone", "-q", str(remote), str(path))
    _identity(path)
    return path


def test_branch_store_save_refuses_when_another_run_saved_since_load(
    clone: Path, remote: Path, tmp_path: Path
) -> None:
    """Run 1 loads, run 2 records a PR, then run 1 saves its stale map."""
    one, two = _store(clone), _store(_second_clone(remote, tmp_path))
    one.save({"x/a": dataclasses.replace(GUIDE, page_id="x/a")}, message="seed")
    stale = one.load()
    current = two.load()
    two.save(
        {"x/a": dataclasses.replace(current["x/a"], pr_url="https://example/pull/7")},
        message="pull",
    )
    tip = _git(remote, "rev-parse", BRANCH)
    loaded = one.tip()

    with pytest.raises(StateConflictError, match="moved since it was loaded"):
        one.save(
            {**stale, "x/b": dataclasses.replace(API, page_id="x/b")}, message="push"
        )

    assert _git(remote, "rev-parse", BRANCH) == tip
    assert one.tip() == loaded != tip
    assert one.load()["x/a"].pr_url == "https://example/pull/7"


def test_branch_store_save_refuses_when_a_missing_branch_was_created(
    clone: Path, remote: Path, tmp_path: Path
) -> None:
    one, two = _store(clone), _store(_second_clone(remote, tmp_path))
    assert one.load() == {}
    two.save({API.page_id: API}, message="first")

    with pytest.raises(StateConflictError):
        one.save({GUIDE.page_id: GUIDE}, message="second")

    assert _store(clone).load() == {API.page_id: API}


def test_branch_store_saves_again_after_its_own_save(clone: Path, remote: Path) -> None:
    store = _store(clone)
    store.load()
    store.save({GUIDE.page_id: GUIDE}, message="one")
    store.save({GUIDE.page_id: GUIDE, API.page_id: API}, message="two")

    assert _commits(remote) == 2
    assert store.load() == {GUIDE.page_id: GUIDE, API.page_id: API}


def test_branch_store_save_without_load_builds_on_the_remote_tip(
    clone: Path, remote: Path, tmp_path: Path
) -> None:
    _store(_second_clone(remote, tmp_path)).save({GUIDE.page_id: GUIDE}, message="one")

    _store(clone).save({GUIDE.page_id: GUIDE, API.page_id: API}, message="two")

    assert _commits(remote) == 2


def test_dir_store_tip_follows_the_files_loaded_or_saved(tmp_path: Path) -> None:
    store = DirStateStore(tmp_path)
    assert store.load() == {}
    assert store.tip() is None

    store.save({GUIDE.page_id: GUIDE}, message="push")
    saved = store.tip()
    other = DirStateStore(tmp_path)
    other.load()
    assert saved is not None
    assert other.tip() == saved

    other.save({GUIDE.page_id: GUIDE, API.page_id: API}, message="push")
    store.load()
    assert store.tip() == other.tip() != saved


def test_branch_store_tip_is_the_commit_loaded_or_saved(
    clone: Path, remote: Path
) -> None:
    store = _store(clone)
    with pytest.raises(StateError, match="before load"):
        store.tip()
    store.load()
    assert store.tip() is None

    store.save({GUIDE.page_id: GUIDE}, message="push")
    assert store.tip() == _git(remote, "rev-parse", BRANCH)

    store.save({API.page_id: API}, message="push")
    assert store.tip() == _git(remote, "rev-parse", BRANCH)
