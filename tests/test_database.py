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

    # --- NULLS LAST and Secondary Sorting ---
    def test_nulls_last_and_filename_sorting(self):
        items = [
            {"sha256_hex": "sha_null_b", "filename": "b.jpg", "file_path": "b.jpg", "last_modified": 100, "original_creation_date": None},
            {"sha256_hex": "sha_null_a", "filename": "a.jpg", "file_path": "a.jpg", "last_modified": 100, "original_creation_date": None},
            {"sha256_hex": "sha_old", "filename": "old.jpg", "file_path": "old.jpg", "last_modified": 100, "original_creation_date": 1000},
            {"sha256_hex": "sha_new", "filename": "new.jpg", "file_path": "new.jpg", "last_modified": 100, "original_creation_date": 2000},
        ]
        # Clean db and insert test items
        for sha in list(db_utils.get_all_shas_in_db(self.db_path)):
            db_utils.delete_media_file_by_sha(self.db_path, sha)
        db_utils.batch_add_or_update_media_files(self.db_path, items)
        
        all_files = list(db_utils.get_all_media_files(self.db_path).values())
        filenames = [f["filename"] for f in all_files]
        # Order must be: new.jpg (2000), old.jpg (1000), a.jpg (NULL), b.jpg (NULL)
        self.assertEqual(filenames, ["new.jpg", "old.jpg", "a.jpg", "b.jpg"])

    # --- Path Conflict Replacement ---
    def test_path_conflict_deletes_old_sha(self):
        item1 = {"sha256_hex": "sha_v1", "filename": "photo.jpg", "file_path": "photos/photo.jpg", "last_modified": 100}
        item2 = {"sha256_hex": "sha_v2", "filename": "photo.jpg", "file_path": "photos/photo.jpg", "last_modified": 200}
        
        db_utils.add_or_update_media_file(self.db_path, item1)
        self.assertIsNotNone(db_utils.get_media_file_by_sha(self.db_path, "sha_v1"))
        
        # Overwrite same path with new SHA
        db_utils.add_or_update_media_file(self.db_path, item2)
        self.assertIsNone(db_utils.get_media_file_by_sha(self.db_path, "sha_v1"))
        self.assertIsNotNone(db_utils.get_media_file_by_sha(self.db_path, "sha_v2"))

    # --- Required Fields Validation ---
    def test_add_media_missing_required_fields_raises_value_error(self):
        # Missing last_modified
        with self.assertRaises(ValueError):
            db_utils.add_or_update_media_file(self.db_path, {"sha256_hex": "1", "filename": "1.jpg", "file_path": "1.jpg"})
        
        # None value in required field
        with self.assertRaises(ValueError):
            db_utils.add_or_update_media_file(self.db_path, {"sha256_hex": None, "filename": "1.jpg", "file_path": "1.jpg", "last_modified": 100})

    # --- Complete Query Helper Coverage ---
    def test_crud_helper_functions(self):
        item = {
            "sha256_hex": "sha_crud",
            "filename": "crud.jpg",
            "file_path": "dir/crud.jpg",
            "last_modified": 12345.67,
            "thumbnail_file": "thumb.jpg",
        }
        db_utils.add_or_update_media_file(self.db_path, item)

        # get_media_file_by_path
        self.assertEqual(db_utils.get_media_file_by_path(self.db_path, "dir/crud.jpg")["sha256_hex"], "sha_crud")
        self.assertIsNone(db_utils.get_media_file_by_path(self.db_path, "nonexistent"))

        # get_file_last_modified
        self.assertAlmostEqual(db_utils.get_file_last_modified(self.db_path, "dir/crud.jpg"), 12345.67)
        self.assertIsNone(db_utils.get_file_last_modified(self.db_path, "nonexistent"))

        # get_all_db_file_paths & get_all_shas_in_db
        self.assertIn("dir/crud.jpg", db_utils.get_all_db_file_paths(self.db_path))
        self.assertIn("sha_crud", db_utils.get_all_shas_in_db(self.db_path))

        # get_all_shas_and_thumbnails & get_all_file_paths_and_last_modified
        sha_thumbs = db_utils.get_all_shas_and_thumbnails(self.db_path)
        self.assertEqual(sha_thumbs.get("sha_crud"), "thumb.jpg")
        path_mtimes = db_utils.get_all_file_paths_and_last_modified(self.db_path)
        self.assertAlmostEqual(path_mtimes.get("dir/crud.jpg"), 12345.67)

        # update_media_file_fields
        self.assertFalse(db_utils.update_media_file_fields(self.db_path, "sha_crud", {}))
        self.assertFalse(db_utils.update_media_file_fields(self.db_path, "sha_crud", {"invalid_column": 123}))
        self.assertTrue(db_utils.update_media_file_fields(self.db_path, "sha_crud", {"city": "Berlin"}))
        self.assertEqual(db_utils.get_media_file_by_sha(self.db_path, "sha_crud")["city"], "Berlin")

        # delete_media_file_by_path
        self.assertTrue(db_utils.delete_media_file_by_path(self.db_path, "dir/crud.jpg"))
        self.assertFalse(db_utils.delete_media_file_by_path(self.db_path, "dir/crud.jpg"))


if __name__ == "__main__":
    unittest.main()

