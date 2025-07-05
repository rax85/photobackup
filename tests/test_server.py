import unittest
import json
import tempfile
import os
import hashlib
import threading
import time
import requests
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

        # Create dummy files for testing the /list endpoint
        cls.file1_content = b"Hello from server test file1"
        cls.file1_path = os.path.join(cls.storage_path, "server_file1.txt")
        with open(cls.file1_path, "wb") as f:
            f.write(cls.file1_content)
        cls.file1_sha256 = hashlib.sha256(cls.file1_content).hexdigest()

        cls.file2_content = b"Hello from server test file2"
        cls.file2_path = os.path.join(cls.storage_path, "sub", "server_file2.txt")
        os.makedirs(os.path.dirname(cls.file2_path), exist_ok=True)
        with open(cls.file2_path, "wb") as f:
            f.write(cls.file2_content)
        cls.file2_sha256 = hashlib.sha256(cls.file2_content).hexdigest()

        # Expected map for /list endpoint
        cls.expected_file_map = {
            cls.file1_sha256: [cls.file1_path],
            cls.file2_sha256: [cls.file2_path]
        }

        # Start the server in a separate thread
        # Store original flag values
        cls.original_port = FLAGS.port
        cls.original_storage_dir = FLAGS.storage_dir

        FLAGS.port = cls.port
        FLAGS.storage_dir = cls.storage_path

        # The server's file_map is global; we need to ensure it's updated for the test
        server_main.file_map = file_scanner.scan_directory(cls.storage_path)

        cls.server_thread = threading.Thread(target=server_main.run_server, args=(cls.port, cls.storage_path), daemon=True)
        cls.server_thread.start()
        time.sleep(0.5) # Give the server a moment to start

    @classmethod
    def tearDownClass(cls):
        cls.test_dir.cleanup()
        # Restore original flag values
        FLAGS.port = cls.original_port
        FLAGS.storage_dir = cls.original_storage_dir
        # Note: Stopping a http.server running `serve_forever` is tricky without modifying the server code.
        # Since it's a daemon thread, it will exit when the main thread (test runner) exits.
        # For more robust cleanup, the server would need a shutdown mechanism.

    def test_list_api(self):
        try:
            response = requests.get(f"http://localhost:{self.port}/list")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Content-Type'], 'application/json')

            # Sort lists in both expected and actual for consistent comparison
            actual_map = response.json()
            for key in actual_map:
                actual_map[key].sort()

            expected_map_sorted = {}
            for key, value in self.expected_file_map.items():
                expected_map_sorted[key] = sorted(value)

            self.assertEqual(actual_map, expected_map_sorted)
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
