import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


WORKER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_DIR))

import worker


class PickDownloadedFileTests(unittest.TestCase):
    def test_finds_media_file_nested_in_collection_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            media_file = task_dir / "collection" / "[P04]男孩.m4a"
            media_file.parent.mkdir()
            media_file.write_bytes(b"audio")

            self.assertEqual(worker._pick_file_from_dir(tmp), str(media_file))

    def test_rejects_multiple_media_files_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            collection_dir = task_dir / "collection"
            collection_dir.mkdir()
            (collection_dir / "[P01]第一首.m4a").write_bytes(b"audio 1")
            (collection_dir / "[P02]第二首.m4a").write_bytes(b"audio 2")

            with self.assertRaises(worker.MultipleMediaFilesError):
                worker._pick_file_from_dir(tmp)


class BbdownArgumentsTests(unittest.TestCase):
    def test_uses_page_from_resolved_short_link(self):
        with mock.patch.object(
            worker,
            "_resolve_download_url",
            return_value="https://www.bilibili.com/video/BV1ZpdVBgEz1/?p=4",
        ):
            args = worker._build_bbdown_args(
                "/worker/BBDown",
                "https://b23.tv/kkwWxgx",
                "audio",
                use_tv=True,
            )

        self.assertEqual(
            args,
            [
                "/worker/BBDown",
                "-tv",
                "-p",
                "4",
                "https://b23.tv/kkwWxgx",
                "--audio-only",
            ],
        )

    def test_defaults_to_first_page_without_page_parameter(self):
        args = worker._build_bbdown_args(
            "/worker/BBDown",
            "https://www.bilibili.com/video/BV1ZpdVBgEz1",
            "video",
            use_tv=True,
            resolved_url="https://www.bilibili.com/video/BV1ZpdVBgEz1",
        )

        self.assertEqual(
            args,
            [
                "/worker/BBDown",
                "-tv",
                "-p",
                "1",
                "https://www.bilibili.com/video/BV1ZpdVBgEz1",
            ],
        )


if __name__ == "__main__":
    unittest.main()
