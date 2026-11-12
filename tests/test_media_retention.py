import os
import time

from app.services.private_media import PrivateImageCache


def test_prunes_only_expired_generated_files(tmp_path):
    old = tmp_path / ("a" * 64 + ".webp")
    fresh = tmp_path / ("b" * 64 + ".webp")
    unrelated = tmp_path / "original.webp"
    temp = tmp_path / ("c" * 64 + "." + "d" * 16 + ".tmp")
    outside = tmp_path.parent / "external.webp"
    outside.write_bytes(b"keep")
    link = tmp_path / ("e" * 64 + ".webp")
    link.symlink_to(outside)
    for path in (old, unrelated, temp):
        path.write_bytes(b"cached")
        os.utime(path, (time.time() - 31 * 86400,) * 2)
    fresh.write_bytes(b"new")
    PrivateImageCache.prune_cache(tmp_path)
    assert not old.exists() and not temp.exists()
    assert (
        fresh.exists() and unrelated.exists() and outside.exists() and link.is_symlink()
    )
