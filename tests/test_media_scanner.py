import unittest
import os
import shutil
import tempfile
import hashlib
import time

# Add project root to sys.path to allow direct import of media_server
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from media_server import media_scanner

# Helper to create dummy files with specific content and mtime
def create_dummy_file(dir_path, filename, content="dummy content", mtime=None):
    filepath = os.path.join(dir_path, filename)
    with open(filepath, "w") as f:
        f.write(content)
    if mtime is not None:
        os.utime(filepath, (mtime, mtime))
    return filepath

# Helper to calculate SHA256 for verification
def calculate_sha256(content_str):
    return hashlib.sha256(content_str.encode('utf-8')).hexdigest()

class TestMediaScanner(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp(prefix="media_server_test_")
        self.subdir = os.path.join(self.test_dir, "subdir")
        os.makedirs(self.subdir)

        # Define some file contents and their expected SHA256 hashes
        self.content_img1 = "this is image1"
        self.hash_img1 = calculate_sha256(self.content_img1)
        self.content_vid1 = "this is video1"
        self.hash_vid1 = calculate_sha256(self.content_vid1)
        self.content_img2 = "this is image2 in subdir"
        self.hash_img2 = calculate_sha256(self.content_img2)

        # Create dummy files
        # mimetypes.guess_type relies on file extensions.
        self.time_img1 = time.time() - 1000 # Ensure a distinct, old timestamp
        self.file_img1 = create_dummy_file(self.test_dir, "image1.jpg", self.content_img1, mtime=self.time_img1)

        self.time_vid1 = time.time() - 2000
        self.file_vid1 = create_dummy_file(self.test_dir, "video1.mp4", self.content_vid1, mtime=self.time_vid1)

        self.file_txt1 = create_dummy_file(self.test_dir, "document.txt", "this is a text document")

        self.time_img2 = time.time() - 500
        self.file_img2_subdir = create_dummy_file(self.subdir, "image2.png", self.content_img2, mtime=self.time_img2)

        self.file_unknown_ext = create_dummy_file(self.test_dir, "archive.xyz", "unknown extension")

        # For testing unreadable file for hashing (though get_file_sha256 handles logging, not raising)
        # self.unreadable_file = create_dummy_file(self.test_dir, "unreadable.jpg", "content")
        # os.chmod(self.unreadable_file, 0o000) # Make unreadable - This might fail on some OS or with permissions

    def tearDown(self):
        # Clean up the temporary directory
        # if os.path.exists(self.unreadable_file): # Ensure it's readable to delete
        #     os.chmod(self.unreadable_file, 0o600)
        shutil.rmtree(self.test_dir)

    def test_is_media_file(self):
        self.assertTrue(media_scanner.is_media_file("test.jpg"))
        self.assertTrue(media_scanner.is_media_file("test.jpeg"))
        self.assertTrue(media_scanner.is_media_file("test.png"))
        self.assertTrue(media_scanner.is_media_file("test.gif"))
        self.assertTrue(media_scanner.is_media_file("test.mp4"))
        self.assertTrue(media_scanner.is_media_file("test.avi"))
        self.assertTrue(media_scanner.is_media_file("test.mov"))
        self.assertFalse(media_scanner.is_media_file("test.txt"))
        self.assertFalse(media_scanner.is_media_file("test.doc"))
        self.assertFalse(media_scanner.is_media_file("test.xyz")) # Unknown extension
        self.assertFalse(media_scanner.is_media_file("test_no_extension"))

    def test_get_file_sha256(self):
        # Test with a known file and content
        expected_hash = self.hash_img1
        actual_hash = media_scanner.get_file_sha256(self.file_img1)
        self.assertEqual(actual_hash, expected_hash)

        # Test with a non-existent file (should log error and return None)
        self.assertIsNone(media_scanner.get_file_sha256("non_existent_file.jpg"))

    def test_scan_directory_empty(self):
        empty_dir = os.path.join(self.test_dir, "empty_subdir")
        os.makedirs(empty_dir)
        result = media_scanner.scan_directory(empty_dir)
        self.assertEqual(result, {})

    def test_scan_directory_non_existent(self):
        result = media_scanner.scan_directory(os.path.join(self.test_dir, "does_not_exist"))
        self.assertEqual(result, {}) # Should return empty dict and log error

    def test_scan_directory_with_media_and_other_files(self):
        result = media_scanner.scan_directory(self.test_dir)

        self.assertEqual(len(result), 3) # img1.jpg, video1.mp4, subdir/image2.png

        # Check img1.jpg
        self.assertIn(self.hash_img1, result)
        self.assertEqual(result[self.hash_img1]['filename'], "image1.jpg")
        self.assertAlmostEqual(result[self.hash_img1]['last_modified'], self.time_img1, places=7)

        # Check video1.mp4
        self.assertIn(self.hash_vid1, result)
        self.assertEqual(result[self.hash_vid1]['filename'], "video1.mp4")
        self.assertAlmostEqual(result[self.hash_vid1]['last_modified'], self.time_vid1, places=7)

        # Check subdir/image2.png
        self.assertIn(self.hash_img2, result)
        self.assertEqual(result[self.hash_img2]['filename'], "image2.png")
        self.assertAlmostEqual(result[self.hash_img2]['last_modified'], self.time_img2, places=7)

        # Ensure text.txt and archive.xyz were not included
        for sha, data in result.items():
            self.assertNotIn(data['filename'], ["document.txt", "archive.xyz"])

    def test_scan_directory_permissions_error_on_metadata(self):
        # This test is tricky to set up reliably across platforms for getmtime.
        # media_scanner logs errors from os.path.getmtime and skips the file.
        # We can simulate by creating a file where getmtime might fail,
        # but a more direct way is to ensure the logic handles it.
        # For now, we trust the try-except block in scan_directory.
        # If a file hash is None (e.g., due to read error for hashing), it's skipped.
        # If getmtime fails, it's also logged and skipped.

        # Create a file, then remove it before scan_directory tries to getmtime (simulates race condition)
        # This isn't perfect but tests one path of os.stat failure.
        tricky_file_path = create_dummy_file(self.test_dir, "tricky.jpg", "content")

        original_getmtime = os.path.getmtime
        def mock_getmtime(path):
            if "tricky.jpg" in path:
                raise OSError("Simulated metadata read error")
            return original_getmtime(path)

        media_scanner.os.path.getmtime = mock_getmtime

        result = media_scanner.scan_directory(self.test_dir)

        media_scanner.os.path.getmtime = original_getmtime # Restore

        # tricky.jpg should not be in the results
        tricky_hash = calculate_sha256("content")
        self.assertNotIn(tricky_hash, result, "File with simulated getmtime error should be skipped.")
        # Other files should still be there
        self.assertIn(self.hash_img1, result)
        self.assertIn(self.hash_vid1, result)
        self.assertIn(self.hash_img2, result)


if __name__ == '__main__':
    unittest.main()
