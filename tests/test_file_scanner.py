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
        self.test_files = {}

        # Text file (should be ignored)
        self._create_test_file("test.txt", b"This is a text file.", "text/plain")

        # Dummy PNG image file (using minimal valid PNG structure)
        # See: https://en.wikipedia.org/wiki/Portable_Network_Graphics#File_header
        png_magic = b"\x89PNG\r\n\x1a\n"
        # Minimal IHDR chunk (1x1 pixel, 1-bit depth, color type 0, etc.)
        ihdr_data = b"\x00\x00\x00\x0dIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x01\x00\x00\x00\x00"
        ihdr_crc = b"\x37\x23\x0D\x8F" # CRC for the IHDR chunk
        ihdr_chunk = ihdr_data + ihdr_crc
        # Minimal IDAT chunk (empty)
        idat_data = b"\x00\x00\x00\x00IDAT"
        idat_crc = b"\x78\x59\x06\x53" # CRC for empty IDAT
        idat_chunk = idat_data + idat_crc
        # IEND chunk
        iend_chunk = b"\x00\x00\x00\x00IEND\xAEB`\x82"
        dummy_png_content = png_magic + ihdr_chunk + idat_chunk + iend_chunk
        self._create_test_file("image.png", dummy_png_content, "image/png", is_media=True)

        # Duplicate PNG image file (same content, different name)
        self._create_test_file("image_duplicate.png", dummy_png_content, "image/png", is_media=True, in_subdir=True)

        # Dummy MP4 video file (very basic, might not be playable but libmagic should identify it)
        # A minimal MP4 starts with ftyp box. Example: ftypisom
        # For simplicity, we'll use a very short byte sequence that libmagic often identifies as video.
        # This is fragile and might depend on libmagic version.
        # A more robust way would be to have actual small media files.
        # Let's try with a common signature for MP4.
        # Box Size (4 bytes) + Box Type (4 bytes, 'ftyp') + Major Brand (4 bytes, e.g., 'isom')
        # + Minor Version (4 bytes) + Compatible Brands (variable)
        # This is a simplified version, python-magic might need more for robust detection.
        # For now, we'll create a file and check its MIME type with python-magic locally to get a valid header.
        # Using a known simple GIF header as a placeholder for a second media type, as it's simple.
        # GIF89a, 1x1 pixel
        dummy_gif_content = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xFF\xFF\xFF!\xF9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        self._create_test_file("video_placeholder.gif", dummy_gif_content, "image/gif", is_media=True) # libmagic identifies GIF as image

        # A file that python-magic might not recognize or recognize as application/octet-stream
        self._create_test_file("unknown.dat", b"\x00\x01\x02\x03\x04\x05", "application/octet-stream")


    def _create_test_file(self, name, content, mime_type, is_media=False, in_subdir=False):
        if in_subdir:
            dir_path = os.path.join(self.storage_path, "subdir")
            os.makedirs(dir_path, exist_ok=True)
            file_path = os.path.join(dir_path, name)
        else:
            file_path = os.path.join(self.storage_path, name)

        with open(file_path, "wb") as f:
            f.write(content)

        sha256 = hashlib.sha256(content).hexdigest()
        self.test_files[name] = {
            "path": file_path,
            "content": content,
            "sha256": sha256,
            "mime": mime_type,
            "is_media": is_media
        }

    def tearDown(self):
        self.test_dir.cleanup()

    def test_get_mime_type(self):
        # Test with a known PNG
        png_path = self.test_files["image.png"]["path"]
        mime = file_scanner.get_mime_type(png_path)
        # python-magic might return 'image/x-png' on some systems
        self.assertTrue(mime == "image/png" or mime == "image/x-png")

        # Test with a known text file
        txt_path = self.test_files["test.txt"]["path"]
        mime = file_scanner.get_mime_type(txt_path)
        self.assertEqual(mime, "text/plain")

        # Test with non-existent file
        mime = file_scanner.get_mime_type("non_existent_file_for_mime_test.txt")
        self.assertIsNone(mime)


    def test_calculate_sha256_existing_file(self):
        png_info = self.test_files["image.png"]
        sha256 = file_scanner.calculate_sha256(png_info["path"])
        self.assertEqual(sha256, png_info["sha256"])

    def test_calculate_sha256_non_existing_file(self):
        sha256 = file_scanner.calculate_sha256("non_existent_file_for_sha_test.txt")
        self.assertIsNone(sha256)

    def test_scan_directory_empty(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            result = file_scanner.scan_directory(empty_dir)
            self.assertEqual(result, {})

    def test_scan_directory_filters_media_files(self):
        expected_map = {}
        for name, info in self.test_files.items():
            if info["is_media"]:
                if info["sha256"] not in expected_map:
                    expected_map[info["sha256"]] = []
                expected_map[info["sha256"]].append(info["path"])

        for sha_key in expected_map: # Sort for consistent comparison
            expected_map[sha_key].sort()

        result = file_scanner.scan_directory(self.storage_path)
        for sha_key in result: # Sort for consistent comparison
            result[sha_key].sort()

        self.assertEqual(result, expected_map)

        # Explicitly check that non-media files are not present
        txt_sha = self.test_files["test.txt"]["sha256"]
        self.assertNotIn(txt_sha, result)

        dat_sha = self.test_files["unknown.dat"]["sha256"]
        self.assertNotIn(dat_sha, result)


    def test_scan_directory_invalid_directory(self):
        result = file_scanner.scan_directory("non_existent_directory_scan_test")
        self.assertEqual(result, {})

if __name__ == '__main__':
    unittest.main()
