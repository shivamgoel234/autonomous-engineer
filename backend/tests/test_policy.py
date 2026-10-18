import io
import stat
import zipfile

import pytest
from ase.domain import PolicyError
from ase.workspace import Workspace, import_zip, safe_path


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/etc/passwd",
        "src/../../outside.py",
        "src\\outside.py",
        ".env",
        ".git/config",
        "src/secret.py",
        "src/__pycache__/code.py",
        "src/file.exe",
    ],
)
def test_forbidden_paths_are_rejected(tmp_path, path):
    with pytest.raises(PolicyError):
        safe_path(tmp_path, path)


def test_symlink_cannot_escape_workspace(tmp_path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("private")
    (tmp_path / "src").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(PolicyError):
        safe_path(tmp_path, "src/outside.py")


def repository(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src/code.py").write_text("value = 1\n")
    (tmp_path / "tests/test_code.py").write_text("assert True\n")
    return Workspace(tmp_path)


def test_read_before_edit_and_protected_tests(tmp_path):
    workspace = repository(tmp_path)
    with pytest.raises(PolicyError, match="Read"):
        workspace.edit("src/code.py", "1", "2")
    workspace.read("tests/test_code.py")
    with pytest.raises(PolicyError, match="immutable"):
        workspace.edit("tests/test_code.py", "True", "False")
    workspace.read("src/code.py")
    workspace.edit("src/code.py", "1", "2")
    assert workspace.read("src/code.py") == "value = 2\n"


def test_stale_ambiguous_and_invalid_edits_are_rejected(tmp_path):
    workspace = repository(tmp_path)
    workspace.read("src/code.py")
    for old, new in [("missing", "2"), ("", "2"), ("1", "(")]:
        with pytest.raises(PolicyError):
            workspace.edit("src/code.py", old, new)
    assert workspace.read("src/code.py") == "value = 1\n"


def make_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in entries:
            archive.writestr(name, text)
    return buffer.getvalue()


def test_zip_validation_is_atomic_before_writes(tmp_path):
    archive = make_zip([("src/code.py", "ok"), ("../leak.py", "bad")])
    with pytest.raises(PolicyError):
        import_zip(archive, tmp_path)
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "entries",
    [
        [("src/code.py", "x"), ("tests/test_code.py", "x"), ("src/code.py", "duplicate")],
        [("src/code.py", "x" * 100001), ("tests/test_code.py", "x")],
        [("only.py", "x")],
        [("src/code.py", "x"), ("tests/test_code.py", "x"), (".env", "SECRET")],
    ],
)
def test_unsafe_archives_are_rejected(tmp_path, entries):
    with pytest.raises(PolicyError):
        import_zip(make_zip(entries), tmp_path)


def test_zip_symlink_is_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("src/link.py")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside.py")
    with pytest.raises(PolicyError, match="Symlinks"):
        import_zip(buffer.getvalue(), tmp_path)


def test_supported_repository_import_and_search(tmp_path):
    import_zip(
        make_zip(
            [("src/code.py", "value = 1\n"), ("tests/test_code.py", "def test_value(): pass\n")]
        ),
        tmp_path,
    )
    workspace = Workspace(tmp_path)
    hits = workspace.search("VALUE")
    assert {hit["path"] for hit in hits} == {"src/code.py", "tests/test_code.py"}
    assert hits[0]["line"] == 1


def test_search_results_do_not_authorize_source_edit(tmp_path):
    workspace = repository(tmp_path)
    workspace.search("value")
    with pytest.raises(PolicyError, match="Read"):
        workspace.edit("src/code.py", "1", "2")
