import unittest
import os
import shutil
import tempfile
import json
import time
from unittest import mock
import io # For BytesIO for file uploads
import hashlib # For SHA256 verification
from datetime import datetime # For checking YYYYMMDD subdirectories

# Add project root to sys.path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the Flask app instance from the server module
from media_server.server import app as flask_app # aliasing to avoid conflict
from media_server.server import MEDIA_DATA_CACHE, MEDIA_DATA_LOCK, reset_media_data_cache # Direct access for tests
from media_server import media_scanner # To get expected data
from media_server import server as media_server_module # For FLAGS access
from PIL import Image # For creating dummy image files

# Helper to create dummy files
def create_dummy_file(dir_path, filename, content="dummy content", mtime=None, image_details=None):
    filepath = os.path.join(dir_path, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if image_details:
        try:
            img = Image.new(image_details.get('mode', 'RGB'),
                            image_details.get('size', (100,100)),
                            image_details.get('color', 'blue'))
            # For thumbnail tests, format needs to be one that media_scanner can make a thumb from (e.g. JPEG, PNG)
            img.save(filepath, image_details.get('format', 'JPEG'))
        except Exception as e:
            # Fallback to simple file if image creation fails
            with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
                f.write(content if content else b"image creation failed")
    else:
        with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
            f.write(content)

    if mtime is not None:
        os.utime(filepath, (mtime, mtime))
    return filepath

class TestServerFlaskIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Ensure absl flags are parsed. This is crucial for accessing FLAGS.storage_dir etc.
        # In a test environment, absl_app.run() isn't called the same way.
        if not media_server_module.FLAGS.is_parsed():
            # Provide a default value for storage_dir for parsing,
            # it will be overridden by test-specific values later.
            # Using a dummy executable name for argv[0]
            media_server_module.FLAGS([sys.argv[0], '--storage_dir=/tmp/dummy_for_parse'])

        cls.test_dir = tempfile.mkdtemp(prefix="media_server_flask_test_")

        # Configure Flask app for testing
        flask_app.config['TESTING'] = True
        flask_app.config['STORAGE_DIR'] = cls.test_dir
        # Ensure THUMBNAIL_DIR is also configured if other parts of app use it
        flask_app.config['THUMBNAIL_DIR'] = os.path.join(cls.test_dir, media_scanner.THUMBNAIL_DIR_NAME)


        # Set absl flags used by the server module (especially for initial scan and background scanner)
        # These flags are read by run_flask_app and background_scanner_task
        media_server_module.FLAGS.storage_dir = cls.test_dir
        media_server_module.FLAGS.port = 8000 # Port not really used by test_client
        media_server_module.FLAGS.rescan_interval = 0 # Disable background scanner for most tests

        # Create some dummy media files
        # This one will be a basic text file, media_scanner won't make a thumbnail
        cls.txt_file_content = b"dummy text file content"
        cls.txt_file_path = create_dummy_file(cls.test_dir, "textfile.txt", cls.txt_file_content)

        # This one will be a basic video-like file (by extension), no actual video content
        # media_scanner won't make a thumbnail for this based on current logic (only for images)
        cls.vid1_content = b"dummy video 1 content"
        cls.vid1_path = create_dummy_file(cls.test_dir, "video1.mp4", cls.vid1_content)

        # This one is an actual image, for which a thumbnail should be generated
        cls.img1_path = create_dummy_file(
            cls.test_dir, "image1.jpg",
            image_details={'size': (120, 80), 'color': 'red', 'format': 'JPEG'}
        )
        # Non-media file
        create_dummy_file(cls.test_dir, "notes.txt", "not a media file")


        # Perform initial scan to populate MEDIA_DATA_CACHE, simulating server startup
        # This scan will also generate thumbnails for image1.jpg
        reset_media_data_cache() # Ensure cache is clean before class setup populates it
        # The scan_directory is called without MEDIA_DATA_LOCK here because it's class setup,
        # not concurrent execution. The function itself doesn't lock MEDIA_DATA_CACHE.
        # The update to MEDIA_DATA_CACHE should be locked if there's any theoretical concurrency.
        # However, for test setup, direct assignment after reset is fine.
        initial_scan_data = media_scanner.scan_directory(cls.test_dir, rescan=False)
        with MEDIA_DATA_LOCK:
            MEDIA_DATA_CACHE.update(initial_scan_data)

        cls.expected_media_data_after_setup = initial_scan_data.copy() # Store the data, not the cache reference
        # Store the SHA256 of the image for thumbnail tests
        cls.img1_sha256 = None
        for sha, data in cls.expected_media_data_after_setup.items():
            if data['filename'] == "image1.jpg":
                cls.img1_sha256 = sha
                break
        assert cls.img1_sha256 is not None, "Failed to get SHA256 for test image image1.jpg"

        # Store SHA256 for the video file (no thumbnail expected)
        cls.vid1_sha256 = None
        for sha, data in cls.expected_media_data_after_setup.items():
            if data['filename'] == "video1.mp4":
                cls.vid1_sha256 = sha
                break
        assert cls.vid1_sha256 is not None, "Failed to get SHA256 for test video video1.mp4"

        cls.client = flask_app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir)
        reset_media_data_cache() # Clean up after all tests in the class
        # Reset any flags if necessary, though absl flags are tricky to reset fully.

    def setUp(self):
        # Ensure cache is in a known state before each test.
        # Reset and then populate with the specific state needed for this test class.
        reset_media_data_cache()
        with MEDIA_DATA_LOCK:
            # MEDIA_DATA_CACHE should be clean here due to reset_media_data_cache()
            # Populate it with the data prepared during setUpClass
            MEDIA_DATA_CACHE.update(self.expected_media_data_after_setup)


    def test_list_endpoint_success(self):
        """Test successful GET request to /list."""
        response = self.client.get('/list')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'application/json')

        returned_data = response.json
        self.assertEqual(len(returned_data), 2) # Expecting two media files
        self.assertEqual(returned_data, self.expected_media_data_after_setup)

    def test_invalid_path_returns_404(self):
        """Test GET request to an invalid path."""
        response = self.client.get('/invalid_path')
        self.assertEqual(response.status_code, 404)
        # Flask's default 404 is HTML, but with jsonify for actual endpoints,
        # a JSON 404 might be configured. For now, test default.
        # For API consistency, one might add a @app.errorhandler(404) to return JSON.

    def test_get_thumbnail_success(self):
        """Test successfully retrieving an existing thumbnail."""
        self.assertIsNotNone(self.img1_sha256, "Test setup error: img1_sha256 not set.")
        # Ensure the thumbnail file actually exists where it should be
        thumb_path = os.path.join(flask_app.config['THUMBNAIL_DIR'], f"{self.img1_sha256}{media_scanner.THUMBNAIL_EXTENSION}")
        self.assertTrue(os.path.exists(thumb_path), f"Thumbnail file {thumb_path} does not exist. Scan/generation issue?")

        response = self.client.get(f'/thumbnail/{self.img1_sha256}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'image/png')
        self.assertTrue(len(response.data) > 0, "Thumbnail data should not be empty.")

    def test_get_thumbnail_not_found_for_video(self):
        """Test 404 for a media type that doesn't generate thumbnails (e.g., video)."""
        self.assertIsNotNone(self.vid1_sha256, "Test setup error: vid1_sha256 not set.")
        # Ensure the thumbnail file does NOT exist for the video
        thumb_path = os.path.join(flask_app.config['THUMBNAIL_DIR'], f"{self.vid1_sha256}{media_scanner.THUMBNAIL_EXTENSION}")
        self.assertFalse(os.path.exists(thumb_path), f"Thumbnail file {thumb_path} should not exist for a video.")

        response = self.client.get(f'/thumbnail/{self.vid1_sha256}')
        self.assertEqual(response.status_code, 404)

    def test_get_thumbnail_not_found_sha_unknown(self):
        """Test 404 for a correctly formatted but unknown SHA256."""
        unknown_sha = "a" * 64 # Valid format, but unlikely to exist
        response = self.client.get(f'/thumbnail/{unknown_sha}')
        self.assertEqual(response.status_code, 404)

    def test_get_thumbnail_invalid_sha_format_too_short(self):
        response = self.client.get('/thumbnail/12345')
        self.assertEqual(response.status_code, 400)

    def test_get_thumbnail_invalid_sha_format_too_long(self):
        response = self.client.get('/thumbnail/' + 'a' * 65)
        self.assertEqual(response.status_code, 400)

    def test_get_thumbnail_invalid_sha_format_non_hex(self):
        response = self.client.get('/thumbnail/' + 'g' * 64) # 'g' is not a hex character
        self.assertEqual(response.status_code, 400)

    def test_get_thumbnail_when_thumbnail_dir_missing(self):
        """Test 404 if the .thumbnails directory itself is missing."""
        # This test requires altering the server's view of the thumbnail directory
        # or creating a situation where it's not there.
        original_thumbnail_dir = flask_app.config['THUMBNAIL_DIR']
        temp_non_existent_thumb_dir = os.path.join(self.test_dir, ".nonexistentthumbnails")
        flask_app.config['THUMBNAIL_DIR'] = temp_non_existent_thumb_dir # Point to a dir that won't exist

        # Ensure the directory does not exist
        if os.path.exists(temp_non_existent_thumb_dir):
            shutil.rmtree(temp_non_existent_thumb_dir)

        response = self.client.get(f'/thumbnail/{self.img1_sha256}')
        self.assertEqual(response.status_code, 404) # Server should see dir missing

        # Restore original config
        flask_app.config['THUMBNAIL_DIR'] = original_thumbnail_dir


    def test_server_startup_with_empty_directory(self):
        """Test server behavior when storage_dir is empty."""
        empty_dir = tempfile.mkdtemp(prefix="media_server_empty_")

        # Temporarily change app config for this test
        original_storage_dir_flag = media_server_module.FLAGS.storage_dir
        original_storage_dir_app_config = flask_app.config['STORAGE_DIR']

        media_server_module.FLAGS.storage_dir = empty_dir
        flask_app.config['STORAGE_DIR'] = empty_dir # Important for scan_directory
        flask_app.config['THUMBNAIL_DIR'] = os.path.join(empty_dir, media_scanner.THUMBNAIL_DIR_NAME)


        reset_media_data_cache() # Clear current cache
        # Simulate initial scan for the empty directory
        # scan_directory itself doesn't write to global MEDIA_DATA_CACHE
        empty_scan_data = media_scanner.scan_directory(empty_dir, rescan=False)
        with MEDIA_DATA_LOCK: # Update global cache if server logic relies on it being pre-populated
            MEDIA_DATA_CACHE.update(empty_scan_data)


        response = self.client.get('/list')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {}) # Expect empty JSON object

        shutil.rmtree(empty_dir)

        # Restore original config and cache state for other tests
        media_server_module.FLAGS.storage_dir = original_storage_dir_flag
        flask_app.config['STORAGE_DIR'] = original_storage_dir_app_config
        with MEDIA_DATA_LOCK: # Restore main cache
            MEDIA_DATA_CACHE.clear()
            MEDIA_DATA_CACHE.update(self.expected_media_data_after_setup)


class TestServerFlaskBackgroundScanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure absl flags are parsed for this test class as well.
        if not media_server_module.FLAGS.is_parsed():
            media_server_module.FLAGS([sys.argv[0], '--storage_dir=/tmp/dummy_for_bg_parse'])

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="media_server_bg_scan_flask_")

        flask_app.config['TESTING'] = True
        flask_app.config['STORAGE_DIR'] = self.test_dir
        self.client = flask_app.test_client()

        # Set absl flags for this test suite
        self.original_flags_storage_dir = media_server_module.FLAGS.storage_dir
        self.original_flags_rescan_interval = media_server_module.FLAGS.rescan_interval

        media_server_module.FLAGS.storage_dir = self.test_dir
        # rescan_interval is for the thread, not directly used by manual trigger.
        media_server_module.FLAGS.rescan_interval = 0.01

        # Initial file
        self.img_content1 = b"image content one"
        self.img_path1 = create_dummy_file(self.test_dir, "imageA.jpg", self.img_content1, mtime=time.time()-100)

        # Initial scan
        reset_media_data_cache()
        # The app.config['STORAGE_DIR'] is self.test_dir, set in setUp
        # The app.config['THUMBNAIL_DIR'] also needs to be set for scan_directory to work correctly
        flask_app.config['THUMBNAIL_DIR'] = os.path.join(self.test_dir, media_scanner.THUMBNAIL_DIR_NAME)
        initial_scan_data = media_scanner.scan_directory(self.test_dir, rescan=False)
        with MEDIA_DATA_LOCK:
            MEDIA_DATA_CACHE.update(initial_scan_data)
        self.initial_cache_state = initial_scan_data.copy()


    def trigger_scan_cycle(self):
        """Manually triggers one cycle of scanning logic."""
        with MEDIA_DATA_LOCK:
            updated_data = media_scanner.scan_directory(
                flask_app.config['STORAGE_DIR'], # Use app.config for consistency
                existing_data=MEDIA_DATA_CACHE,
                rescan=True
            )
            MEDIA_DATA_CACHE.clear()
            MEDIA_DATA_CACHE.update(updated_data)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        # Restore flags
        media_server_module.FLAGS.storage_dir = self.original_flags_storage_dir
        media_server_module.FLAGS.rescan_interval = self.original_flags_rescan_interval
        reset_media_data_cache() # Ensure cache is clean after these tests

    def test_background_scan_picks_up_new_file(self):
        response1 = self.client.get('/list')
        self.assertEqual(response1.status_code, 200)
        data1 = response1.json
        self.assertEqual(len(data1), 1)
        initial_sha1 = media_scanner.get_file_sha256(self.img_path1)
        self.assertIn(initial_sha1, data1)

        img_content2 = b"image content two"
        img_path2 = create_dummy_file(self.test_dir, "imageB.png", img_content2, mtime=time.time()-50)
        new_file_sha2 = media_scanner.get_file_sha256(img_path2)

        self.trigger_scan_cycle()

        response2 = self.client.get('/list')
        self.assertEqual(response2.status_code, 200)
        data2 = response2.json
        self.assertEqual(len(data2), 2)
        self.assertIn(initial_sha1, data2)
        self.assertIn(new_file_sha2, data2)
        self.assertEqual(data2[new_file_sha2]['filename'], "imageB.png")

    def test_background_scan_picks_up_deleted_file(self):
        initial_sha1 = media_scanner.get_file_sha256(self.img_path1)
        response1 = self.client.get('/list')
        self.assertIn(initial_sha1, response1.json)

        os.remove(self.img_path1)
        self.trigger_scan_cycle()

        response2 = self.client.get('/list')
        data2 = response2.json
        self.assertEqual(len(data2), 0)
        self.assertNotIn(initial_sha1, data2)

    def test_background_scan_picks_up_modified_file(self):
        initial_sha1 = media_scanner.get_file_sha256(self.img_path1)
        response1 = self.client.get('/list')
        self.assertIn(initial_sha1, response1.json)
        original_mtime = response1.json[initial_sha1]['last_modified']

        time.sleep(0.01) # Ensure mtime is different
        new_mtime = time.time()
        modified_content = b"modified content for imageA"
        # Re-create the file with new content and mtime
        create_dummy_file(self.test_dir, os.path.basename(self.img_path1), modified_content, mtime=new_mtime)
        modified_sha1 = media_scanner.get_file_sha256(self.img_path1)
        self.assertNotEqual(initial_sha1, modified_sha1)

        self.trigger_scan_cycle()

        response2 = self.client.get('/list')
        data2 = response2.json
        self.assertEqual(len(data2), 1)
        self.assertNotIn(initial_sha1, data2)
        self.assertIn(modified_sha1, data2)
        self.assertEqual(data2[modified_sha1]['filename'], os.path.basename(self.img_path1))
        self.assertNotAlmostEqual(data2[modified_sha1]['last_modified'], original_mtime, places=7)
        # Ensure mtime is close to new_mtime. Precision can vary.
        self.assertAlmostEqual(data2[modified_sha1]['last_modified'], new_mtime, places=2)


if __name__ == '__main__':
    unittest.main()


class TestImageEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not media_server_module.FLAGS.is_parsed():
            media_server_module.FLAGS([sys.argv[0], '--storage_dir=/tmp/dummy_for_img_parse'])

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="media_server_image_test_")
        flask_app.config['TESTING'] = True
        flask_app.config['STORAGE_DIR'] = self.test_dir
        flask_app.config['THUMBNAIL_DIR'] = os.path.join(self.test_dir, media_scanner.THUMBNAIL_DIR_NAME)

        # Ensure .thumbnails directory exists within the temp test_dir
        os.makedirs(flask_app.config['THUMBNAIL_DIR'], exist_ok=True)

        media_server_module.FLAGS.storage_dir = self.test_dir
        media_server_module.FLAGS.rescan_interval = 0

        self.client = flask_app.test_client()

        # Clear cache before each test
        with MEDIA_DATA_LOCK:
            MEDIA_DATA_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        with MEDIA_DATA_LOCK:
            MEDIA_DATA_CACHE.clear()

    def _create_dummy_image_bytes(self, text_content="dummy_image", format="PNG"):
        """Creates dummy image bytes and returns them along with their SHA256 hash."""
        img_byte_arr = io.BytesIO()
        # Create a very simple image using PIL to ensure it's a valid format
        try:
            dummy_pil_img = Image.new('RGB', (100, 50), color = 'blue') # Slightly larger
            # Add some text to make content unique if needed for different SHAs
            from PIL import ImageDraw # Import here, as it's specific to this try block
            draw = ImageDraw.Draw(dummy_pil_img)
            # Use text_content to make image bytes different
            draw.text((10,10), text_content, fill=(255,255,0))
            dummy_pil_img.save(img_byte_arr, format=format.upper())
            img_byte_arr.seek(0)
            content_bytes = img_byte_arr.read()
            img_byte_arr.seek(0) # Reset for upload
            sha256 = hashlib.sha256(content_bytes).hexdigest()
            return img_byte_arr, content_bytes, sha256
        except ImportError: # Fallback if PIL is not available (should be for server, but test safety)
            content_bytes = text_content.encode('utf-8') * 10 # Make it a bit larger
            sha256 = hashlib.sha256(content_bytes).hexdigest()
            return io.BytesIO(content_bytes), content_bytes, sha256


    def test_put_image_success_new_image(self):
        """Test successful upload of a new image."""
        image_name = "test_image.png"
        img_data, img_content_bytes, img_sha256 = self._create_dummy_image_bytes(text_content=image_name)

        response = self.client.put(
            f'/image/{image_name}',
            data={'file': (img_data, image_name)},
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 201)
        json_response = response.json
        self.assertEqual(json_response['sha256'], img_sha256)
        self.assertEqual(json_response['filename'], image_name)

        # Verify file saved in dated subdirectory
        today_str = datetime.now().strftime('%Y%m%d')
        expected_file_dir = os.path.join(self.test_dir, "uploads", today_str)
        expected_file_path = os.path.join(expected_file_dir, image_name)
        self.assertTrue(os.path.exists(expected_file_path))
        with open(expected_file_path, "rb") as f:
            self.assertEqual(f.read(), img_content_bytes)

        # Verify cache
        with MEDIA_DATA_LOCK:
            self.assertIn(img_sha256, MEDIA_DATA_CACHE)
            cache_entry = MEDIA_DATA_CACHE[img_sha256]
            self.assertEqual(cache_entry['filename'], image_name)
            self.assertEqual(cache_entry['original_filename'], image_name)
            self.assertEqual(cache_entry['file_path'], os.path.join("uploads", today_str, image_name))
            self.assertIsNotNone(cache_entry['thumbnail_file'])

        # Verify thumbnail generated
        expected_thumbnail_path = os.path.join(flask_app.config['THUMBNAIL_DIR'], f"{img_sha256}.png")
        self.assertTrue(os.path.exists(expected_thumbnail_path))

    def test_put_image_filename_collision(self):
        """Test filename collision: upload two different images with the same initial filename."""
        image_name = "collision.jpg"
        img_data1, _, img_sha1 = self._create_dummy_image_bytes(text_content="image_v1")
        img_data2, _, img_sha2 = self._create_dummy_image_bytes(text_content="image_v2")
        self.assertNotEqual(img_sha1, img_sha2) # Ensure contents are different

        # Upload first image
        self.client.put(f'/image/{image_name}', data={'file': (img_data1, image_name)}, content_type='multipart/form-data')

        # Upload second image with same desired name
        response = self.client.put(f'/image/{image_name}', data={'file': (img_data2, 'another_original_name.jpg')}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201)
        json_response = response.json

        suffixed_filename = "collision_1.jpg" # Expected suffixed name
        self.assertEqual(json_response['filename'], suffixed_filename)
        self.assertEqual(json_response['sha256'], img_sha2)

        today_str = datetime.now().strftime('%Y%m%d')
        expected_path1 = os.path.join(self.test_dir, "uploads", today_str, image_name)
        expected_path2 = os.path.join(self.test_dir, "uploads", today_str, suffixed_filename)
        self.assertTrue(os.path.exists(expected_path1))
        self.assertTrue(os.path.exists(expected_path2))

        with MEDIA_DATA_LOCK:
            self.assertIn(img_sha1, MEDIA_DATA_CACHE)
            self.assertIn(img_sha2, MEDIA_DATA_CACHE)
            self.assertEqual(MEDIA_DATA_CACHE[img_sha1]['filename'], image_name)
            self.assertEqual(MEDIA_DATA_CACHE[img_sha2]['filename'], suffixed_filename)
            self.assertEqual(MEDIA_DATA_CACHE[img_sha2]['original_filename'], image_name) # from URL

    def test_put_image_duplicate_content(self):
        """Test uploading an image whose content (SHA256) already exists."""
        image_name1 = "original.png"
        image_name2 = "duplicate_content.png"
        img_data, img_content_bytes, img_sha256 = self._create_dummy_image_bytes("same_content")

        # Upload first image
        res1 = self.client.put(f'/image/{image_name1}', data={'file': (img_data, image_name1)}, content_type='multipart/form-data')
        self.assertEqual(res1.status_code, 201)

        # Attempt to upload same content with a different name
        # Re-create BytesIO for the second upload as the first one might be closed
        img_data_for_res2 = io.BytesIO(img_content_bytes)
        res2 = self.client.put(f'/image/{image_name2}', data={'file': (img_data_for_res2, image_name2)}, content_type='multipart/form-data')
        self.assertEqual(res2.status_code, 200) # Should be no-op for storage
        json_response = res2.json
        self.assertEqual(json_response['sha256'], img_sha256)
        # The returned filename/path should be of the *first* instance of this SHA
        self.assertEqual(json_response['filename'], image_name1)

        today_str = datetime.now().strftime('%Y%m%d')
        expected_file_path1 = os.path.join(self.test_dir, "uploads", today_str, image_name1)
        expected_file_path2 = os.path.join(self.test_dir, "uploads", today_str, image_name2)
        self.assertTrue(os.path.exists(expected_file_path1))
        self.assertFalse(os.path.exists(expected_file_path2)) # Second file should not have been saved

        with MEDIA_DATA_LOCK:
            self.assertEqual(len(MEDIA_DATA_CACHE), 1) # Only one entry for this content
            self.assertEqual(MEDIA_DATA_CACHE[img_sha256]['filename'], image_name1)

    def test_put_image_invalid_file_type(self):
        """Test uploading a non-image file."""
        txt_data = io.BytesIO(b"this is not an image")
        response = self.client.put('/image/textfile.txt', data={'file': (txt_data, 'textfile.txt')}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)

    def test_put_image_no_file_part(self):
        response = self.client.put('/image/someimage.jpg', data={}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)

    def test_put_image_empty_filename_in_form(self):
        img_data, _, _ = self._create_dummy_image_bytes()
        response = self.client.put('/image/someimage.jpg', data={'file': (img_data, '')}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400) # "No selected file"

    def test_get_image_success(self):
        """Test retrieving an image successfully uploaded via PUT."""
        image_name = "retrievable.jpg"
        img_data, img_content_bytes, img_sha256 = self._create_dummy_image_bytes(text_content="retrievable_content", format="JPEG")

        # Upload the image first
        put_response = self.client.put(
            f'/image/{image_name}',
            data={'file': (img_data, image_name)},
            content_type='multipart/form-data'
        )
        self.assertEqual(put_response.status_code, 201)

        # Now try to GET it
        get_response = self.client.get(f'/image/{img_sha256}')
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.data, img_content_bytes)
        self.assertIn('image/jpeg', get_response.content_type.lower())

    def test_get_image_unknown_sha(self):
        response = self.client.get('/image/' + 'a'*64) # Valid format, unknown SHA
        self.assertEqual(response.status_code, 404)

    def test_get_image_invalid_sha_format(self):
        response = self.client.get('/image/invalidsha123')
        self.assertEqual(response.status_code, 400)

    def test_get_image_file_deleted_after_cache(self):
        """Test GET when file is deleted from disk after being cached."""
        image_name = "to_be_deleted.png"
        img_data, _, img_sha256 = self._create_dummy_image_bytes("delete_me")

        put_res = self.client.put(f'/image/{image_name}', data={'file': (img_data, image_name)}, content_type='multipart/form-data')
        self.assertEqual(put_res.status_code, 201)

        # Manually delete the file from storage
        with MEDIA_DATA_LOCK: # Access cache safely
            cached_entry = MEDIA_DATA_CACHE.get(img_sha256)
            self.assertIsNotNone(cached_entry)
            file_to_delete_abs = os.path.join(flask_app.config['STORAGE_DIR'], cached_entry['file_path'])

        self.assertTrue(os.path.exists(file_to_delete_abs))
        os.remove(file_to_delete_abs)
        self.assertFalse(os.path.exists(file_to_delete_abs))

        get_response = self.client.get(f'/image/{img_sha256}')
        self.assertEqual(get_response.status_code, 404) # send_from_directory should cause NotFound -> 404
