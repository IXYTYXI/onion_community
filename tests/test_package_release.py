"""Release archives include committed code and built assets, never local secrets."""

from hashlib import sha256
from pathlib import Path
from subprocess import run
from tarfile import TarInfo, open as open_tar

import pytest

from scripts.package_release import package_release, verify_release


COMMIT = "a" * 40


def test_package_contains_tracked_source_and_build_but_no_local_state(tmp_path):
    run(["git", "init", "-q", str(tmp_path)], check=True)
    for name in ("app/main.py", "uv.lock", ".env.example", "frontend/dist/index.html", "frontend/dist/deploy.html"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    (tmp_path / ".env").write_text("SECRET=do-not-package")
    (tmp_path / "app/main.py").write_text("committed version")
    run(["git", "-C", str(tmp_path), "add", "app/main.py", "uv.lock", ".env.example"], check=True)
    archive = tmp_path / "release.tar.gz"

    package_release(tmp_path, archive, COMMIT)

    digest = sha256(archive.read_bytes()).hexdigest()
    verify_release(archive, digest, COMMIT)
    with open_tar(archive, "r:gz") as tar:
        names = set(tar.getnames())
        assert "source/app/main.py" in names
        assert "source/.env.example" in names
        assert "source/frontend/dist/index.html" in names
        assert "source/frontend/dist/deploy.html" in names
        assert "source/.env" not in names
        assert "source/.git" not in names
        assert tar.extractfile("source/app/main.py").read() == b"committed version"


def test_verify_rejects_path_escape(tmp_path):
    archive = tmp_path / "release.tar.gz"
    with open_tar(archive, "w:gz") as tar:
        info = TarInfo("source/../../escape")
        info.size = 1
        from io import BytesIO
        tar.addfile(info, BytesIO(b"x"))

    with pytest.raises(ValueError, match="unsafe archive member"):
        verify_release(archive, sha256(archive.read_bytes()).hexdigest(), COMMIT)
