import unittest
import json
import tempfile
import os
import hashlib
import threading
import time
import requests
import socketserver # <--- Add this import
from absl import flags
from rest_server import main as server_main
from rest_server.lib import file_scanner

import sys # Add this import
# It's good practice to reset flags if they are manipulated in tests,
# especially if tests might run in the same process.
FLAGS = flags.FLAGS

class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure flags are parsed, passing only the program name
        if not FLAGS.is_parsed():
            FLAGS([sys.argv[0]])

        cls.test_dir = tempfile.TemporaryDirectory()
        cls.storage_path = cls.test_dir.name
        cls.port = 8081 # Use a different port for testing

        cls.test_media_files = {}

        # Dummy PNG image file for server test
        png_magic = b"\x89PNG\r\n\x1a\n"
        ihdr_data = b"\x00\x00\x00\x0dIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x01\x00\x00\x00\x00"
        ihdr_crc = b"\x37\x23\x0D\x8F"
        ihdr_chunk = ihdr_data + ihdr_crc
        idat_data = b"\x00\x00\x00\x00IDAT"
        idat_crc = b"\x78\x59\x06\x53"
        idat_chunk = idat_data + idat_crc
        iend_chunk = b"\x00\x00\x00\x00IEND\xAEB`\x82"
        dummy_png_content_server = png_magic + ihdr_chunk + idat_chunk + iend_chunk
        cls._create_server_test_file("server_image.png", dummy_png_content_server, "image/png")

        # Dummy GIF file for server test
        dummy_gif_content_server = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xFF\xFF\xFF!\xF9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        cls._create_server_test_file("server_image.gif", dummy_gif_content_server, "image/gif", in_subdir=True)

        # Text file (should be ignored by the server's scan)
        cls._create_server_test_file("server_text.txt", b"This is a text file for server test.", "text/plain", is_media=False)

        # Expected map for /list endpoint - only media files
        cls.expected_file_map = {}
        for name, info in cls.test_media_files.items():
            if info["is_media"]:
                file_data = {
                    "filepath": info["path"],
                    "last_modified": info["last_modified"]
                }
                if info["sha256"] not in cls.expected_file_map:
                    cls.expected_file_map[info["sha256"]] = []
                cls.expected_file_map[info["sha256"]].append(file_data)

        for sha_key in cls.expected_file_map: # Sort lists of dicts by filepath for consistent comparison
             cls.expected_file_map[sha_key].sort(key=lambda x: x["filepath"])


        # Start the server in a separate thread
        # Store original flag values
        cls.original_port = FLAGS.port
        cls.original_storage_dir = FLAGS.storage_dir

        FLAGS.port = cls.port
        FLAGS.storage_dir = cls.storage_path

        # The server's file_map is global; we need to ensure it's updated for the test
        # This is done by run_server, but we'll manage the server instance directly.
        # server_main.file_map = file_scanner.scan_directory(cls.storage_path)

        # Allow address reuse
        socketserver.TCPServer.allow_reuse_address = True
        try:
            cls.httpd = socketserver.TCPServer(("", cls.port), server_main.Handler)
        except Exception as e:
            # If server setup fails, make sure to clean up the temp directory
            cls.test_dir.cleanup()
            raise e

        # Update the global file_map that the Handler will use
        # This needs to be done before the server thread starts serving requests
        server_main.file_map = file_scanner.scan_directory(cls.storage_path)


        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5) # Give the server a moment to start

    @classmethod
    def _create_server_test_file(cls, name, content, mime_type, is_media=True, in_subdir=False):
        if in_subdir:
            dir_path = os.path.join(cls.storage_path, "sub_server") # different subdir to avoid collision with file_scanner tests
            os.makedirs(dir_path, exist_ok=True)
            file_path = os.path.join(dir_path, name)
        else:
            file_path = os.path.join(cls.storage_path, name)

        with open(file_path, "wb") as f:
            f.write(content)

        sha256 = hashlib.sha256(content).hexdigest()

        predictable_mtime = 1678886401.0 # Slightly different from file_scanner test for distinction
        os.utime(file_path, (os.path.getatime(file_path), predictable_mtime))

        # Store info about the created file, useful for constructing the expected_file_map
        cls.test_media_files[name] = {
            "path": file_path,
            "sha256": sha256,
            "is_media": mime_type.startswith("image/") or mime_type.startswith("video/"), # Determine based on actual mime
            "last_modified": predictable_mtime
        }


    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'httpd') and cls.httpd:
            cls.httpd.shutdown() # Signal serve_forever loop to stop
            cls.httpd.server_close() # Close the server socket

        # Wait for the server thread to finish
        if hasattr(cls, 'server_thread') and cls.server_thread:
            cls.server_thread.join(timeout=1.0) # Wait for up to 1 second

        if hasattr(cls, 'test_dir'): # Ensure test_dir exists before cleanup
            cls.test_dir.cleanup()

        # Restore original flag values
        FLAGS.port = cls.original_port
        FLAGS.storage_dir = cls.original_storage_dir


    def test_list_api(self):
        try:
            response = requests.get(f"http://localhost:{self.port}/list")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Content-Type'], 'application/json')

            # Sort lists in both expected and actual for consistent comparison
            actual_map_raw = response.json()

            # Sort lists of dicts by filepath in actual_map_raw for consistent comparison
            actual_map_sorted = {}
            for sha_key, files_list in actual_map_raw.items():
                actual_map_sorted[sha_key] = sorted(files_list, key=lambda x: x["filepath"])

            # self.expected_file_map is already sorted by filepath during setup

            # Custom comparison for lists of dictionaries
            self.assertEqual(len(actual_map_sorted), len(self.expected_file_map))
            for sha_key, expected_files_list in self.expected_file_map.items():
                self.assertIn(sha_key, actual_map_sorted)
                actual_files_list = actual_map_sorted[sha_key]
                self.assertEqual(len(actual_files_list), len(expected_files_list))
                for i, expected_file_info in enumerate(expected_files_list):
                    actual_file_info = actual_files_list[i]
                    self.assertEqual(actual_file_info["filepath"], expected_file_info["filepath"])
                    # Timestamps from JSON will be floats, compare them with assertAlmostEqual
                    self.assertAlmostEqual(actual_file_info["last_modified"], expected_file_info["last_modified"], places=5)

        except requests.exceptions.ConnectionError as e:
            self.fail(f"Failed to connect to the test server: {e}")


    def test_not_found_api(self):
        try:
            response = requests.get(f"http://localhost:{self.port}/nonexistent")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.text, "Not Found")
        except requests.exceptions.ConnectionError as e:
            self.fail(f"Failed to connect to the test server: {e}")


if __name__ == '__main__':
    # This allows running tests with `python tests/test_server.py`
    # It's important to parse flags if your main app uses them, even in tests.
    # However, server_main.main itself calls app.run which handles flags.
    # For direct invocation of run_server, we manually set flags.
    unittest.main()
