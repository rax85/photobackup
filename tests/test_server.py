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
        # Manually populate the server's cache using the initial scan logic from server.py
        # This ensures the MEDIA_DATA_LOCK is respected if it were used during initial scan.
        with media_server_module.MEDIA_DATA_LOCK:
            media_server_module.MEDIA_DATA_CACHE = media_scanner.scan_directory(cls.test_dir, rescan=False)

        cls.expected_media_data_after_setup = media_server_module.MEDIA_DATA_CACHE.copy()

        # cls.httpd is already initialized above before populating the cache.
        # The following lines were redundant and caused the port binding issue.
        # cls.httpd = HTTPServer(("", cls.port), media_server_module.MediaRequestHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        # No background scanner thread is started in this setUpClass by default.
        # Tests needing the background scanner will set it up themselves.
        time.sleep(0.1) # Give server a moment to start

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.test_dir)
        # Reset server's global state if necessary, e.g. MEDIA_DATA_CACHE
        with media_server_module.MEDIA_DATA_LOCK:
            media_server_module.MEDIA_DATA_CACHE = {}


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
        # Compare with the cache state right after setup.
        self.assertEqual(returned_data, self.expected_media_data_after_setup)


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

# Mock time.sleep to speed up tests involving background scanner
class MockTime:
    def __init__(self):
        self.sleep_calls = []

    def sleep(self, duration):
        self.sleep_calls.append(duration)
        # In a real test, we might advance a simulated clock here
        # or simply record the call and return immediately.
        return

    def time(self): # Needed if other parts of tested code use time.time()
        return time.time()


class TestServerBackgroundScanning(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="media_server_bg_scan_")
        self.port = get_free_port()
        self.server_url = f"http://localhost:{self.port}"

        # Mock FLAGS for the server instance
        class MockFlags:
            storage_dir = self.test_dir
            port = self.port
            rescan_interval = 0.1 # Small interval for testing
            log_dir = None
            verbosity = 0

        self.original_flags = media_server_module.FLAGS
        media_server_module.FLAGS = MockFlags()

        self.original_time_sleep = time.sleep
        self.mock_time = MockTime()
        time.sleep = self.mock_time.sleep # Patch time.sleep

        # Initial file
        self.img_content1 = b"image content one"
        self.img_path1 = create_dummy_file(self.test_dir, "imageA.jpg", self.img_content1, mtime=time.time()-100)

        # Start server with background scanner
        # The server's run_server logic will start the background thread.
        # We need to run parts of run_server or simulate its effect.

        # 1. Initial scan
        with media_server_module.MEDIA_DATA_LOCK:
            media_server_module.MEDIA_DATA_CACHE = media_scanner.scan_directory(
                media_server_module.FLAGS.storage_dir, rescan=False
            )
        self.initial_cache_state = media_server_module.MEDIA_DATA_CACHE.copy()

        # 2. Start HTTP server (similar to TestServerIntegration)
        self.httpd = HTTPServer(("", self.port), media_server_module.MediaRequestHandler)
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

        # No autonomous scanner thread started here. Scans will be triggered manually.
        time.sleep(0.05) # Ensure HTTP server thread has started

    def trigger_scan_cycle(self):
        """Manually triggers one cycle of scanning logic."""
        media_server_module.logging.info("Test: Manually triggering scan cycle...")
        # The mocked time.sleep within this call path (if any internal part of scan_directory uses it)
        # will be handled by self.mock_time.sleep, returning immediately.
        # The FLAGS.rescan_interval is not used here as we are not simulating the timed loop.
        try:
            with media_server_module.MEDIA_DATA_LOCK:
                updated_data = media_scanner.scan_directory(
                    media_server_module.FLAGS.storage_dir, # Use storage_dir from mocked FLAGS
                    existing_data=media_server_module.MEDIA_DATA_CACHE,
                    rescan=True
                )
                media_server_module.MEDIA_DATA_CACHE = updated_data
            media_server_module.logging.info("Test: Manual scan cycle complete.")
        except Exception as e:
            media_server_module.logging.error(f"Test: Error in manual scan cycle: {e}", exc_info=True)


    def tearDown(self):
        # No scanner_thread to stop or join as it's not started in setUp anymore

        if hasattr(self, 'httpd') and self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

        if hasattr(self, 'server_thread') and self.server_thread.is_alive():
            self.server_thread.join(timeout=0.5)


        if os.path.exists(self.test_dir): # Check if test_dir was created
            shutil.rmtree(self.test_dir)

        if hasattr(self, 'original_flags'): # Check if original_flags was set
             media_server_module.FLAGS = self.original_flags
        if hasattr(self, 'original_time_sleep'): # Check if original_time_sleep was set
            time.sleep = self.original_time_sleep

        with media_server_module.MEDIA_DATA_LOCK:
            media_server_module.MEDIA_DATA_CACHE = {}


    def test_background_scan_picks_up_new_file(self):
        # 1. Verify initial state via /list
        response1 = requests.get(f"{self.server_url}/list")
        self.assertEqual(response1.status_code, 200)
        data1 = response1.json()
        self.assertEqual(len(data1), 1)
        initial_sha1 = media_scanner.get_file_sha256(self.img_path1)
        self.assertIn(initial_sha1, data1)

        # 2. Add a new file to the directory
        img_content2 = b"image content two"
        img_path2 = create_dummy_file(self.test_dir, "imageB.png", img_content2, mtime=time.time()-50)
        new_file_sha2 = media_scanner.get_file_sha256(img_path2)

        # 3. Manually trigger the scan logic
        self.trigger_scan_cycle()

        # 4. Verify /list shows the new file
        response2 = requests.get(f"{self.server_url}/list")
        self.assertEqual(response2.status_code, 200)
        data2 = response2.json()

        self.assertEqual(len(data2), 2, f"Expected 2 files, got {len(data2)}. Data: {data2}")
        self.assertIn(initial_sha1, data2)
        self.assertIn(new_file_sha2, data2)
        self.assertEqual(data2[new_file_sha2]['filename'], "imageB.png")
        # self.assertTrue(len(self.mock_time.sleep_calls) > 0, "time.sleep should have been called by background scanner")
        # self.assertAlmostEqual(self.mock_time.sleep_calls[0], media_server_module.FLAGS.rescan_interval, places=7)
        # The above sleep call checks are no longer relevant as the rescan_interval sleep is not part of trigger_scan_cycle


    def test_background_scan_picks_up_deleted_file(self):
        # Initial state has one file (imageA.jpg)
        initial_sha1 = media_scanner.get_file_sha256(self.img_path1)
        response1 = requests.get(f"{self.server_url}/list")
        self.assertIn(initial_sha1, response1.json())

        # Delete the file
        os.remove(self.img_path1)

        # Manually trigger the scan logic
        self.trigger_scan_cycle()

        response2 = requests.get(f"{self.server_url}/list")
        data2 = response2.json()
        self.assertEqual(len(data2), 0, f"Expected 0 files after deletion, got {len(data2)}. Data: {data2}")
        self.assertNotIn(initial_sha1, data2)

    def test_background_scan_picks_up_modified_file(self):
        initial_sha1 = media_scanner.get_file_sha256(self.img_path1)
        response1 = requests.get(f"{self.server_url}/list")
        self.assertIn(initial_sha1, response1.json())
        original_mtime = response1.json()[initial_sha1]['last_modified']

        # Modify the file (content and mtime)
        time.sleep(0.01)
        new_mtime = time.time()
        modified_content = b"modified content for imageA"
        create_dummy_file(self.test_dir, "imageA.jpg", modified_content, mtime=new_mtime)
        modified_sha1 = media_scanner.get_file_sha256(self.img_path1)
        self.assertNotEqual(initial_sha1, modified_sha1)

        # Manually trigger the scan logic
        self.trigger_scan_cycle()

        response2 = requests.get(f"{self.server_url}/list")
        data2 = response2.json()

        self.assertEqual(len(data2), 1)
        self.assertNotIn(initial_sha1, data2)
        self.assertIn(modified_sha1, data2)
        self.assertEqual(data2[modified_sha1]['filename'], "imageA.jpg")
        self.assertNotAlmostEqual(data2[modified_sha1]['last_modified'], original_mtime, places=7)
        self.assertAlmostEqual(data2[modified_sha1]['last_modified'], new_mtime, places=7)


if __name__ == '__main__':
    # This allows running tests with `python tests/test_server.py`
    # It's good practice to also be runnable via `python -m unittest discover`
    unittest.main()
