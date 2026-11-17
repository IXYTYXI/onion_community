"""Build and validate a source release without copying local credentials or state."""

import argparse
from gzip import GzipFile
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import subprocess
from tarfile import TarInfo, open as open_tar


REQUIRED = {
    "source/.release-commit",
    "source/app/main.py",
    "source/uv.lock",
    "source/frontend/dist/index.html",
    "source/frontend/dist/deploy.html",
}
MAX_UNPACKED_BYTES = 512 * 1024 * 1024


def _commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("commit must be a 40-character lowercase SHA")
    return value


def _files(root: Path):
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    names = {Path(raw.decode()) for raw in tracked if raw}
    build = root / "frontend/dist"
    if not (build / "index.html").is_file() or not (build / "deploy.html").is_file():
        raise ValueError("frontend/dist is incomplete; build it before packaging")
    names.update(path.relative_to(root) for path in build.rglob("*") if path.is_file())
    for name in sorted(names):
        if (name.is_absolute() or ".." in name.parts
                or (name.name.startswith(".env") and name.name != ".env.example")):
            raise ValueError(f"unsafe release path: {name}")
        source = root / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"release input is not a regular file: {name}")
        yield name, source


def package_release(root: Path, archive: Path, commit: str) -> None:
    root = root.resolve()
    commit = _commit(commit)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as output, GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as gz:
        with open_tar(fileobj=gz, mode="w") as tar:
            for name, source in _files(root):
                data = source.read_bytes()
                info = TarInfo("source/" + name.as_posix())
                info.size = len(data)
                info.mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
                info.mtime = 0
                tar.addfile(info, BytesIO(data))
            marker = TarInfo("source/.release-commit")
            marker.size = len(commit)
            marker.mode = 0o644
            marker.mtime = 0
            tar.addfile(marker, BytesIO(commit.encode()))


def verify_release(archive: Path, digest: str, commit: str) -> None:
    commit = _commit(commit)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("digest must be a SHA-256 hex string")
    hasher = sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError("release SHA-256 mismatch")
    names = set()
    total = 0
    with open_tar(archive, "r:gz") as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "source"
                    or ".." in path.parts or not member.isfile() or member.name in names):
                raise ValueError(f"unsafe archive member: {member.name}")
            names.add(member.name)
            total += member.size
            if member.size > MAX_UNPACKED_BYTES or total > MAX_UNPACKED_BYTES:
                raise ValueError("release exceeds unpacked size limit")
        if not REQUIRED <= names:
            raise ValueError(f"release missing required files: {sorted(REQUIRED - names)}")
        marker = tar.extractfile("source/.release-commit")
        if marker is None or marker.read().decode() != commit:
            raise ValueError("release commit mismatch")


def extract_release(archive: Path, digest: str, commit: str, destination: Path) -> None:
    verify_release(archive, digest, commit)
    destination.mkdir(parents=True, exist_ok=True)
    with open_tar(archive, "r:gz") as tar:
        tar.extractall(destination, filter="data")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--commit", required=True)
    for command in ("verify", "extract"):
        check = sub.add_parser(command)
        check.add_argument("--archive", type=Path, required=True)
        check.add_argument("--digest", required=True)
        check.add_argument("--commit", required=True)
        if command == "extract":
            check.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        package_release(args.root, args.archive, args.commit)
    elif args.command == "verify":
        verify_release(args.archive, args.digest, args.commit)
    else:
        extract_release(args.archive, args.digest, args.commit, args.destination)


if __name__ == "__main__":
    main()
