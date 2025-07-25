import unittest
import os
import shutil
import tempfile
import json
import time
from unittest import mock
import io
import hashlib
from datetime import datetime
import threading

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from media_server.server import app as flask_app
from media_server import media_scanner
from media_server import database as db_utils
from media_server import server as media_server_module
from media_server import settings as settings_utils
from PIL import Image

def create_dummy_file(dir_path, filename, content="dummy content", mtime=None, image_details=None):
    filepath = os.path.join(dir_path, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if image_details:
        try:
            img = Image.new(image_details.get('mode', 'RGB'),
                            image_details.get('size', (100,100)),
                            image_details.get('color', 'blue'))
            img.save(filepath, image_details.get('format', 'JPEG'))
        except Exception:
            with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
                f.write(content if content else b"image creation failed")
    else:
        with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
            f.write(content)
    if mtime is not None:
        os.utime(filepath, (mtime, mtime))
    return filepath

class TestServerFlaskWithDB(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not media_server_module.FLAGS.is_parsed():
            media_server_module.FLAGS([sys.argv[0], '--storage_dir=/tmp/dummy_for_parse_server'])

        cls.test_dir = tempfile.mkdtemp(prefix="media_server_flask_db_test_")

        # Configure Flask app and FLAGS before DB initialization
        flask_app.config['TESTING'] = True
        flask_app.config['STORAGE_DIR'] = cls.test_dir
        media_server_module.FLAGS.storage_dir = cls.test_dir # Set FLAG for server components that read it

        # Determine DB path using the centralized db_utils.get_db_path and default DATABASE_NAME
        cls.db_path = db_utils.get_db_path(cls.test_dir)
        flask_app.config['DATABASE_PATH'] = cls.db_path
        media_server_module.FLAGS.db_name = db_utils.DATABASE_NAME # Ensure FLAGS uses the default DB name

        flask_app.config['THUMBNAIL_DIR'] = os.path.join(cls.test_dir, media_scanner.THUMBNAIL_DIR_NAME)
        os.makedirs(flask_app.config['THUMBNAIL_DIR'], exist_ok=True)

        media_server_module.settings_manager = settings_utils.SettingsManager(
            os.path.join(cls.test_dir, 'settings.json')
        )

        db_utils.init_db(cls.test_dir) # This will init the DB at cls.db_path

        cls.img1_path = create_dummy_file(cls.test_dir, "image1.jpg", image_details={'size': (120, 80), 'format': 'JPEG'})
        cls.vid1_path = create_dummy_file(cls.test_dir, "video1.mp4", b"dummy video")

        with mock.patch('media_server.image_classifier.ImageClassifier') as MockImageClassifier:
            mock_classifier_instance = MockImageClassifier.return_value
            mock_classifier_instance.settings = media_server_module.settings_manager.get()
            media_scanner.scan_directory(cls.test_dir, cls.db_path, mock_classifier_instance, rescan=False)

        cls.img1_sha256 = media_scanner.get_file_sha256(cls.img1_path)
        cls.vid1_sha256 = media_scanner.get_file_sha256(cls.vid1_path)

        cls.client = flask_app.test_client()

    @classmethod
    def tearDownClass(cls):
        db_utils.close_db_connection()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        shutil.rmtree(cls.test_dir)



    def test_list_endpoint_success(self):
        response = self.client.get('/list')
        self.assertEqual(response.status_code, 200)
        returned_data = response.json
        self.assertEqual(len(returned_data), 3)
        self.assertIn(self.img1_sha256, returned_data)
        self.assertIn(self.vid1_sha256, returned_data)

    def test_get_thumbnail_success(self):
        response = self.client.get(f'/thumbnail/{self.img1_sha256}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'image/png')

    def test_get_thumbnail_not_found_for_video(self):
        response = self.client.get(f'/thumbnail/{self.vid1_sha256}')
        self.assertEqual(response.status_code, 404) # Videos don't have thumbs by default

    def _create_dummy_image_bytes(self, text_content="dummy_image", format="PNG"):
        img_byte_arr = io.BytesIO()
        dummy_pil_img = Image.new('RGB', (60, 30), color = 'red')
        from PIL import ImageDraw
        draw = ImageDraw.Draw(dummy_pil_img)
        draw.text((5,5), text_content, fill=(0,0,0))
        dummy_pil_img.save(img_byte_arr, format=format.upper())
        content_bytes = img_byte_arr.getvalue()
        img_byte_arr.seek(0)
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        return img_byte_arr, content_bytes, sha256

    def test_put_image_success_new_image(self):
        image_name = "test_put_image.png"
        img_data, img_content_bytes, img_sha256 = self._create_dummy_image_bytes(text_content=image_name)

        response = self.client.put(
            f'/image/{image_name}',
            data={'file': (img_data, image_name)},
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 201)
        json_response = response.json
        self.assertEqual(json_response['sha256'], img_sha256)

        db_entry = db_utils.get_media_file_by_sha(self.db_path, img_sha256)
        self.assertIsNotNone(db_entry)
        self.assertEqual(db_entry['filename'], image_name)

        # Verify file saved
        today_str = datetime.now().strftime('%Y%m%d')
        expected_file_path = os.path.join(self.test_dir, "uploads", today_str, image_name)
        self.assertTrue(os.path.exists(expected_file_path))

        # Clean up this specific uploaded file and DB entry to avoid affecting other tests
        os.remove(expected_file_path)
        db_utils.delete_media_file_by_sha(self.db_path, img_sha256)
        # Thumbnail cleanup would also be needed if we checked it.
        thumb_path = os.path.join(flask_app.config['THUMBNAIL_DIR'], db_entry['thumbnail_file'])
        if os.path.exists(thumb_path): os.remove(thumb_path)
        thumb_subdir = os.path.dirname(thumb_path)
        if os.path.exists(thumb_subdir) and not os.listdir(thumb_subdir):
            os.rmdir(thumb_subdir)


    def test_get_image_success(self):
        # This test relies on img1_path from setUpClass
        response = self.client.get(f'/image/{self.img1_sha256}')
        self.assertEqual(response.status_code, 200)
        with open(self.img1_path, "rb") as f:
            expected_content = f.read()
        self.assertEqual(response.data, expected_content)

    def test_get_settings(self):
        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        settings = response.json
        self.assertEqual(settings['rescan_interval'], 600)
        self.assertEqual(settings['tagging_model'], "Off")

    def test_put_settings(self):
        new_settings = {
            "rescan_interval": 1200,
            "tagging_model": "Resnet",
            "archival_backend": "AWS",
            "archival_bucket": "my-test-bucket"
        }
        response = self.client.put('/api/settings', json=new_settings)
        self.assertEqual(response.status_code, 200)
        updated_settings = response.json
        self.assertEqual(updated_settings, new_settings)

        # Verify that the settings were actually updated
        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code, 200)
        settings = response.json
        self.assertEqual(settings, new_settings)

    def test_put_settings_invalid_format(self):
        response = self.client.put('/api/settings', json={"invalid_field": "value"})
        self.assertEqual(response.status_code, 400)

    def test_list_media_by_date_success(self):
        # This test assumes a known date for one of the test files.
        # Let's update one file to have a specific date.
        img1_creation_time = datetime(2023, 1, 15, 12, 0, 0).timestamp()
        db_utils.update_media_file_fields(self.db_path, self.img1_sha256, {'original_creation_date': img1_creation_time})

        response = self.client.get('/list/date/2023-01-15')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(len(data), 1)
        self.assertIn(self.img1_sha256, data)

        # Test with no results
        response = self.client.get('/list/date/2022-01-01')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 0)

    def test_list_media_by_date_range_success(self):
        # Dates for img1 and vid1
        img1_creation_time = datetime(2023, 1, 15, 12, 0, 0).timestamp()
        vid1_creation_time = datetime(2023, 1, 20, 12, 0, 0).timestamp()
        db_utils.update_media_file_fields(self.db_path, self.img1_sha256, {'original_creation_date': img1_creation_time})
        db_utils.update_media_file_fields(self.db_path, self.vid1_sha256, {'original_creation_date': vid1_creation_time})

        # Range including both
        response = self.client.get('/list/daterange/2023-01-15/2023-01-20')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(len(data), 2)
        self.assertIn(self.img1_sha256, data)
        self.assertIn(self.vid1_sha256, data)

        # Range including only one
        response = self.client.get('/list/daterange/2023-01-14/2023-01-16')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 1)

    def test_list_media_by_location_success(self):
        # Update a record to have a location
        db_utils.update_media_file_fields(self.db_path, self.img1_sha256, {'city': 'TestCity', 'country': 'TestCountry'})

        # Test with city and country
        response = self.client.get('/list/location/TestCity/TestCountry')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(len(data), 1)
        self.assertIn(self.img1_sha256, data)

        # Test with city only
        response = self.client.get('/list/location/TestCity')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 1)

        # Test with no results
        response = self.client.get('/list/location/UnknownCity')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 0)

    def test_get_image_by_sha256_endpoint_success(self):
        response = self.client.get(f'/image/sha256/{self.img1_sha256}')
        self.assertEqual(response.status_code, 200)
        with open(self.img1_path, "rb") as f:
            expected_content = f.read()
        self.assertEqual(response.data, expected_content)

    def test_image_classifier_updated_on_settings_change(self):
        # 1. Setup initial state
        create_dummy_file(self.test_dir, "test_image.jpg", image_details={'format': 'JPEG'})
        initial_settings = settings_utils.Settings(rescan_interval=0, tagging_model="Off")
        media_server_module.settings_manager.write_settings(initial_settings)

        # 2. Mock ImageClassifier
        with mock.patch('media_server.image_classifier.ImageClassifier') as MockImageClassifier:
            mock_classifier_instance = MockImageClassifier.return_value
            mock_classifier_instance.classify_image.return_value = [("mock_tag", 0.9)]

            # Pass settings to the instance
            mock_classifier_instance.settings = initial_settings

            # 3. Initial scan with tagging off
            media_scanner.scan_directory(self.test_dir, self.db_path, mock_classifier_instance, rescan=False)

            # 4. Verify no tags
            db_entries = db_utils.get_all_media_files(self.db_path)
            self.assertEqual(len(db_entries), 3)
            image_sha = ""
            for sha, entry in db_entries.items():
                if entry['filename'] == 'test_image.jpg':
                    image_sha = sha
                    break
            self.assertNotEqual(image_sha, "")
            db_entry = db_utils.get_media_file_by_sha(self.db_path, image_sha)
            self.assertIsNone(db_entry.get('tags'))
            self.assertNotEqual(db_entry.get('tagging_model'), "Resnet")

            # 5. Update settings to turn on tagging
            new_settings_dict = {
                "rescan_interval": 1,
                "tagging_model": "Resnet",
                "archival_backend": "Off",
                "archival_bucket": ""
            }

            # Directly update settings instead of using the API
            updated_settings = settings_utils.Settings(**new_settings_dict)
            media_server_module.settings_manager.write_settings(updated_settings)

            # 6. Manually trigger a scan with new settings
            mock_classifier_instance.settings = updated_settings
            media_scanner.scan_directory(self.test_dir, self.db_path, mock_classifier_instance, rescan=True)

            # 7. Verify tags are now present
            db_entry_after_scan = db_utils.get_media_file_by_sha(self.db_path, image_sha)
            self.assertIsNotNone(db_entry_after_scan.get('tags'))
            self.assertEqual(db_entry_after_scan.get('tagging_model'), "Resnet")
            self.assertIn("mock_tag", db_entry_after_scan.get('tags'))




if __name__ == '__main__':
    unittest.main()
