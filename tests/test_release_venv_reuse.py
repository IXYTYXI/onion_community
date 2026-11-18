from pathlib import Path
import sys

from scripts.release_venv_reuse import can_reuse


def release(root: Path) -> Path:
    (root / "packages/deploy-engine/src").mkdir(parents=True)
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").symlink_to(sys.executable)
    (root / ".venv/pyvenv.cfg").write_text(
        f"home = /usr/bin\nversion_info = {sys.version_info.major}.{sys.version_info.minor}.0\n"
    )
    (root / "uv.lock").write_text("lock-v1")
    (root / "pyproject.toml").write_text("project-v1")
    (root / "packages/deploy-engine/pyproject.toml").write_text("engine-v1")
    (root / "packages/deploy-engine/src/engine.py").write_text("code-v1")
    return root


def test_reuses_environment_for_application_code_only(tmp_path: Path) -> None:
    previous = release(tmp_path / "previous")
    candidate = release(tmp_path / "candidate")
    (candidate / "app.py").write_text("new business logic")
    assert can_reuse(previous, candidate)


def test_ignores_generated_package_build_files(tmp_path: Path) -> None:
    previous = release(tmp_path / "previous")
    candidate = release(tmp_path / "candidate")
    build = previous / "packages/deploy-engine/build/lib"
    build.mkdir(parents=True)
    (build / "engine.py").write_text("generated copy")
    assert can_reuse(previous, candidate)


def test_rebuilds_environment_when_lock_changes(tmp_path: Path) -> None:
    previous = release(tmp_path / "previous")
    candidate = release(tmp_path / "candidate")
    (candidate / "uv.lock").write_text("lock-v2")
    assert not can_reuse(previous, candidate)


def test_rebuilds_environment_when_local_package_changes(tmp_path: Path) -> None:
    previous = release(tmp_path / "previous")
    candidate = release(tmp_path / "candidate")
    (candidate / "packages/deploy-engine/src/engine.py").write_text("code-v2")
    assert not can_reuse(previous, candidate)


def test_rebuilds_environment_when_project_metadata_changes(tmp_path: Path) -> None:
    previous = release(tmp_path / "previous")
    candidate = release(tmp_path / "candidate")
    (candidate / "pyproject.toml").write_text("project-v2")
    assert not can_reuse(previous, candidate)


def test_rebuilds_environment_for_different_python_version(tmp_path: Path) -> None:
    previous = release(tmp_path / "previous")
    candidate = release(tmp_path / "candidate")
    (previous / ".venv/pyvenv.cfg").write_text("version = 3.99.0\n")
    assert not can_reuse(previous, candidate)


def test_rebuilds_environment_without_usable_previous_venv(tmp_path: Path) -> None:
    previous = release(tmp_path / "previous")
    candidate = release(tmp_path / "candidate")
    (previous / ".venv/bin/python").unlink()
    assert not can_reuse(previous, candidate)
