import unittest
import os
import shutil
import tempfile
import json
import threading
import time
import requests # For making HTTP requests
from http.server import HTTPServer
import socket # To find a free port

# Add project root to sys.path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from media_server import server as media_server_module # aliasing to avoid conflict
from media_server import media_scanner # To get expected data

# Helper to create dummy files (copied from test_media_scanner for independence if needed)
def create_dummy_file(dir_path, filename, content="dummy content", mtime=None):
    filepath = os.path.join(dir_path, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
        f.write(content)
    if mtime is not None:
        os.utime(filepath, (mtime, mtime))
    return filepath

def get_free_port():
    """Finds and returns an available port number."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

class TestServerIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="media_server_int_test_")
        cls.port = get_free_port()
        cls.server_url = f"http://localhost:{cls.port}"

        # Create some dummy media files
        cls.img1_content = b"dummy image 1 content"
        cls.img1_path = create_dummy_file(cls.test_dir, "image1.jpg", cls.img1_content)
        cls.vid1_content = b"dummy video 1 content"
        cls.vid1_path = create_dummy_file(cls.test_dir, "video1.mp4", cls.vid1_content)
        create_dummy_file(cls.test_dir, "notes.txt", "not a media file") # Non-media file

        # Pre-calculate expected data
        cls.expected_media_data = media_scanner.scan_directory(cls.test_dir)

        # Start the server in a separate thread
        # Mock FLAGS for the server instance
        class MockFlags:
            def __init__(self, storage_dir, port):
                self.storage_dir = storage_dir
                self.port = port
                self.log_dir = None # Add any other flags server expects with default values
                self.verbosity = 0 # Example, adjust if server uses it

        media_server_module.FLAGS = MockFlags(cls.test_dir, cls.port)

        # The server's run_server function populates its own MEDIA_DATA_CACHE
        # We need to ensure this happens before the httpd server starts serving requests.
        # The current server.py structure does this sequentially.

        cls.httpd = HTTPServer(("", cls.port), media_server_module.MediaRequestHandler)
        # Manually populate the server's cache for the test handler instance
        # This is because MediaRequestHandler gets MEDIA_DATA_CACHE at class level / module level
        # and we're running scan_directory in run_server context for the main thread.
        # For testing, we directly set what the handler would see.
        media_server_module.MEDIA_DATA_CACHE = cls.expected_media_data

        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1) # Give server a moment to start

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        # cls.server_thread.join() # Daemon thread will exit automatically
        shutil.rmtree(cls.test_dir)
        # Restore original FLAGS if they were globally patched and it matters for other tests
        # For absl, it's usually managed per app.run, so direct patch might be tricky.
        # Here, we assigned to media_server_module.FLAGS, which is fine.

    def test_list_endpoint_success(self):
        """Test successful GET request to /list."""
        response = requests.get(f"{self.server_url}/list")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/json')

        returned_data = response.json()
        self.assertEqual(len(returned_data), 2) # Expecting two media files

        # Verify content (hashes should match, filenames and timestamps)
        # The structure is {hash: {'filename': ..., 'last_modified': ...}}
        # We can compare it with our pre-calculated expected_media_data

        # Normalize timestamps for comparison as JSON float precision might differ slightly
        # from os.path.getmtime float precision.
        # However, since we populate MEDIA_DATA_CACHE directly from scan_directory output,
        # they should be identical.

        self.assertEqual(returned_data, self.expected_media_data)


    def test_invalid_path_returns_404(self):
        """Test GET request to an invalid path."""
        response = requests.get(f"{self.server_url}/invalid_path")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers['Content-Type'], 'text/plain')
        self.assertIn(b"Error 404: Not Found", response.content)

    def test_server_startup_with_empty_directory(self):
        """Test server behavior when storage_dir is empty."""
        empty_dir = tempfile.mkdtemp(prefix="media_server_empty_")
        current_test_port = get_free_port() # Renamed to avoid conflict with cls.port or other scopes

        class MockFlagsEmpty:
            storage_dir = empty_dir
            port = current_test_port # Use the correctly defined port for this test
            log_dir = None
            verbosity = 0

        original_flags = media_server_module.FLAGS
        media_server_module.FLAGS = MockFlagsEmpty

        # Manually trigger the scan and cache update for this specific test case
        # This simulates what app.run -> run_server would do
        temp_cache = media_scanner.scan_directory(empty_dir)

        # Temporarily override the global cache for the handler.
        original_cache = media_server_module.MEDIA_DATA_CACHE
        media_server_module.MEDIA_DATA_CACHE = temp_cache

        httpd_empty = HTTPServer(("", current_test_port), media_server_module.MediaRequestHandler)
        thread_empty = threading.Thread(target=httpd_empty.serve_forever, daemon=True)
        thread_empty.start()
        time.sleep(0.1)

        response = requests.get(f"http://localhost:{current_test_port}/list")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {}) # Expect empty JSON object

        httpd_empty.shutdown()
        httpd_empty.server_close()
        shutil.rmtree(empty_dir)

        # Restore original flags and cache for other tests
        media_server_module.FLAGS = original_flags
        media_server_module.MEDIA_DATA_CACHE = original_cache


if __name__ == '__main__':
    # This allows running tests with `python tests/test_server.py`
    # It's good practice to also be runnable via `python -m unittest discover`
    unittest.main()
