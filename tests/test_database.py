import unittest
import os
import tempfile
import shutil
import time
import sys

# Add project root to sys.path to allow direct import of media_server
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from media_server import database as db_utils  # noqa: E402


class TestDataFiltering(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="db_filter_test_")
        self.db_path = db_utils.get_db_path(self.test_dir)
        db_utils.init_db(self.test_dir)

        # Sample data
        self.media_data = [
            {
                "sha256_hex": "hash1",
                "filename": "file1.jpg",
                "file_path": "path1",
                "last_modified": time.time(),
                "original_creation_date": 1672531200,
                "city": "New York",
                "country": "USA",  # 2023-01-01
            },
            {
                "sha256_hex": "hash2",
                "filename": "file2.jpg",
                "file_path": "path2",
                "last_modified": time.time(),
                "original_creation_date": 1675209600,
                "city": "Los Angeles",
                "country": "USA",  # 2023-02-01
            },
            {
                "sha256_hex": "hash3",
                "filename": "file3.jpg",
                "file_path": "path3",
                "last_modified": time.time(),
                "original_creation_date": 1672531200,
                "city": "New York",
                "country": "USA",  # 2023-01-01
            },
            {
                "sha256_hex": "hash4",
                "filename": "file4.jpg",
                "file_path": "path4",
                "last_modified": time.time(),
                "original_creation_date": 1677628800,
                "city": "London",
                "country": "UK",  # 2023-03-01
            },
        ]

        for data in self.media_data:
            db_utils.add_or_update_media_file(self.db_path, data)

    def tearDown(self):
        db_utils.close_db_connection()
        shutil.rmtree(self.test_dir)

    def test_get_media_files_by_date(self):
        # Test for a date with multiple files
        results = db_utils.get_media_files_by_date(self.db_path, 1672531200)
        self.assertEqual(len(results), 2)
        self.assertIn("hash1", results)
        self.assertIn("hash3", results)

        # Test for a date with a single file
        results = db_utils.get_media_files_by_date(self.db_path, 1675209600)
        self.assertEqual(len(results), 1)
        self.assertIn("hash2", results)

        # Test for a date with no files
        results = db_utils.get_media_files_by_date(
            self.db_path, 1672617600
        )  # 2023-01-02
        self.assertEqual(len(results), 0)

    def test_get_media_files_by_date_range(self):
        # Test range including multiple dates
        results = db_utils.get_media_files_by_date_range(
            self.db_path, 1672531200, 1675209600
        )
        self.assertEqual(len(results), 3)
        self.assertIn("hash1", results)
        self.assertIn("hash2", results)
        self.assertIn("hash3", results)

        # Test range with a single date
        results = db_utils.get_media_files_by_date_range(
            self.db_path, 1672531200, 1672531200
        )
        self.assertEqual(len(results), 2)

        # Test range with no files
        results = db_utils.get_media_files_by_date_range(
            self.db_path, 1680307200, 1682899200
        )  # April 2023
        self.assertEqual(len(results), 0)

    def test_get_media_files_by_location(self):
        # Test for a city with multiple files
        results = db_utils.get_media_files_by_location(self.db_path, "New York")
        self.assertEqual(len(results), 2)
        self.assertIn("hash1", results)
        self.assertIn("hash3", results)

        # Test for a city with a single file
        results = db_utils.get_media_files_by_location(self.db_path, "London")
        self.assertEqual(len(results), 1)
        self.assertIn("hash4", results)

        # Test for a city with country
        results = db_utils.get_media_files_by_location(self.db_path, "New York", "USA")
        self.assertEqual(len(results), 2)

        # Test for a city with wrong country
        results = db_utils.get_media_files_by_location(self.db_path, "New York", "UK")
        self.assertEqual(len(results), 0)

        # Test for a non-existent city
        results = db_utils.get_media_files_by_location(self.db_path, "Paris")
        self.assertEqual(len(results), 0)

    def test_get_media_files_by_location_case_insensitive(self):
        # Test for a city with different case
        results = db_utils.get_media_files_by_location(self.db_path, "new york")
        self.assertEqual(len(results), 2)
        self.assertIn("hash1", results)
        self.assertIn("hash3", results)

        # Test for a city and country with different case
        results = db_utils.get_media_files_by_location(self.db_path, "new york", "usa")
        self.assertEqual(len(results), 2)

    def test_batch_add_and_total_count(self):
        batch_data = [
            {
                "sha256_hex": f"batch_hash_{i}",
                "filename": f"batch_file_{i}.jpg",
                "original_filename": f"batch_file_{i}.jpg",
                "file_path": f"batch/file_{i}.jpg",
                "last_modified": time.time(),
                "original_creation_date": 1672531200 + i * 100,
                "city": "Tokyo",
                "country": "Japan",
                "mime_type": "image/jpeg",
                "filesize": 1024,
                "tags": '["tokyo", "japan"]',
            }
            for i in range(5)
        ]
        db_utils.batch_add_or_update_media_files(self.db_path, batch_data)
        count = db_utils.get_total_media_count(self.db_path)
        self.assertEqual(count, 9)  # 4 initial + 5 batch

        search_res = db_utils.search_media_files(self.db_path, "Tokyo")
        self.assertEqual(len(search_res), 5)


if __name__ == "__main__":
    unittest.main()
