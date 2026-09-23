import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import export_image_cache


MB = 1024 * 1024


class ExportImageCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temporary_directory.name)
        self.settings = patch.multiple(
            export_image_cache.settings,
            export_image_cache_max_mb=500,
            export_image_cache_target_mb=450,
        )
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temporary_directory.cleanup()

    def create_file(self, name: str, size_mb: int, age: int) -> Path:
        path = self.cache_dir / name
        with path.open("wb") as stream:
            stream.truncate(size_mb * MB)
        timestamp = time.time() - age
        os.utime(path, (timestamp, timestamp))
        return path

    def test_cache_below_limit_is_not_changed(self):
        cached = self.create_file("cached.jpg", 400, 10)

        export_image_cache.maintain_export_image_cache(self.cache_dir)

        self.assertTrue(cached.exists())

    def test_cache_exactly_at_limit_is_not_changed(self):
        cached = self.create_file("cached.jpg", 500, 10)

        export_image_cache.maintain_export_image_cache(self.cache_dir)

        self.assertTrue(cached.exists())

    def test_cache_above_limit_starts_cleanup(self):
        files = [self.create_file(f"{index:02}.jpg", 100, 10 - index) for index in range(5)]
        overflow = self.create_file("overflow.jpg", 1, 0)

        export_image_cache.maintain_export_image_cache(self.cache_dir)

        self.assertFalse(files[0].exists())
        self.assertTrue(overflow.exists())

    def test_oldest_files_are_removed_until_target(self):
        files = [self.create_file(f"{index:02}.jpg", 50, 20 - index) for index in range(12)]

        export_image_cache.maintain_export_image_cache(self.cache_dir)

        self.assertEqual(sum(path.stat().st_size for path in self.cache_dir.glob("*.jpg")), 450 * MB)
        self.assertFalse(any(path.exists() for path in files[:3]))
        self.assertTrue(all(path.exists() for path in files[3:]))

    def test_new_files_remain_in_cache(self):
        old_files = [self.create_file(f"old-{index}.jpg", 50, 100 - index) for index in range(4)]
        new_files = [self.create_file(f"new-{index}.jpg", 50, index) for index in range(8)]

        export_image_cache.maintain_export_image_cache(self.cache_dir)

        self.assertFalse(any(path.exists() for path in old_files[:3]))
        self.assertTrue(all(path.exists() for path in new_files))

    def test_delete_error_does_not_stop_other_deletions(self):
        files = [self.create_file(f"{index}.jpg", 100, 10 - index) for index in range(6)]
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == files[0]:
                raise PermissionError("test")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", unlink):
            export_image_cache.maintain_export_image_cache(self.cache_dir)

        self.assertTrue(files[0].exists())
        self.assertFalse(files[1].exists())

    def test_cleanup_error_does_not_escape_excel_export_hook(self):
        with patch.object(export_image_cache, "maintain_export_image_cache", side_effect=OSError("test")):
            export_image_cache.maintain_export_image_cache_safely("job-id")

    def test_parallel_maintenance_runs_only_one_cleanup(self):
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def cleanup(_directory):
            nonlocal calls
            calls += 1
            entered.set()
            release.wait(2)

        with patch.object(export_image_cache, "_cleanup_cache", cleanup):
            first = threading.Thread(target=export_image_cache.maintain_export_image_cache, args=(self.cache_dir,))
            second = threading.Thread(target=export_image_cache.maintain_export_image_cache, args=(self.cache_dir,))
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            second.join()
            release.set()
            first.join()

        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
