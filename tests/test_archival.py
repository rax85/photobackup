import os
import tempfile
import unittest
from media_server import archival
from media_server.settings import Settings


class TestArchival(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="archival_test_")
        self.sample_file = os.path.join(self.test_dir, "sample.jpg")
        with open(self.sample_file, "wb") as f:
            f.write(b"sample image bytes")

    def tearDown(self):
        if os.path.exists(self.sample_file):
            os.remove(self.sample_file)
        if os.path.exists(self.test_dir):
            os.rmdir(self.test_dir)

    def test_null_archival_provider(self):
        settings = Settings(archival_backend="Off")
        manager = archival.ArchivalManager(settings)
        self.assertFalse(manager.archive_media_file(self.sample_file, "hash123"))
        status = manager.test_status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["backend"], "Off")

    def test_mock_archival_provider(self):
        mock_provider = archival.MockArchivalProvider("my-test-bucket")
        self.assertTrue(
            mock_provider.upload_file(self.sample_file, "media/ha/hash123.jpg")
        )
        self.assertIn("media/ha/hash123.jpg", mock_provider.uploaded_files)
        res = mock_provider.test_connection()
        self.assertTrue(res.success)


if __name__ == "__main__":
    unittest.main()
