import unittest
import os
import tempfile
import hashlib
from rest_server.lib import file_scanner

class TestFileScanner(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing
        self.test_dir = tempfile.TemporaryDirectory()
        self.storage_path = self.test_dir.name

        # Create some dummy files
        self.file1_content = b"This is file1."
        self.file1_path = os.path.join(self.storage_path, "file1.txt")
        with open(self.file1_path, "wb") as f:
            f.write(self.file1_content)
        self.file1_sha256 = hashlib.sha256(self.file1_content).hexdigest()

        self.file2_content = b"This is file2, different content."
        self.file2_path = os.path.join(self.storage_path, "subfolder", "file2.txt")
        os.makedirs(os.path.dirname(self.file2_path), exist_ok=True)
        with open(self.file2_path, "wb") as f:
            f.write(self.file2_content)
        self.file2_sha256 = hashlib.sha256(self.file2_content).hexdigest()

        # Create a duplicate file (same content as file1)
        self.file3_path = os.path.join(self.storage_path, "file3.txt")
        with open(self.file3_path, "wb") as f:
            f.write(self.file1_content)


    def tearDown(self):
        # Cleanup the temporary directory
        self.test_dir.cleanup()

    def test_calculate_sha256_existing_file(self):
        sha256 = file_scanner.calculate_sha256(self.file1_path)
        self.assertEqual(sha256, self.file1_sha256)

    def test_calculate_sha256_non_existing_file(self):
        sha256 = file_scanner.calculate_sha256("non_existent_file.txt")
        self.assertIsNone(sha256)

    def test_scan_directory_empty(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            result = file_scanner.scan_directory(empty_dir)
            self.assertEqual(result, {})

    def test_scan_directory_with_files(self):
        expected_map = {
            self.file1_sha256: sorted([self.file1_path, self.file3_path]),
            self.file2_sha256: [self.file2_path]
        }
        result = file_scanner.scan_directory(self.storage_path)
        # Sort the lists of file paths in the result for consistent comparison
        for sha_key in result:
            result[sha_key].sort()
        self.assertEqual(result, expected_map)

    def test_scan_directory_invalid_directory(self):
        result = file_scanner.scan_directory("non_existent_directory")
        self.assertEqual(result, {})

if __name__ == '__main__':
    unittest.main()
