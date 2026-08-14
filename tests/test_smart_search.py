import shutil
import tempfile
import time
import unittest
from media_server import database as db_utils


class TestSmartSearch(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="search_test_")
        self.db_path = db_utils.get_db_path(self.test_dir)
        db_utils.init_db(self.test_dir)

        now = time.time()
        self.media_items = [
            {
                "sha256_hex": "sha_golden_gate",
                "filename": "golden_gate_bridge.jpg",
                "original_filename": "IMG_0001.jpg",
                "file_path": "photos/golden_gate_bridge.jpg",
                "last_modified": now,
                "original_creation_date": 1672531200,
                "city": "San Francisco",
                "country": "United States",
                "mime_type": "image/jpeg",
                "filesize": 204800,
                "tags": '["bridge", "landmark", "sunset"]',
            },
            {
                "sha256_hex": "sha_eiffel_tower",
                "filename": "eiffel_tower.png",
                "original_filename": "IMG_0002.png",
                "file_path": "photos/eiffel_tower.png",
                "last_modified": now,
                "original_creation_date": 1675209600,
                "city": "Paris",
                "country": "France",
                "mime_type": "image/png",
                "filesize": 409600,
                "tags": '["tower", "paris", "monument"]',
            },
            {
                "sha256_hex": "sha_cat_video",
                "filename": "cute_cat_playing.mp4",
                "original_filename": "VID_0003.mp4",
                "file_path": "videos/cute_cat_playing.mp4",
                "last_modified": now,
                "original_creation_date": 1677628800,
                "city": "Tokyo",
                "country": "Japan",
                "mime_type": "video/mp4",
                "filesize": 10485760,
                "tags": '["cat", "pet", "funny"]',
            },
        ]

        for item in self.media_items:
            db_utils.add_or_update_media_file(self.db_path, item)

    def tearDown(self):
        db_utils.close_db_connection()
        shutil.rmtree(self.test_dir)

    def test_search_by_city(self):
        results = db_utils.search_media_files(self.db_path, "Paris")
        self.assertEqual(len(results), 1)
        self.assertIn("sha_eiffel_tower", results)

    def test_search_by_tag(self):
        results = db_utils.search_media_files(self.db_path, "sunset")
        self.assertEqual(len(results), 1)
        self.assertIn("sha_golden_gate", results)

    def test_search_by_filename(self):
        results = db_utils.search_media_files(self.db_path, "cute_cat")
        self.assertEqual(len(results), 1)
        self.assertIn("sha_cat_video", results)

    def test_search_filter_video(self):
        results = db_utils.search_media_files(self.db_path, "", media_type="video")
        self.assertEqual(len(results), 1)
        self.assertIn("sha_cat_video", results)

    def test_search_filter_image(self):
        results = db_utils.search_media_files(self.db_path, "", media_type="image")
        self.assertEqual(len(results), 2)
        self.assertIn("sha_golden_gate", results)
        self.assertIn("sha_eiffel_tower", results)

    def test_fts5_prefix_matching(self):
        # Prefix matching test for FTS5 (e.g. 'eiff*' matches 'eiffel')
        results = db_utils.search_media_files(self.db_path, "eiff")
        self.assertEqual(len(results), 1)
        self.assertIn("sha_eiffel_tower", results)

        results_gold = db_utils.search_media_files(self.db_path, "gold")
        self.assertEqual(len(results_gold), 1)
        self.assertIn("sha_golden_gate", results_gold)

    def test_fts5_multi_token_search(self):
        # Multi-token search requires all tokens to match
        results = db_utils.search_media_files(self.db_path, "Paris monument")
        self.assertEqual(len(results), 1)
        self.assertIn("sha_eiffel_tower", results)

        # Non-matching combination
        results_none = db_utils.search_media_files(self.db_path, "Paris sunset")
        self.assertEqual(len(results_none), 0)

    def test_fts5_trigger_update_and_delete(self):
        # Verify FTS trigger update
        db_utils.update_media_file_fields(
            self.db_path, "sha_eiffel_tower", {"city": "Rome"}
        )
        results_rome = db_utils.search_media_files(self.db_path, "Rome")
        self.assertEqual(len(results_rome), 1)
        self.assertIn("sha_eiffel_tower", results_rome)

        # Verify FTS trigger delete
        db_utils.delete_media_file_by_sha(self.db_path, "sha_eiffel_tower")
        results_deleted = db_utils.search_media_files(self.db_path, "Rome")
        self.assertEqual(len(results_deleted), 0)

    def test_database_stats(self):
        stats = db_utils.get_database_stats(self.db_path)
        self.assertEqual(stats["total_count"], 3)
        self.assertEqual(stats["image_count"], 2)
        self.assertEqual(stats["video_count"], 1)
        self.assertEqual(stats["cities_count"], 3)
        self.assertGreater(stats["total_size_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
