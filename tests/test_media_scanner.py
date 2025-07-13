import unittest
import os
import shutil
import sqlite3
from absl import logging
from media_server.media_scanner import scan_directory
from media_server.database import get_db_connection, init_db

logging.set_verbosity(logging.INFO)

class TestMediaScanner(unittest.TestCase):
    def setUp(self):
        self.storage_dir = 'test_storage'
        self.db_path = os.path.join(self.storage_dir, 'media_cache.sqlite3')
        os.makedirs(self.storage_dir, exist_ok=True)
        init_db(self.storage_dir)

        # Copy the test image to the storage directory
        self.image_path = os.path.join(self.storage_dir, 'test_image_with_gps.jpg')
        shutil.copyfile('tests/test_image_with_gps.jpg', self.image_path)

    def tearDown(self):
        shutil.rmtree(self.storage_dir)

    def test_scan_directory_with_gps(self):
        scan_directory(self.storage_dir, self.db_path)
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT city, country, latitude, longitude FROM media_files WHERE filename = 'test_image_with_gps.jpg'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        # The test image has coordinates that resolve to Paris, France
        self.assertEqual(row[0], 'Paris')
        self.assertEqual(row[1], 'France')
        self.assertAlmostEqual(row[2], 43.46745, delta=0.0001)
        self.assertAlmostEqual(row[3], 11.88512, delta=0.0001)

if __name__ == '__main__':
    unittest.main()
