import unittest
import os
import shutil
import tempfile
from unittest import mock
import io
import hashlib
from datetime import datetime
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from media_server.server import app as flask_app  # noqa: E402
from media_server import media_scanner  # noqa: E402
from media_server import database as db_utils  # noqa: E402
from media_server import server as media_server_module  # noqa: E402
from media_server import settings as settings_utils  # noqa: E402
from PIL import Image  # noqa: E402


def create_dummy_file(
    dir_path, filename, content="dummy content", mtime=None, image_details=None
):
    filepath = os.path.join(dir_path, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if image_details:
        try:
            img = Image.new(
                image_details.get("mode", "RGB"),
                image_details.get("size", (100, 100)),
                image_details.get("color", "blue"),
            )
            img.save(filepath, image_details.get("format", "JPEG"))
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
            media_server_module.FLAGS(
                [sys.argv[0], "--storage_dir=/tmp/dummy_for_parse_server"]
            )

        cls.test_dir = tempfile.mkdtemp(prefix="media_server_flask_db_test_")

        # Configure Flask app and FLAGS before DB initialization
        flask_app.config["TESTING"] = True
        flask_app.config["STORAGE_DIR"] = cls.test_dir
        media_server_module.FLAGS.storage_dir = (
            cls.test_dir
        )  # Set FLAG for server components that read it

        # Determine DB path using the centralized db_utils.get_db_path and default DATABASE_NAME
        cls.db_path = db_utils.get_db_path(cls.test_dir)
        flask_app.config["DATABASE_PATH"] = cls.db_path
        media_server_module.FLAGS.db_name = (
            db_utils.DATABASE_NAME
        )  # Ensure FLAGS uses the default DB name

        flask_app.config["THUMBNAIL_DIR"] = os.path.join(
            cls.test_dir, media_scanner.THUMBNAIL_DIR_NAME
        )
        os.makedirs(flask_app.config["THUMBNAIL_DIR"], exist_ok=True)

        media_server_module.settings_manager = settings_utils.SettingsManager(
            os.path.join(cls.test_dir, "settings.json")
        )

        db_utils.init_db(cls.test_dir)  # This will init the DB at cls.db_path

        cls.img1_path = create_dummy_file(
            cls.test_dir,
            "image1.jpg",
            image_details={"size": (120, 80), "format": "JPEG"},
        )
        cls.vid1_path = create_dummy_file(cls.test_dir, "video1.mp4", b"dummy video")

        with mock.patch(
            "media_server.image_classifier.ImageClassifier"
        ) as MockImageClassifier:
            mock_classifier_instance = MockImageClassifier.return_value
            mock_classifier_instance.settings = (
                media_server_module.settings_manager.get()
            )
            media_scanner.scan_directory(
                cls.test_dir, cls.db_path, mock_classifier_instance, rescan=False
            )

        cls.img1_sha256 = media_scanner.get_file_sha256(cls.img1_path)
        cls.vid1_sha256 = media_scanner.get_file_sha256(cls.vid1_path)

        cls.client = flask_app.test_client()

    def setUp(self):
        self._initial_db_state = db_utils.get_all_media_files(self.db_path)

    def tearDown(self):
        test_img = os.path.join(self.test_dir, "test_image.jpg")
        if os.path.exists(test_img):
            try:
                os.remove(test_img)
            except OSError:
                pass
        current_entries = db_utils.get_all_media_files(self.db_path)
        for sha in list(current_entries.keys()):
            if sha not in self._initial_db_state:
                db_utils.delete_media_file_by_sha(self.db_path, sha)
        for sha, data in self._initial_db_state.items():
            db_utils.add_or_update_media_file(self.db_path, data)

    @classmethod
    def tearDownClass(cls):
        db_utils.close_db_connection()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        shutil.rmtree(cls.test_dir)

    def test_list_endpoint_success(self):
        response = self.client.get("/list")
        self.assertEqual(response.status_code, 200)
        returned_data = response.json
        self.assertEqual(len(returned_data), 2)
        self.assertIn(self.img1_sha256, returned_data)
        self.assertIn(self.vid1_sha256, returned_data)

    def test_get_thumbnail_success(self):
        response = self.client.get(f"/thumbnail/{self.img1_sha256}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "image/png")

    def test_get_thumbnail_video_success(self):
        response = self.client.get(f"/thumbnail/{self.vid1_sha256}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "image/png")

    def test_get_thumbnail_unknown_sha(self):
        response = self.client.get(f"/thumbnail/{'a' * 64}")
        self.assertEqual(response.status_code, 404)

    def _create_dummy_image_bytes(self, text_content="dummy_image", format="PNG"):
        img_byte_arr = io.BytesIO()
        dummy_pil_img = Image.new("RGB", (60, 30), color="red")
        from PIL import ImageDraw

        draw = ImageDraw.Draw(dummy_pil_img)
        draw.text((5, 5), text_content, fill=(0, 0, 0))
        dummy_pil_img.save(img_byte_arr, format=format.upper())
        content_bytes = img_byte_arr.getvalue()
        img_byte_arr.seek(0)
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        return img_byte_arr, content_bytes, sha256

    def test_put_image_success_new_image(self):
        image_name = "test_put_image.png"
        img_data, img_content_bytes, img_sha256 = self._create_dummy_image_bytes(
            text_content=image_name
        )

        response = self.client.put(
            f"/image/{image_name}",
            data={"file": (img_data, image_name)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        json_response = response.json
        self.assertEqual(json_response["sha256"], img_sha256)

        db_entry = db_utils.get_media_file_by_sha(self.db_path, img_sha256)
        self.assertIsNotNone(db_entry)
        self.assertEqual(db_entry["filename"], image_name)

        # Verify file saved
        today_str = datetime.now().strftime("%Y%m%d")
        expected_file_path = os.path.join(
            self.test_dir, "uploads", today_str, image_name
        )
        self.assertTrue(os.path.exists(expected_file_path))

        # Clean up this specific uploaded file and DB entry to avoid affecting other tests
        os.remove(expected_file_path)
        db_utils.delete_media_file_by_sha(self.db_path, img_sha256)
        # Thumbnail cleanup would also be needed if we checked it.
        thumb_path = os.path.join(
            flask_app.config["THUMBNAIL_DIR"], db_entry["thumbnail_file"]
        )
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
        thumb_subdir = os.path.dirname(thumb_path)
        if os.path.exists(thumb_subdir) and not os.listdir(thumb_subdir):
            os.rmdir(thumb_subdir)

    def test_get_image_success(self):
        # This test relies on img1_path from setUpClass
        response = self.client.get(f"/image/{self.img1_sha256}")
        self.assertEqual(response.status_code, 200)
        with open(self.img1_path, "rb") as f:
            expected_content = f.read()
        self.assertEqual(response.data, expected_content)

    @mock.patch("media_server.image_classifier.ImageClassifier.classify_image")
    def test_put_image_with_tagging(self, mock_classify_image):
        # 1. Setup initial state
        mock_classify_image.return_value = [("mock_tag", 0.9)]
        initial_settings = settings_utils.Settings(
            rescan_interval=0, tagging_model="Resnet"
        )
        media_server_module.settings_manager.write_settings(initial_settings)

        # 2. Upload an image
        image_name = "test_put_image_with_tagging.png"
        img_data, _, img_sha256 = self._create_dummy_image_bytes(
            text_content=image_name
        )

        response = self.client.put(
            f"/image/{image_name}",
            data={"file": (img_data, image_name)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)

        # 3. Verify tags are present
        db_entry = db_utils.get_media_file_by_sha(self.db_path, img_sha256)
        self.assertIsNotNone(db_entry)
        self.assertIsNotNone(db_entry.get("tags"))
        self.assertEqual(db_entry.get("tagging_model"), "Resnet")
        self.assertIn("mock_tag", db_entry.get("tags"))

    def test_put_portrait_jpeg_aspect_ratio(self):
        import piexif
        image_name = "test_portrait.jpeg"
        img_byte_arr = io.BytesIO()
        dummy_pil_img = Image.new("RGB", (600, 400), color="green")
        exif_dict = {"0th": {piexif.ImageIFD.Orientation: 6}}
        exif_bytes = piexif.dump(exif_dict)
        dummy_pil_img.save(img_byte_arr, format="JPEG", exif=exif_bytes)
        content_bytes = img_byte_arr.getvalue()
        img_byte_arr.seek(0)
        img_sha256 = hashlib.sha256(content_bytes).hexdigest()

        response = self.client.put(
            f"/image/{image_name}",
            data={"file": (img_byte_arr, image_name)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)

        db_entry = db_utils.get_media_file_by_sha(self.db_path, img_sha256)
        self.assertIsNotNone(db_entry)
        # Orientation 6 should transpose 600x400 to 400x600 (portrait)
        self.assertEqual(db_entry["width"], 400)
        self.assertEqual(db_entry["height"], 600)

    def test_get_settings(self):
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        settings = response.json
        self.assertEqual(settings["rescan_interval"], 600)
        self.assertEqual(settings["tagging_model"], "Off")

    def test_put_settings(self):
        new_settings = {
            "rescan_interval": 1200,
            "tagging_model": "Resnet",
            "archival_backend": "AWS",
            "archival_bucket": "my-test-bucket",
        }
        response = self.client.put("/api/settings", json=new_settings)
        self.assertEqual(response.status_code, 200)
        updated_settings = response.json
        self.assertEqual(updated_settings, new_settings)

        # Verify that the settings were actually updated
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        settings = response.json
        self.assertEqual(settings, new_settings)

    def test_put_settings_invalid_format(self):
        response = self.client.put("/api/settings", json={"invalid_field": "value"})
        self.assertEqual(response.status_code, 400)

    def test_list_media_by_date_success(self):
        # This test assumes a known date for one of the test files.
        # Let's update one file to have a specific date.
        img1_creation_time = datetime(2023, 1, 15, 12, 0, 0).timestamp()
        db_utils.update_media_file_fields(
            self.db_path,
            self.img1_sha256,
            {"original_creation_date": img1_creation_time},
        )

        response = self.client.get("/list/date/2023-01-15")
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(len(data), 1)
        self.assertIn(self.img1_sha256, data)

        # Test with no results
        response = self.client.get("/list/date/2022-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 0)

    def test_list_media_by_date_range_success(self):
        # Dates for img1 and vid1
        img1_creation_time = datetime(2023, 1, 15, 12, 0, 0).timestamp()
        vid1_creation_time = datetime(2023, 1, 20, 12, 0, 0).timestamp()
        db_utils.update_media_file_fields(
            self.db_path,
            self.img1_sha256,
            {"original_creation_date": img1_creation_time},
        )
        db_utils.update_media_file_fields(
            self.db_path,
            self.vid1_sha256,
            {"original_creation_date": vid1_creation_time},
        )

        # Range including both
        response = self.client.get("/list/daterange/2023-01-15/2023-01-20")
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(len(data), 2)
        self.assertIn(self.img1_sha256, data)
        self.assertIn(self.vid1_sha256, data)

        # Range including only one
        response = self.client.get("/list/daterange/2023-01-14/2023-01-16")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 1)

    def test_list_media_by_location_success(self):
        # Update a record to have a location
        db_utils.update_media_file_fields(
            self.db_path,
            self.img1_sha256,
            {"city": "TestCity", "country": "TestCountry"},
        )

        # Test with city and country
        response = self.client.get("/list/location/TestCity/TestCountry")
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(len(data), 1)
        self.assertIn(self.img1_sha256, data)

        # Test with city only
        response = self.client.get("/list/location/TestCity")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 1)

        # Test with no results
        response = self.client.get("/list/location/UnknownCity")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 0)

    def test_get_image_by_sha256_endpoint_success(self):
        response = self.client.get(f"/image/sha256/{self.img1_sha256}")
        self.assertEqual(response.status_code, 200)
        with open(self.img1_path, "rb") as f:
            expected_content = f.read()
        self.assertEqual(response.data, expected_content)

    def test_image_classifier_updated_on_settings_change(self):
        # 1. Setup initial state
        create_dummy_file(
            self.test_dir, "test_image.jpg", image_details={"format": "JPEG"}
        )
        initial_settings = settings_utils.Settings(
            rescan_interval=0, tagging_model="Off"
        )
        media_server_module.settings_manager.write_settings(initial_settings)

        # 2. Mock ImageClassifier
        with mock.patch(
            "media_server.image_classifier.ImageClassifier"
        ) as MockImageClassifier:
            mock_classifier_instance = MockImageClassifier.return_value
            mock_classifier_instance.classify_image.return_value = [("mock_tag", 0.9)]

            # Pass settings to the instance
            mock_classifier_instance.settings = initial_settings

            # 3. Initial scan with tagging off
            media_scanner.scan_directory(
                self.test_dir, self.db_path, mock_classifier_instance, rescan=False
            )

            # 4. Verify no tags
            db_entries = db_utils.get_all_media_files(self.db_path)
            self.assertEqual(len(db_entries), 3)
            image_sha = ""
            for sha, entry in db_entries.items():
                if entry["filename"] == "test_image.jpg":
                    image_sha = sha
                    break
            self.assertNotEqual(image_sha, "")
            db_entry = db_utils.get_media_file_by_sha(self.db_path, image_sha)
            self.assertIsNone(db_entry.get("tags"))
            self.assertNotEqual(db_entry.get("tagging_model"), "Resnet")

            # 5. Update settings to turn on tagging
            new_settings_dict = {
                "rescan_interval": 1,
                "tagging_model": "Resnet",
                "archival_backend": "Off",
                "archival_bucket": "",
            }

            # Directly update settings instead of using the API
            updated_settings = settings_utils.Settings(**new_settings_dict)
            media_server_module.settings_manager.write_settings(updated_settings)

            # 6. Manually trigger a scan with new settings
            mock_classifier_instance.settings = updated_settings
            media_scanner.scan_directory(
                self.test_dir, self.db_path, mock_classifier_instance, rescan=True
            )

            # 7. Verify tags are now present
            db_entry_after_scan = db_utils.get_media_file_by_sha(
                self.db_path, image_sha
            )
            self.assertIsNotNone(db_entry_after_scan.get("tags"))
            self.assertEqual(db_entry_after_scan.get("tagging_model"), "Resnet")
            self.assertIn("mock_tag", db_entry_after_scan.get("tags"))

    def test_get_api_media_paginated(self):
        response = self.client.get("/api/media?limit=1&offset=0")
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertIn("items", data)
        self.assertIn("total_count", data)
        self.assertIn("has_more", data)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["total_count"], 2)
        self.assertTrue(data["has_more"])

    def test_root_route_serves_scanning_when_scan_in_progress(self):
        media_server_module.scan_status.update(
            initial_scan_in_progress=True,
            initial_scan_completed=False,
            is_scanning=True,
        )
        try:
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Scanning Media Library", response.data)
        finally:
            media_server_module.scan_status.update(
                initial_scan_in_progress=False,
                initial_scan_completed=True,
                is_scanning=False,
            )

    def test_root_route_serves_index_when_scan_complete(self):
        media_server_module.scan_status.update(
            initial_scan_in_progress=False,
            initial_scan_completed=True,
            is_scanning=False,
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"PhotoBackup", response.data)
        self.assertIn(b"gallery-grid", response.data)

    def test_api_scan_status(self):
        media_server_module.scan_status.update(
            is_scanning=True,
            initial_scan_in_progress=True,
            initial_scan_completed=False,
            phase="processing",
            message="Processing media 5/10",
            current=5,
            total=10,
            percent=50.0,
        )
        try:
            response = self.client.get("/api/scan/status")
            self.assertEqual(response.status_code, 200)
            data = response.json
            self.assertTrue(data["is_scanning"])
            self.assertTrue(data["initial_scan_in_progress"])
            self.assertFalse(data["initial_scan_completed"])
            self.assertEqual(data["phase"], "processing")
            self.assertEqual(data["current"], 5)
            self.assertEqual(data["total"], 10)
            self.assertEqual(data["percent"], 50.0)
        finally:
            media_server_module.scan_status.update(
                initial_scan_in_progress=False,
                initial_scan_completed=True,
                is_scanning=False,
            )

    def test_api_scan_post_and_get(self):
        # Test GET /api/scan
        get_res = self.client.get("/api/scan")
        self.assertEqual(get_res.status_code, 200)
        self.assertIn("is_scanning", get_res.json)

        # Test POST /api/scan
        post_res = self.client.post("/api/scan")
        self.assertEqual(post_res.status_code, 200)
        self.assertIn("message", post_res.json)
    def test_put_unicode_filename_preserves_extension(self):
        # Non-ASCII filename (e.g. Chinese characters)
        image_name = "暑假旅行.jpg"
        img_byte_arr = io.BytesIO()
        dummy_pil_img = Image.new("RGB", (100, 100), color="blue")
        dummy_pil_img.save(img_byte_arr, format="JPEG")
        content_bytes = img_byte_arr.getvalue()
        img_byte_arr.seek(0)
        img_sha256 = hashlib.sha256(content_bytes).hexdigest()

        response = self.client.put(
            f"/image/{image_name}",
            data={"file": (img_byte_arr, image_name)},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)

        db_entry = db_utils.get_media_file_by_sha(self.db_path, img_sha256)
        self.assertIsNotNone(db_entry)
        self.assertTrue(db_entry["file_path"].endswith(".jpg"))
        self.assertEqual(db_entry["mime_type"], "image/jpeg")

    def test_archival_test_with_payload(self):
        # Test with 'Off' payload
        response = self.client.post(
            "/api/archival/test",
            json={"archival_backend": "Off", "archival_bucket": "test-bucket"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertTrue(data.get("connected"))

    # --- HTTP 400 & SHA256 Format Validations ---
    def test_get_image_invalid_sha_format_returns_400(self):
        for bad_sha in ["short_sha", "g" * 64, "12345", "../../etc/passwd"]:
            res = self.client.get(f"/image/{bad_sha}")
            self.assertIn(res.status_code, [400, 404])

    def test_get_thumbnail_invalid_sha_format_returns_400(self):
        res = self.client.get("/thumbnail/invalid_sha_123")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid SHA256 format", res.json["error"])

    # --- Date & Range Parameter Validations ---
    def test_list_media_by_date_invalid_format_returns_400(self):
        for bad_date in ["2023-13-45", "not-a-date", "20230101"]:
            res = self.client.get(f"/list/date/{bad_date}")
            self.assertEqual(res.status_code, 400)
            self.assertIn("Invalid date format", res.json["error"])

    def test_list_media_by_date_range_inverted_returns_400(self):
        res = self.client.get("/list/daterange/2023-02-01/2023-01-01")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Start date must be before end date", res.json["error"])

    # --- Upload Error Conditions & Deduplication ---
    def test_put_image_missing_file_part_returns_400(self):
        res = self.client.put("/image/test.jpg", data={})
        self.assertEqual(res.status_code, 400)
        self.assertIn("No file part in the request", res.json["error"])

    def test_put_image_disallowed_extension_returns_400(self):
        data = {"file": (io.BytesIO(b"fake executable"), "script.exe")}
        res = self.client.put("/image/script.exe", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid file type", res.json["error"])

    def test_put_image_duplicate_sha_returns_200_deduplication(self):
        img_bytes = io.BytesIO()
        Image.new("RGB", (50, 50), color="yellow").save(img_bytes, format="JPEG")
        raw = img_bytes.getvalue()

        # 1st Upload
        res1 = self.client.put(
            "/image/first.jpg",
            data={"file": (io.BytesIO(raw), "first.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res1.status_code, 201)
        sha = res1.json["sha256"]

        # 2nd Upload with exact same content
        res2 = self.client.put(
            "/image/second.jpg",
            data={"file": (io.BytesIO(raw), "second.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res2.status_code, 200)
        self.assertIn("Image content already exists in DB", res2.json["message"])
        self.assertEqual(res2.json["sha256"], sha)

    # --- Video Range Requests (HTTP 206 Streaming) ---
    def test_video_range_request_streaming(self):
        video_content = b"0123456789" * 100  # 1000 bytes
        video_sha = hashlib.sha256(video_content).hexdigest()
        video_path = os.path.join(self.test_dir, "sample.mp4")
        with open(video_path, "wb") as f:
            f.write(video_content)

        db_utils.add_or_update_media_file(
            self.db_path,
            {
                "sha256_hex": video_sha,
                "filename": "sample.mp4",
                "file_path": "sample.mp4",
                "last_modified": 1672531200,
                "mime_type": "video/mp4",
                "filesize": len(video_content),
            },
        )

        headers = {"Range": "bytes=0-99"}
        res = self.client.get(f"/image/{video_sha}", headers=headers)
        self.assertEqual(res.status_code, 206)
        self.assertEqual(res.content_type, "video/mp4")
        self.assertEqual(len(res.data), 100)
        self.assertEqual(res.data, video_content[0:100])
        self.assertIn("bytes 0-99/1000", res.headers.get("Content-Range", ""))

    # --- API Search & Stats Endpoints ---
    def test_api_search_endpoint(self):
        res = self.client.get("/api/search?q=sample&type=video")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json, dict)

    def test_api_stats_endpoint(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        self.assertIn("total_count", res.json)
        self.assertIn("video_count", res.json)
        self.assertIn("image_count", res.json)

    # --- Settings Update Error Handling ---
    def test_put_settings_non_json_or_invalid_values(self):
        # Non-JSON
        res = self.client.put("/api/settings", data="not json", content_type="text/plain")
        self.assertIn(res.status_code, [400, 415])

        # Invalid rescan interval value
        res = self.client.put("/api/settings", json={"rescan_interval": -500})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid settings format", res.json["error"])


if __name__ == "__main__":
    unittest.main()


