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
        self.assertEqual(result[self.hash_img1]['file_path'], self.file_img1)

        # Check video1.mp4
        self.assertIn(self.hash_vid1, result)
        self.assertEqual(result[self.hash_vid1]['filename'], "video1.mp4")
        self.assertAlmostEqual(result[self.hash_vid1]['last_modified'], self.time_vid1, places=7)
        self.assertEqual(result[self.hash_vid1]['file_path'], self.file_vid1)

        # Check subdir/image2.png
        self.assertIn(self.hash_img2, result)
        self.assertEqual(result[self.hash_img2]['filename'], "image2.png")
        self.assertAlmostEqual(result[self.hash_img2]['last_modified'], self.time_img2, places=7)
        self.assertEqual(result[self.hash_img2]['file_path'], self.file_img2_subdir)

        # Ensure text.txt and archive.xyz were not included
        for sha, data in result.items():
            self.assertNotIn(data['filename'], ["document.txt", "archive.xyz"])

    def test_rescan_directory_no_changes(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)
        self.assertEqual(initial_scan, rescan_result)

    def test_rescan_directory_add_file(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)

        # Add a new file
        time_new_img = time.time() - 200
        content_new_img = "new image content"
        hash_new_img = calculate_sha256(content_new_img)
        file_new_img = create_dummy_file(self.test_dir, "new_image.gif", content_new_img, mtime=time_new_img)

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan) + 1)
        self.assertIn(hash_new_img, rescan_result)
        self.assertEqual(rescan_result[hash_new_img]['filename'], "new_image.gif")
        self.assertAlmostEqual(rescan_result[hash_new_img]['last_modified'], time_new_img, places=7)
        self.assertEqual(rescan_result[hash_new_img]['file_path'], file_new_img)

    def test_rescan_directory_remove_file(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)

        # Remove a file (image1.jpg)
        os.remove(self.file_img1)

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan) - 1)
        self.assertNotIn(self.hash_img1, rescan_result)

    def test_rescan_directory_modify_file_content_changes_sha(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)

        # Modify content of image1.jpg (changes SHA)
        new_content_img1 = "modified image1 content"
        new_hash_img1 = calculate_sha256(new_content_img1)
        # Ensure mtime also changes, as real modifications would
        new_time_img1 = time.time() - 100
        create_dummy_file(self.test_dir, "image1.jpg", new_content_img1, mtime=new_time_img1) # Overwrites

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan)) # Same number of files
        self.assertNotIn(self.hash_img1, rescan_result) # Old SHA should be gone
        self.assertIn(new_hash_img1, rescan_result) # New SHA should be present
        self.assertEqual(rescan_result[new_hash_img1]['filename'], "image1.jpg")
        self.assertAlmostEqual(rescan_result[new_hash_img1]['last_modified'], new_time_img1, places=7)

    def test_rescan_directory_modify_file_mtime_only(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        self.assertIn(self.hash_img1, initial_scan) # Ensure file is in initial scan
        original_mtime_from_initial_scan = initial_scan[self.hash_img1]['last_modified']

        # Modify mtime of image1.jpg, content (and SHA) remains the same
        # Ensure new_time_img1 is significantly different and later.
        new_time_img1 = time.time() + 100 # Clearly different and in the future relative to self.time_img1
        self.assertNotAlmostEqual(original_mtime_from_initial_scan, new_time_img1, places=7) # Verify it's different beforehand

        os.utime(self.file_img1, (new_time_img1, new_time_img1))

        # Perform the rescan
        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        # Basic checks
        self.assertEqual(len(rescan_result), len(initial_scan))
        self.assertIn(self.hash_img1, rescan_result) # SHA is the same
        self.assertEqual(rescan_result[self.hash_img1]['filename'], "image1.jpg")

        # Check that the last_modified time IS updated in the rescan_result
        self.assertAlmostEqual(rescan_result[self.hash_img1]['last_modified'], new_time_img1, places=7)

        # Ensure the original entry in initial_scan was indeed different, confirming the update happened in rescan_result
        self.assertNotAlmostEqual(original_mtime_from_initial_scan, rescan_result[self.hash_img1]['last_modified'], places=7,
                                  msg="Timestamp in rescan_result should be updated and different from initial_scan's timestamp.")
        self.assertAlmostEqual(original_mtime_from_initial_scan, self.time_img1, places=7,
                                  msg="Timestamp in initial_scan should match the original self.time_img1.")


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
