"""Repository import, path policy, exact edits, and deterministic diffs."""

import ast
import difflib
import io
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .domain import PolicyError

MAX_FILE = 100_000
MAX_REPOSITORY = 2_000_000
MAX_FILES = 150
SUFFIXES = {".py", ".md", ".txt", ".toml", ".json", ".cfg", ".ini"}


def safe_path(root: Path, relative: str) -> Path:
    p = PurePosixPath(relative)
    if not relative or "\\" in relative or p.is_absolute() or ".." in p.parts:
        raise PolicyError("Expected a repository-relative path without traversal.")
    if any(part.startswith(".") or part in {"__pycache__", "node_modules"} for part in p.parts):
        raise PolicyError("Hidden files, secrets, and generated directories are inaccessible.")
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise PolicyError("Symbolic links are forbidden.")
    if not current.resolve().is_relative_to(root.resolve()):
        raise PolicyError("Path escapes workspace.")
    if current.suffix not in SUFFIXES:
        raise PolicyError("Unsupported file type.")
    if any(word in current.name.lower() for word in ("secret", "credential", "private_key")):
        raise PolicyError("Potential secret file is inaccessible.")
    return current


def import_zip(payload: bytes, root: Path):
    if len(payload) > MAX_REPOSITORY:
        raise PolicyError("Archive exceeds 2 MB.")
    pending = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if len(archive.infolist()) > MAX_FILES:
                raise PolicyError("Archive exceeds 150 entries.")
            names = set()
            for entry in archive.infolist():
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise PolicyError("Symlinks and encrypted archives are forbidden.")
                if entry.is_dir():
                    continue
                path = safe_path(root, entry.filename)
                if entry.filename in names:
                    raise PolicyError("Duplicate archive path.")
                names.add(entry.filename)
                total += entry.file_size
                if entry.file_size > MAX_FILE or total > MAX_REPOSITORY:
                    raise PolicyError("Expanded repository exceeds size limits.")
                content = archive.read(entry).decode("utf-8")
                pending.append((path, content))
    except (zipfile.BadZipFile, UnicodeDecodeError, RuntimeError) as exc:
        raise PolicyError("Expected an unencrypted UTF-8 source ZIP.") from exc
    if not any(path.relative_to(root).parts[0] == "src" for path, _ in pending):
        raise PolicyError("ZIP must have src/ and tests/ at its root.")
    if not any(path.relative_to(root).parts[0] == "tests" for path, _ in pending):
        raise PolicyError("Repository needs protected acceptance tests in tests/.")
    for path, content in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class Workspace:
    def __init__(self, root: Path):
        self.root = root
        self.read_paths = set()
        self.modified = set()

    def files(self):
        result = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(self.root).as_posix()
                try:
                    safe_path(self.root, relative)
                except PolicyError:
                    continue
                result.append(relative)
        return result

    def read(self, relative, mark=True):
        path = safe_path(self.root, relative)
        if path.stat().st_size > MAX_FILE:
            raise PolicyError("File exceeds 100 KB.")
        text = path.read_text(encoding="utf-8")
        if mark:
            self.read_paths.add(relative)
        return text

    def search(self, query):
        if not query or len(query) > 120:
            raise PolicyError("Search query must be between 1 and 120 characters.")
        hits = []
        for path in self.files():
            for number, line in enumerate(self.read(path, mark=False).splitlines(), 1):
                if query.casefold() in line.casefold():
                    hits.append(dict(path=path, line=number, text=line[:300]))
                    if len(hits) >= 40:
                        return hits
        return hits

    def edit(self, relative, old, new):
        path = safe_path(self.root, relative)
        if not relative.startswith("src/") or path.suffix != ".py":
            raise PolicyError("Only Python files under src/ can be edited; tests stay immutable.")
        if relative not in self.read_paths:
            raise PolicyError("Read the file before editing it.")
        text = self.read(relative)
        if not old or text.count(old) != 1:
            raise PolicyError("Old text must match exactly once; refresh the file before retrying.")
        replacement = text.replace(old, new, 1)
        if len(replacement.encode()) > MAX_FILE:
            raise PolicyError("Edited file exceeds 100 KB.")
        if len(self.modified | {relative}) > 5:
            raise PolicyError("A run may change at most five source files.")
        try:
            ast.parse(replacement)
        except SyntaxError as exc:
            raise PolicyError(f"Replacement is invalid Python: {exc.msg}") from exc
        path.write_text(replacement, encoding="utf-8")
        self.modified.add(relative)
        return {"path": relative, "result": "edited"}

    def diff(self, original: Path):
        patches, changed = [], []
        for relative in self.files():
            before = (original / relative).read_text(encoding="utf-8")
            after = (self.root / relative).read_text(encoding="utf-8")
            if before != after:
                if not before.endswith("\n") or not after.endswith("\n"):
                    raise PolicyError("Changed files must end with a newline for portable patches.")
                changed.append(relative)
                patches.extend(
                    difflib.unified_diff(
                        before.splitlines(keepends=True),
                        after.splitlines(keepends=True),
                        fromfile=f"a/{relative}",
                        tofile=f"b/{relative}",
                    )
                )
        return "".join(patches), changed
