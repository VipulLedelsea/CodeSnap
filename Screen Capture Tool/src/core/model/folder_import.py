"""Read a program's source straight from a folder instead of from screenshots.

A file read from disk is exact: nothing was transcribed, so there is no line check, no capture gap and nothing to recapture.
Each file becomes an artifact like a finished capture and is recorded in the program's `exact_sources`, which is how the rest
of the review (quality checks, report wording) knows the text can be relied on as it is.
"""
from pathlib import Path

from core.technology_support import EXTENSIONS
from core.validate import check_code_text

from .ingest import artifact_type_for, ingest_artifact, validation_from_errors

SKIP_DIRS = {".git", ".svn", ".hg", ".idea", ".vscode", "node_modules", "venv", ".venv", "__pycache__", "build", "dist",
             "target", "bin", "obj", ".gradle", ".next", "vendor", "site-packages", ".tox", ".pytest_cache"}
SKIP_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "ico", "svg", "pdf", "zip", "gz", "tar", "jar", "war", "class", "exe",
                   "dll", "so", "dylib", "o", "a", "pyc", "db", "sqlite", "lock", "map", "min", "mp3", "mp4", "mov", "woff",
                   "woff2", "ttf", "eot", "docx", "xlsx", "pptx", "ds_store", "log", "csv"}
MAX_BYTES = 1_000_000
MAX_FILES = 2000


def scan_folder(folder) -> dict:
    """{files: [Path], skipped: {reason: count}} for the source files under the folder, in a stable order."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise ValueError("That folder does not exist.")
    files, skipped = [], {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS or part.startswith(".") for part in relative.parts[:-1]) or path.name.startswith("."):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        ext = path.suffix.lower().lstrip(".")
        if ext in SKIP_EXTENSIONS:
            skip("not source")
        elif path.stat().st_size > MAX_BYTES:
            skip("too large")
        elif path.stat().st_size == 0:
            skip("empty")
        else:
            files.append(path)
    if len(files) > MAX_FILES:
        skip(f"beyond the first {MAX_FILES}")
        files = files[:MAX_FILES]
    return {"root": root, "files": files, "skipped": skipped}


def _read(path: Path):
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError:
            return None


def add_folder_files(store, folder, progress=None) -> dict:
    """Add every readable source file under the folder as a program file. Returns {added, unreadable, skipped, names}."""
    found = scan_folder(folder)
    root = found["root"]
    basenames = {}
    for path in found["files"]:
        basenames[path.name] = basenames.get(path.name, 0) + 1
    exact = dict(store.get_meta("exact_sources") or {})
    names, unreadable = [], []
    for done, path in enumerate(found["files"], 1):
        text = _read(path)
        if text is None or not text.strip():
            unreadable.append(path.name)
            continue
        ext = path.suffix.lower().lstrip(".")
        relative = path.relative_to(root).as_posix()
        name = relative if basenames[path.name] > 1 else path.name   # same file name in two folders: keep the folder
        language = EXTENSIONS.get(ext, "")
        artifact_id = store.add_artifact(name, artifact_type_for({"extension": ext}, True), language, text)
        try:
            result = check_code_text(text, ext)
        except Exception:  # noqa: BLE001
            result = {}
        if result.get("checked"):
            ok, errors = validation_from_errors("" if result.get("ok") else result.get("errors") or "check failed")
            store.set_validation(artifact_id, result.get("tool") or "compiler", ok, errors or "")
        exact[name] = {"path": relative, "from_folder": str(root)}
        names.append(name)
        if progress:
            progress(done, len(found["files"]))
    store.set_meta("exact_sources", exact)
    return {"added": len(names), "unreadable": unreadable, "skipped": found["skipped"], "names": names}


def structure_files(store, client, names, progress=None) -> int:
    """Read the structure of each added file (what it defines and what it calls). Returns how many failed."""
    failed = 0
    for done, name in enumerate(names, 1):
        art = store.current_artifact(name)
        if art:
            try:
                ingest_artifact(store, client, art["id"])
            except Exception:  # noqa: BLE001
                failed += 1
        if progress:
            progress(done, len(names))
    return failed


def is_exact(store, art) -> bool:
    return (art or {}).get("name") in (store.get_meta("exact_sources") or {})
