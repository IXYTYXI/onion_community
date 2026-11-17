import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import check_server


def test_preflight_accepts_shared_vite_entry_and_rejects_missing_assets(tmp_path, monkeypatch):
    build = tmp_path / "frontend/dist"
    (build / ".vite").mkdir(parents=True)
    (build / "assets").mkdir()
    shared = build / "assets/shared.js"
    shared.write_text("export {}")
    (build / ".vite/manifest.json").write_text(json.dumps({
        "_shared.js": {"file": "assets/shared.js"},
        "login.html": {"file": "assets/shared.js", "isEntry": True},
    }))
    for name in (
        "index", "cases", "news", "skills", "services", "deploy",
        "profile", "detail", "officers", "login",
    ):
        (build / f"{name}.html").write_text('<script src="/assets/shared.js"></script>')
    class RedisStub:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ping(self): return True
    monkeypatch.setattr(check_server, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(check_server.Redis, "from_url", lambda *a, **kw: RedisStub())
    settings = SimpleNamespace(
        environment="production", feishu_app_id="test", deploy_enabled=False,
        feishu_app_secret=SimpleNamespace(get_secret_value=lambda: "test"),
        redis_url=SimpleNamespace(get_secret_value=lambda: "redis://localhost"),
        site_origin="https://example.com", allowed_hosts=["example.com"],
    )
    check_server.check(settings)
    poster = build / "assets/poster.png"
    poster.write_bytes(b"poster")
    original_open = Path.open

    def deny_poster_open(path, *args, **kwargs):
        if path == poster:
            raise PermissionError("poster is unreadable")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as inaccessible:
        inaccessible.setattr(Path, "open", deny_poster_open)
        with pytest.raises(ValueError, match="前端静态资源不可读"):
            check_server.check(settings)
    shared.unlink()
    with pytest.raises(ValueError, match="前端构建产物不完整"):
        check_server.check(settings)
