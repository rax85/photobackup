import unittest
from unittest import mock
import os
import shutil
import tempfile
import hashlib
import time

# Add project root to sys.path to allow direct import of media_server
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from media_server import media_scanner  # noqa: E402
from media_server import database as db_utils  # noqa: E402
import piexif  # noqa: E402
from PIL import Image  # noqa: E402
from datetime import datetime as dt  # noqa: E402


# Helper to create GPS rational representation
def to_rational(number):
    if isinstance(number, int):
        return (number, 1)
    if isinstance(number, float):
        f_den = 1000000
        return (int(number * f_den), f_den)
    return (number, 1)


# Helper to create dummy files
def create_dummy_file(
    dir_path,
    filename,
    content="dummy content",
    mtime=None,
    image_details=None,
    exif_datetime_original_str=None,
    gps_info_dict=None,
    orientation=None,
):
    filepath = os.path.join(dir_path, filename)
    os.makedirs(
        os.path.dirname(filepath), exist_ok=True
    )  # Ensure parent directory exists

    if image_details:
        try:
            img = Image.new(
                image_details.get("mode", "RGB"),
                image_details.get("size", (100, 100)),
                image_details.get("color", "blue"),
            )

            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}}
            if orientation is not None:
                exif_dict["0th"][piexif.ImageIFD.Orientation] = orientation
            if exif_datetime_original_str:
                exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = (
                    exif_datetime_original_str.encode("utf-8")
                )

            if gps_info_dict:
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = gps_info_dict[
                    "GPSLatitudeRef"
                ].encode("utf-8")
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = [
                    to_rational(x) for x in gps_info_dict["GPSLatitude"]
                ]
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = gps_info_dict[
                    "GPSLongitudeRef"
                ].encode("utf-8")
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = [
                    to_rational(x) for x in gps_info_dict["GPSLongitude"]
                ]

            exif_bytes = piexif.dump(exif_dict)
            img.save(filepath, image_details.get("format", "JPEG"), exif=exif_bytes)
        except Exception:  # Fallback for any image creation/saving error
            with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
                f.write(content if content else b"image creation failed")
    else:
        with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
            f.write(content)

    if mtime is not None:
        os.utime(filepath, (mtime, mtime))
    return filepath


def calculate_sha256_str(content_str):
    content_to_hash = (
        content_str.encode("utf-8") if isinstance(content_str, str) else content_str
    )
    return hashlib.sha256(content_to_hash).hexdigest()


def calculate_sha256_file(filepath):
    return media_scanner.get_file_sha256(filepath)


class TestMediaScannerWithDB(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="media_scanner_db_test_")
        self.subdir = os.path.join(self.test_dir, "subdir")
        os.makedirs(self.subdir)

        # Setup database in the test_dir
        # self.test_dir is the storage directory
        self.db_path = db_utils.get_db_path(
            self.test_dir
        )  # This will use DATABASE_NAME from db_utils
        db_utils.init_db(self.test_dir)  # This will init the DB at self.db_path

        self.thumbnail_dir_path = os.path.join(
            self.test_dir, media_scanner.THUMBNAIL_DIR_NAME
        )
        # media_scanner.scan_directory will create self.thumbnail_dir_path if it doesn't exist.

        # Create dummy files
        self.content_vid1 = b"this is video1"
        self.hash_vid1 = calculate_sha256_str(self.content_vid1)
        self.time_img1 = time.time() - 1000
        self.file_img1 = create_dummy_file(
            self.test_dir,
            "image1.jpg",
            mtime=self.time_img1,
            image_details={"size": (600, 400), "format": "JPEG"},
        )
        self.hash_img1 = calculate_sha256_file(self.file_img1)
        self.time_vid1 = time.time() - 2000
        self.file_vid1 = create_dummy_file(
            self.test_dir, "video1.mp4", self.content_vid1, mtime=self.time_vid1
        )
        self.file_txt1 = create_dummy_file(
            self.test_dir, "document.txt", "this is a text document"
        )
        self.time_img2 = time.time() - 500
        self.file_img2_subdir = create_dummy_file(
            self.subdir,
            "image2.png",
            mtime=self.time_img2,
            image_details={"size": (300, 500), "format": "PNG"},
        )
        self.hash_img2 = calculate_sha256_file(self.file_img2_subdir)
        self.file_img3_square = create_dummy_file(
            self.test_dir,
            "square.jpg",
            mtime=time.time() - 400,
            image_details={"size": (400, 400), "format": "JPEG"},
        )
        self.hash_img3_square = calculate_sha256_file(self.file_img3_square)
        self.exif_date_str = "2001:01:01 10:00:00"
        self.exif_timestamp = dt.strptime(
            self.exif_date_str, "%Y:%m:%d %H:%M:%S"
        ).timestamp()
        self.time_img_exif = time.time() - 300
        self.file_img_exif = create_dummy_file(
            self.test_dir,
            "image_with_exif.jpg",
            mtime=self.time_img_exif,
            image_details={"size": (80, 90), "format": "JPEG"},
            exif_datetime_original_str=self.exif_date_str,
        )
        self.hash_img_exif = calculate_sha256_file(self.file_img_exif)
        self.gps_lat_ref = "N"
        self.gps_lat_dms = (34, 5, 12.34)
        self.gps_lon_ref = "W"
        self.gps_lon_dms = (118, 30, 56.78)
        self.expected_gps_lat_decimal = 34 + (5 / 60) + (12.34 / 3600)
        self.expected_gps_lon_decimal = -(118 + (30 / 60) + (56.78 / 3600))
        self.time_img_gps = time.time() - 200
        self.file_img_gps = create_dummy_file(
            self.test_dir,
            "image_with_gps.jpg",
            mtime=self.time_img_gps,
            image_details={"size": (120, 100), "format": "JPEG"},
            gps_info_dict={
                "GPSLatitudeRef": self.gps_lat_ref,
                "GPSLatitude": self.gps_lat_dms,
                "GPSLongitudeRef": self.gps_lon_ref,
                "GPSLongitude": self.gps_lon_dms,
            },
        )
        self.hash_img_gps = calculate_sha256_file(self.file_img_gps)

        self.mock_jpeg_gps_info_sub_ifd = {
            media_scanner.GPS_LATITUDE_REF_TAG: self.gps_lat_ref,
            media_scanner.GPS_LATITUDE_TAG: self.gps_lat_dms,  # Using tuple of floats directly
            media_scanner.GPS_LONGITUDE_REF_TAG: self.gps_lon_ref,
            media_scanner.GPS_LONGITUDE_TAG: self.gps_lon_dms,  # Using tuple of floats directly
        }
        self.mock_exif_obj_for_gps_jpeg = Image.Exif()
        if media_scanner.GPS_TAG_ID is not None:
            self.mock_exif_obj_for_gps_jpeg[media_scanner.GPS_TAG_ID] = (
                self.mock_jpeg_gps_info_sub_ifd
            )

        self.mock_image_classifier = mock.Mock()
        self.mock_image_classifier.settings = mock.Mock()
        self.mock_image_classifier.settings.tagging_model = "Off"

    def tearDown(self):
        db_utils.close_db_connection()  # Ensure connection for this thread is closed
        if os.path.exists(self.db_path):
            # Give a moment for SQLite to release file lock if needed, though typically not an issue.
            # On Windows, file locks can be more persistent.
            time.sleep(0.1)
            try:
                os.remove(self.db_path)
            except PermissionError:  # pragma: no cover
                # This might happen on Windows if the DB connection isn't fully released.
                # Add a small delay and retry.
                time.sleep(0.5)
                try:
                    os.remove(self.db_path)
                except Exception as e:
                    print(
                        f"Warning: Could not remove test DB {self.db_path} during teardown: {e}"
                    )

        shutil.rmtree(self.test_dir)

    def test_is_media_file(self):
        self.assertTrue(media_scanner.is_media_file("test.jpg"))
        self.assertFalse(media_scanner.is_media_file("test.txt"))

    def test_get_file_sha256(self):
        self.assertEqual(media_scanner.get_file_sha256(self.file_img1), self.hash_img1)
        self.assertIsNone(media_scanner.get_file_sha256("non_existent_file.jpg"))

    def test_scan_directory_empty(self):
        empty_dir = os.path.join(self.test_dir, "empty_subdir_for_scan")
        os.makedirs(empty_dir)
        # Create a separate DB for this empty dir test to avoid interference
        empty_db_path = os.path.join(empty_dir, "empty_test_db.sqlite3")
        db_utils.init_db(
            empty_dir
        )  # This will use empty_dir to form path to empty_test_db.sqlite3

        media_scanner.scan_directory(
            empty_dir, empty_db_path, self.mock_image_classifier
        )

        result_from_db = db_utils.get_all_media_files(empty_db_path)
        self.assertEqual(result_from_db, {})
        self.assertTrue(
            os.path.isdir(os.path.join(empty_dir, media_scanner.THUMBNAIL_DIR_NAME))
        )

        db_utils.close_db_connection()  # Close for this specific DB
        if os.path.exists(empty_db_path):
            os.remove(empty_db_path)

    def test_scan_directory_non_existent(self):
        non_existent_dir = os.path.join(self.test_dir, "does_not_exist")
        # scan_directory should log an error and return without altering DB significantly
        # (it might create thumbnail dir if storage_dir was interpretable as a path segment)
        # For this test, we assume db_path is valid but storage_dir is not.
        media_scanner.scan_directory(
            non_existent_dir, self.db_path, self.mock_image_classifier
        )
        result_from_db = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(
            result_from_db, {}, "DB should be empty if scan target dir doesn't exist."
        )

    def _assert_thumbnail_properties(
        self,
        base_thumbnail_dir,
        relative_thumb_path,
        original_image_source,
        expected_sha,
    ):
        full_thumb_path = os.path.join(base_thumbnail_dir, relative_thumb_path)
        self.assertTrue(
            os.path.exists(full_thumb_path), f"Thumbnail not found at {full_thumb_path}"
        )
        expected_subdir_name = expected_sha[:2]
        path_parts = os.path.normpath(relative_thumb_path).split(os.sep)
        self.assertEqual(path_parts[0], expected_subdir_name)
        self.assertEqual(
            path_parts[1], expected_sha + media_scanner.THUMBNAIL_EXTENSION
        )
        with Image.open(full_thumb_path) as thumb_img:
            self.assertEqual(thumb_img.size, media_scanner.THUMBNAIL_SIZE)
            self.assertEqual(thumb_img.format, "PNG")
            # ... (rest of the detailed pixel checks from original test if needed)

    def test_scan_directory_initial_scan_and_thumbnails(self):
        original_image_open = Image.open
        test_self = self

        def mock_image_open_for_gps_jpeg(fp, mode="r"):
            if isinstance(fp, str) and fp == test_self.file_img_gps:
                mock_img = Image.new("RGB", (120, 100), color="blue")
                mock_img.getexif = mock.Mock(
                    return_value=test_self.mock_exif_obj_for_gps_jpeg
                )
                return mock_img
            return original_image_open(fp, mode=mode)

        with unittest.mock.patch(
            "PIL.Image.open", side_effect=mock_image_open_for_gps_jpeg
        ):
            media_scanner.scan_directory(
                self.test_dir, self.db_path, self.mock_image_classifier, rescan=False
            )

        result_from_db = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(
            len(result_from_db), 6
        )  # img1, vid1, img2_subdir, square, img_exif, img_gps
        self.assertTrue(os.path.isdir(self.thumbnail_dir_path))

        # Check img1.jpg
        data_img1 = result_from_db.get(self.hash_img1)
        self.assertIsNotNone(data_img1)
        st_img1 = os.stat(self.file_img1)
        expected_date = getattr(st_img1, "st_birthtime", st_img1.st_mtime)
        self.assertAlmostEqual(
            data_img1["original_creation_date"], expected_date
        )
        self.assertIsNone(data_img1.get("latitude"))
        relative_thumb_path_img1 = os.path.join(
            self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION
        )
        self.assertEqual(data_img1["thumbnail_file"], relative_thumb_path_img1)
        self._assert_thumbnail_properties(
            self.thumbnail_dir_path,
            relative_thumb_path_img1,
            self.file_img1,
            self.hash_img1,
        )

        # Check video1.mp4
        data_vid1 = result_from_db.get(self.hash_vid1)
        self.assertIsNotNone(data_vid1)
        self.assertIsNotNone(data_vid1["thumbnail_file"])

        # Check image_with_exif.jpg
        data_img_exif = result_from_db.get(self.hash_img_exif)
        self.assertIsNotNone(data_img_exif)

        # Check image_with_gps.jpg
        data_img_gps = result_from_db.get(self.hash_img_gps)
        self.assertIsNotNone(data_img_gps)

    def test_rescan_no_changes(self):
        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=False
        )  # Initial scan
        initial_db_state = db_utils.get_all_media_files(self.db_path)

        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=True
        )  # Rescan
        rescan_db_state = db_utils.get_all_media_files(self.db_path)

        self.assertEqual(initial_db_state, rescan_db_state)
        # Check a specific thumbnail still exists
        relative_thumb_path_img1 = os.path.join(
            self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.thumbnail_dir_path, relative_thumb_path_img1)
            )
        )

    def test_rescan_add_image_file(self):
        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=False
        )  # Initial scan
        count_before = len(db_utils.get_all_media_files(self.db_path))

        new_img_path = create_dummy_file(
            self.test_dir,
            "new_image.gif",
            mtime=time.time() - 100,
            image_details={"size": (50, 70), "format": "GIF"},
        )
        new_img_hash = calculate_sha256_file(new_img_path)

        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=True
        )  # Rescan

        rescan_db_state = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(len(rescan_db_state), count_before + 1)
        self.assertIn(new_img_hash, rescan_db_state)
        new_db_entry = rescan_db_state[new_img_hash]
        relative_new_thumb_path = os.path.join(
            new_img_hash[:2], new_img_hash + media_scanner.THUMBNAIL_EXTENSION
        )
        self.assertEqual(new_db_entry["thumbnail_file"], relative_new_thumb_path)
        self._assert_thumbnail_properties(
            self.thumbnail_dir_path, relative_new_thumb_path, new_img_path, new_img_hash
        )

    def test_rescan_remove_image_file(self):
        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=False
        )  # Initial scan
        count_before = len(db_utils.get_all_media_files(self.db_path))

        # Ensure img1 and its thumbnail exist
        self.assertIsNotNone(
            db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
        )
        relative_thumb_path_img1 = os.path.join(
            self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION
        )
        full_thumb_path_img1 = os.path.join(
            self.thumbnail_dir_path, relative_thumb_path_img1
        )
        self.assertTrue(os.path.exists(full_thumb_path_img1))

        os.remove(self.file_img1)  # Remove the source file
        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=True
        )  # Rescan

        rescan_db_state = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(len(rescan_db_state), count_before - 1)
        self.assertNotIn(self.hash_img1, rescan_db_state)
        self.assertFalse(
            os.path.exists(full_thumb_path_img1),
            "Thumbnail of deleted file should be removed.",
        )

    def test_rescan_modify_image_mtime_only(self):
        """Test mtime change, SHA same, DB entry updated."""
        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=False
        )

        db_entry_before = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
        original_last_modified = db_entry_before["last_modified"]

        time.sleep(0.02)
        new_mtime = time.time() + 200
        os.utime(self.file_img1, (new_mtime, new_mtime))

        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=True
        )

        db_entry_after = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
        self.assertIsNotNone(db_entry_after)
        self.assertAlmostEqual(db_entry_after["last_modified"], new_mtime, places=5)
        self.assertNotAlmostEqual(
            db_entry_after["last_modified"], original_last_modified, places=5
        )

    # ... (Keep other tests like HEIC, subdir, generate_thumbnail, permissions, self-healing, adapting them for DB)
    # For example, test_thumbnail_cleanup_logic will now need to check db_utils.get_all_shas_and_thumbnails

    def test_scan_directory_with_gps(self):
        # This test uses the pre-existing image_with_gps.jpg created in setUp
        # It has known coordinates that should resolve to a specific city.
        media_scanner.scan_directory(
            self.test_dir, self.db_path, self.mock_image_classifier, rescan=False
        )

        db_entry = db_utils.get_media_file_by_sha(self.db_path, self.hash_img_gps)
        self.assertIsNotNone(db_entry)
        self.assertIn("city", db_entry)
        self.assertIn("country", db_entry)
        # The test coordinates from setUp are for Santa Monica, USA
        self.assertEqual(db_entry["city"], "Santa Monica")
        self.assertEqual(db_entry["country"], "United States")

    def test_tagging_model_change_and_retag(self):
        # 1. Initial scan with Resnet
        settings_path = os.path.join(self.test_dir, ".settings.json")
        settings_manager = media_scanner.SettingsManager(settings_path)
        settings = settings_manager.get()
        settings.tagging_model = "Resnet"
        settings_manager.write_settings(settings)

        settings_path = os.path.join(self.test_dir, "settings.json")
        settings_manager = media_scanner.SettingsManager(settings_path)
        settings = settings_manager.get()
        settings.tagging_model = "Resnet"
        settings_manager.write_settings(settings)

        with mock.patch(
            "media_server.image_classifier.ImageClassifier"
        ) as MockImageClassifier:
            mock_classifier_instance = MockImageClassifier.return_value
            mock_classifier_instance.classify_image.return_value = [("tag1", 0.9)]
            mock_classifier_instance.settings.tagging_model = "Resnet"

            media_scanner.scan_directory(
                self.test_dir, self.db_path, mock_classifier_instance, rescan=False
            )

            # 2. Verify initial state
            db_entry = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
            self.assertIsNotNone(db_entry)
            self.assertEqual(db_entry["tagging_model"], "Resnet")
            self.assertEqual(db_entry["tags"], '[["tag1", 0.9]]')
            self.assertEqual(
                mock_classifier_instance.classify_image.call_count, 5
            )  # 5 images

        # 3. Change settings to Mobilenet
        settings.tagging_model = "Mobilenet"
        settings_manager.write_settings(settings)

        with mock.patch(
            "media_server.image_classifier.ImageClassifier"
        ) as MockImageClassifier:
            mock_classifier_instance = MockImageClassifier.return_value
            mock_classifier_instance.classify_image.return_value = [("tag2", 0.8)]
            mock_classifier_instance.settings.tagging_model = "Mobilenet"
            media_scanner.scan_directory(
                self.test_dir, self.db_path, mock_classifier_instance, rescan=True
            )

            # 4. Verify updated state
            db_entry = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
            self.assertIsNotNone(db_entry)
            self.assertEqual(db_entry["tagging_model"], "Mobilenet")
            self.assertEqual(db_entry["tags"], '[["tag2", 0.8]]')
            self.assertEqual(mock_classifier_instance.classify_image.call_count, 5)

        # 5. Change settings to Off
        settings.tagging_model = "Off"
        settings_manager.write_settings(settings)

        with mock.patch(
            "media_server.image_classifier.ImageClassifier"
        ) as MockImageClassifier:
            mock_classifier_instance = MockImageClassifier.return_value
            mock_classifier_instance.settings.tagging_model = "Off"
            media_scanner.scan_directory(
                self.test_dir, self.db_path, mock_classifier_instance, rescan=True
            )

            # 6. Verify tags are not changed
            db_entry = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
            self.assertIsNotNone(db_entry)
            self.assertEqual(db_entry["tagging_model"], "Mobilenet")  # Stays the same
            self.assertEqual(db_entry["tags"], '[["tag2", 0.8]]')
            mock_classifier_instance.classify_image.assert_not_called()

    def test_scan_directory_with_progress_callback(self):
        reports = []

        def callback(info):
            reports.append(info)

        with mock.patch("media_server.image_classifier.ImageClassifier") as MockClassifier:
            mock_classifier = MockClassifier.return_value
            mock_classifier.settings.tagging_model = "Off"
            media_scanner.scan_directory(
                self.test_dir,
                self.db_path,
                mock_classifier,
                rescan=False,
                progress_callback=callback,
            )

        self.assertTrue(len(reports) >= 2)
        # Check discovering phase
        self.assertEqual(reports[0]["phase"], "discovering")
        # Check complete phase at end
        self.assertEqual(reports[-1]["phase"], "complete")
        self.assertEqual(reports[-1]["percent"], 100.0)

    def test_generate_thumbnail_force(self):
        # 1. Generate thumbnail initially
        thumb_rel = media_scanner.generate_thumbnail(
            self.file_img1, self.thumbnail_dir_path, self.hash_img1
        )
        self.assertIsNotNone(thumb_rel)
        thumb_abs = os.path.join(self.thumbnail_dir_path, thumb_rel)
        self.assertTrue(os.path.exists(thumb_abs))

        # 2. Re-generating without force returns existing path without rewriting
        thumb_rel2 = media_scanner.generate_thumbnail(
            self.file_img1, self.thumbnail_dir_path, self.hash_img1, force=False
        )
        self.assertEqual(thumb_rel, thumb_rel2)

        # 3. Generating with force=True re-writes the thumbnail
        thumb_rel3 = media_scanner.generate_thumbnail(
            self.file_img1, self.thumbnail_dir_path, self.hash_img1, force=True
        )
        self.assertEqual(thumb_rel, thumb_rel3)
        self.assertTrue(os.path.exists(thumb_abs))

    def test_scan_directory_force_rebuild(self):
        # 1. Initial scan
        with mock.patch("media_server.image_classifier.ImageClassifier") as MockClassifier:
            mock_classifier = MockClassifier.return_value
            mock_classifier.settings.tagging_model = "Off"
            media_scanner.scan_directory(
                self.test_dir,
                self.db_path,
                mock_classifier,
                rescan=False,
            )

        db_entry = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
        self.assertIsNotNone(db_entry)
        db_entry["tags"] = '[["old_tag", 0.5]]'
        db_entry["width"] = 9999
        db_utils.add_or_update_media_file(self.db_path, db_entry)

        # 2. Run scan_directory with force_rebuild=True and active model
        with mock.patch("media_server.image_classifier.ImageClassifier") as MockClassifier:
            mock_classifier = MockClassifier.return_value
            mock_classifier.settings.tagging_model = "Mobilenet"
            mock_classifier.classify_image.return_value = [("rebuilt_tag", 0.95)]
            media_scanner.scan_directory(
                self.test_dir,
                self.db_path,
                mock_classifier,
                rescan=False,
                force_rebuild=True,
            )

            # Verify classify_image was called
            self.assertTrue(mock_classifier.classify_image.called)

        # 3. Verify metadata was rebuilt
        rebuilt_entry = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
        self.assertIsNotNone(rebuilt_entry)
        self.assertEqual(rebuilt_entry["tags"], '[["rebuilt_tag", 0.95]]')
        self.assertEqual(rebuilt_entry["width"], 600)  # Re-extracted from image1.jpg (600, 400)

    def test_scan_portrait_jpeg_aspect_ratio(self):
        # Create a JPEG with raw dimensions 600x400 (landscape buffer) but EXIF orientation 6 (portrait)
        portrait_file = create_dummy_file(
            self.test_dir,
            "portrait.jpeg",
            image_details={"size": (600, 400), "format": "JPEG"},
            orientation=6,
        )
        portrait_sha = calculate_sha256_file(portrait_file)

        with mock.patch("media_server.image_classifier.ImageClassifier") as MockClassifier:
            mock_classifier = MockClassifier.return_value
            mock_classifier.settings.tagging_model = "Off"
            media_scanner.scan_directory(
                self.test_dir,
                self.db_path,
                mock_classifier,
                rescan=False,
            )

        entry = db_utils.get_media_file_by_sha(self.db_path, portrait_sha)
        self.assertIsNotNone(entry)
        # Transposed width and height should be 400 and 600 (portrait orientation)
        self.assertEqual(entry["width"], 400)
        self.assertEqual(entry["height"], 600)

    # --- Full EXIF Orientations 1-8 ---
    def test_all_exif_orientations_width_height(self):
        # Raw buffer: 400 wide x 200 high
        # Orientations 5, 6, 7, 8 swap width and height -> expect 200 x 400
        # Orientations 1, 2, 3, 4 preserve dimensions -> expect 400 x 200
        expected_dims = {
            1: (400, 200),
            2: (400, 200),
            3: (400, 200),
            4: (400, 200),
            5: (200, 400),
            6: (200, 400),
            7: (200, 400),
            8: (200, 400),
        }
        for orientation, (expected_w, expected_h) in expected_dims.items():
            fname = f"orient_{orientation}.jpg"
            fpath = create_dummy_file(
                self.test_dir,
                fname,
                image_details={"size": (400, 200), "format": "JPEG"},
                orientation=orientation,
            )
            sha = media_scanner.get_file_sha256(fpath)
            media_scanner.scan_directory(
                self.test_dir, self.db_path, self.mock_image_classifier, rescan=True
            )
            entry = db_utils.get_media_file_by_sha(self.db_path, sha)
            self.assertIsNotNone(entry, f"Failed for orientation {orientation}")
            self.assertEqual(entry["width"], expected_w, f"Width mismatch for orient {orientation}")
            self.assertEqual(entry["height"], expected_h, f"Height mismatch for orient {orientation}")

    # --- Format Matrix: WebP, PNG, GIF ---
    def test_image_formats_support(self):
        formats = [
            ("test.webp", "WEBP", (150, 100)),
            ("test.png", "PNG", (120, 80)),
            ("test.gif", "GIF", (90, 60)),
        ]
        for fname, fmt, size in formats:
            fpath = create_dummy_file(
                self.test_dir, fname, image_details={"size": size, "format": fmt}
            )
            sha = media_scanner.get_file_sha256(fpath)
            media_scanner.scan_directory(
                self.test_dir, self.db_path, self.mock_image_classifier, rescan=True
            )
            entry = db_utils.get_media_file_by_sha(self.db_path, sha)
            self.assertIsNotNone(entry, f"Failed to index {fmt}")
            self.assertEqual(entry["width"], size[0])
            self.assertEqual(entry["height"], size[1])

    # --- Video Binary Sniffing ---
    def test_is_plausible_video_binary(self):
        # 1. MP4 header
        mp4_file = os.path.join(self.test_dir, "sample.mp4")
        with open(mp4_file, "wb") as f:
            f.write(b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 32)
        self.assertTrue(media_scanner._is_plausible_video_binary(mp4_file))

        # 2. AVI header
        avi_file = os.path.join(self.test_dir, "sample.avi")
        with open(avi_file, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00AVI LIST\x00\x00\x00\x00" + b"\x00" * 32)
        self.assertTrue(media_scanner._is_plausible_video_binary(avi_file))

        # 3. Matroska/WebM header
        mkv_file = os.path.join(self.test_dir, "sample.mkv")
        with open(mkv_file, "wb") as f:
            f.write(b"\x1a\x45\xdf\xa3\x93\x42\x86\x81\x01\x42\xf7\x81\x01" + b"\x00" * 32)
        self.assertTrue(media_scanner._is_plausible_video_binary(mkv_file))

        # 4. Short / text file (<32 bytes)
        short_file = os.path.join(self.test_dir, "short.mp4")
        with open(short_file, "wb") as f:
            f.write(b"too short")
        self.assertFalse(media_scanner._is_plausible_video_binary(short_file))

    # --- Video Frame Extraction and Letterboxing ---
    def test_video_thumbnail_letterbox_aspect_ratio(self):
        frame_img = Image.new("RGBA", (640, 360), (0, 128, 255, 255))
        with mock.patch("media_server.media_scanner._extract_video_frame", return_value=frame_img):
            mp4_file = os.path.join(self.test_dir, "test_wide.mp4")
            with open(mp4_file, "wb") as f:
                f.write(b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 32)
            sha = hashlib.sha256(b"test_wide").hexdigest()
            thumb_rel = media_scanner.generate_thumbnail(mp4_file, self.thumbnail_dir_path, sha)
            self.assertIsNotNone(thumb_rel)
            thumb_path = os.path.join(self.thumbnail_dir_path, thumb_rel)
            with Image.open(thumb_path) as thumb:
                self.assertEqual(thumb.size, (256, 256))
                # Top border is black letterbox (0,0,0,255)
                self.assertEqual(thumb.getpixel((128, 5)), (0, 0, 0, 255))

    # --- File Rename Updates Database ---
    def test_file_renamed_preserves_original_filename(self):
        orig_file = create_dummy_file(
            self.test_dir, "original.jpg", image_details={"size": (100, 100), "format": "JPEG"}
        )
        sha = media_scanner.get_file_sha256(orig_file)
        media_scanner.scan_directory(self.test_dir, self.db_path, self.mock_image_classifier, rescan=False)

        entry1 = db_utils.get_media_file_by_sha(self.db_path, sha)
        self.assertEqual(entry1["filename"], "original.jpg")

        # Rename file on disk
        renamed_file = os.path.join(self.test_dir, "renamed.jpg")
        os.rename(orig_file, renamed_file)

        media_scanner.scan_directory(self.test_dir, self.db_path, self.mock_image_classifier, rescan=True)
        entry2 = db_utils.get_media_file_by_sha(self.db_path, sha)
        self.assertIsNotNone(entry2)
        self.assertEqual(entry2["filename"], "renamed.jpg")

    # --- Orphaned Thumbnails Cleanup ---
    def test_cleanup_orphaned_thumbnails(self):
        # Inject an orphaned thumbnail on disk not in DB
        orphan_dir = os.path.join(self.thumbnail_dir_path, "ff")
        os.makedirs(orphan_dir, exist_ok=True)
        orphan_file = os.path.join(orphan_dir, "ff" + "0" * 62 + ".png")
        with open(orphan_file, "wb") as f:
            f.write(b"dummy_orphan_thumbnail")

        self.assertTrue(os.path.exists(orphan_file))

        # Run orphan cleanup
        media_scanner._cleanup_orphaned_thumbnails(self.db_path, self.thumbnail_dir_path)

        # Orphan file and empty subdir should be pruned
        self.assertFalse(os.path.exists(orphan_file))
        self.assertFalse(os.path.exists(orphan_dir))

    # --- GPS DMS Conversion Edge Cases ---
    def test_convert_dms_to_decimal_edge_cases(self):
        # 1. Normal N/W
        lat = media_scanner._convert_dms_to_decimal(((34, 1), (5, 1), (12, 1)), "N")
        self.assertAlmostEqual(lat, 34 + 5 / 60 + 12 / 3600)

        # 2. Southern / Eastern hemisphere
        lat_s = media_scanner._convert_dms_to_decimal(((33, 1), (51, 1), (0, 1)), "S")
        self.assertAlmostEqual(lat_s, -(33 + 51 / 60))

        lon_e = media_scanner._convert_dms_to_decimal(((151, 1), (12, 1), (0, 1)), "E")
        self.assertAlmostEqual(lon_e, 151 + 12 / 60)

        # 3. Zero denominator protection
        lat_zero = media_scanner._convert_dms_to_decimal(((34, 1), (5, 0), (12, 1)), "N")
        self.assertAlmostEqual(lat_zero, 34 + 12 / 3600)

        # 4. Invalid length / ref
        self.assertIsNone(media_scanner._convert_dms_to_decimal((34, 5), "N"))
        self.assertIsNone(media_scanner._convert_dms_to_decimal(((34, 1), (5, 1), (12, 1)), "INVALID"))
        self.assertIsNone(media_scanner._convert_dms_to_decimal(None, "N"))


if __name__ == "__main__":
    unittest.main()

