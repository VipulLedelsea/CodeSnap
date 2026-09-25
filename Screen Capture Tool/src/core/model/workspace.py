import os
import re
from pathlib import Path

DEFAULT_ROOT = Path.home() / "CodeSnap" / "programs"


def programs_root(root=None) -> Path:
    path = Path(root or os.environ.get("CODESNAP_PROGRAMS") or DEFAULT_ROOT).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (name or "").strip()).strip("-").lower()
    return slug or "program"


def unique_dir(root: Path, slug: str) -> Path:
    candidate, i = root / slug, 2
    while candidate.exists():
        candidate, i = root / f"{slug}-{i}", i + 1
    return candidate


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("._") or "file"
