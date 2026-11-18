"""Decide whether a staged release can use the active release's virtualenv."""

from pathlib import Path
import os
import re
import sys


DEPENDENCY_FILES = ("uv.lock", "pyproject.toml")
LOCAL_PACKAGE = "packages/deploy-engine"


def _files(root: Path) -> dict[str, bytes] | None:
    result: dict[str, bytes] = {}
    for relative in DEPENDENCY_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            return None
        result[relative] = path.read_bytes()
    package = root / LOCAL_PACKAGE
    if not package.is_dir() or package.is_symlink():
        return None
    for path in package.rglob("*"):
        relative_parts = path.relative_to(package).parts
        if relative_parts[0] == "build" or "__pycache__" in relative_parts:
            continue
        if path.is_symlink():
            return None
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def can_reuse(previous: Path, candidate: Path) -> bool:
    venv = previous / ".venv"
    python = venv / "bin/python"
    config = venv / "pyvenv.cfg"
    if not (config.is_file() and python.is_file() and os.access(python, os.X_OK)):
        return False
    try:
        version = re.search(r"(?m)^version(?:_info)?\s*=\s*(\d+)\.(\d+)", config.read_text())
    except OSError:
        return False
    if version is None or tuple(map(int, version.groups())) != sys.version_info[:2]:
        return False
    old_files = _files(previous)
    return old_files is not None and old_files == _files(candidate)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: release_venv_reuse.py PREVIOUS CANDIDATE")
    raise SystemExit(0 if can_reuse(Path(sys.argv[1]), Path(sys.argv[2])) else 1)
