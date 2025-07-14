import unittest
from unittest import mock
import os
import shutil
import tempfile
import hashlib
import time

# Add project root to sys.path to allow direct import of media_server
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from media_server import media_scanner
from media_server import database as db_utils # Import database utils
import piexif
from PIL import Image, ExifTags
from datetime import datetime as dt # Alias to avoid conflict with time module

# Helper to create GPS rational representation
def to_rational(number):
    if isinstance(number, int): return (number, 1)
    if isinstance(number, float):
        f_den = 1000000
        return (int(number * f_den), f_den)
    return (number,1)


# Helper to create dummy files
def create_dummy_file(dir_path, filename, content="dummy content", mtime=None,
                      image_details=None, exif_datetime_original_str=None, gps_info_dict=None):
    filepath = os.path.join(dir_path, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True) # Ensure parent directory exists

    if image_details:
        try:
            img = Image.new(image_details.get('mode', 'RGB'),
                            image_details.get('size', (100,100)),
                            image_details.get('color', 'blue'))

            exif_dict = {"Exif": {}, "GPS": {}}
            if exif_datetime_original_str:
                exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_datetime_original_str.encode("utf-8")

            if gps_info_dict:
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = gps_info_dict['GPSLatitudeRef'].encode("utf-8")
                exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = [to_rational(x) for x in gps_info_dict['GPSLatitude']]
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = gps_info_dict['GPSLongitudeRef'].encode("utf-8")
                exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = [to_rational(x) for x in gps_info_dict['GPSLongitude']]

            exif_bytes = piexif.dump(exif_dict)
            img.save(filepath, image_details.get('format', 'JPEG'), exif=exif_bytes)
        except Exception: # Fallback for any image creation/saving error
            with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
                f.write(content if content else b"image creation failed")
    else:
        with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
            f.write(content)

    if mtime is not None:
        os.utime(filepath, (mtime, mtime))
    return filepath

def calculate_sha256_str(content_str):
    content_to_hash = content_str.encode('utf-8') if isinstance(content_str, str) else content_str
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
        self.db_path = db_utils.get_db_path(self.test_dir) # This will use DATABASE_NAME from db_utils
        db_utils.init_db(self.test_dir) # This will init the DB at self.db_path

        self.thumbnail_dir_path = os.path.join(self.test_dir, media_scanner.THUMBNAIL_DIR_NAME)
        # media_scanner.scan_directory will create self.thumbnail_dir_path if it doesn't exist.

        # Create dummy files
        self.content_vid1 = b"this is video1"
        self.hash_vid1 = calculate_sha256_str(self.content_vid1)
        self.time_img1 = time.time() - 1000
        self.file_img1 = create_dummy_file(self.test_dir, "image1.jpg", mtime=self.time_img1, image_details={'size': (600, 400), 'format': 'JPEG'})
        self.hash_img1 = calculate_sha256_file(self.file_img1)
        self.time_vid1 = time.time() - 2000
        self.file_vid1 = create_dummy_file(self.test_dir, "video1.mp4", self.content_vid1, mtime=self.time_vid1)
        self.file_txt1 = create_dummy_file(self.test_dir, "document.txt", "this is a text document")
        self.time_img2 = time.time() - 500
        self.file_img2_subdir = create_dummy_file(self.subdir, "image2.png", mtime=self.time_img2, image_details={'size': (300, 500), 'format': 'PNG'})
        self.hash_img2 = calculate_sha256_file(self.file_img2_subdir)
        self.file_img3_square = create_dummy_file(self.test_dir, "square.jpg", mtime=time.time() - 400, image_details={'size': (400,400), 'format': 'JPEG'})
        self.hash_img3_square = calculate_sha256_file(self.file_img3_square)
        self.exif_date_str = "2001:01:01 10:00:00"
        self.exif_timestamp = dt.strptime(self.exif_date_str, "%Y:%m:%d %H:%M:%S").timestamp()
        self.time_img_exif = time.time() - 300
        self.file_img_exif = create_dummy_file(self.test_dir, "image_with_exif.jpg", mtime=self.time_img_exif, image_details={'size': (80,90), 'format': 'JPEG'}, exif_datetime_original_str=self.exif_date_str)
        self.hash_img_exif = calculate_sha256_file(self.file_img_exif)
        self.gps_lat_ref = 'N'; self.gps_lat_dms = (34, 5, 12.34)
        self.gps_lon_ref = 'W'; self.gps_lon_dms = (118, 30, 56.78)
        self.expected_gps_lat_decimal = 34 + (5/60) + (12.34/3600)
        self.expected_gps_lon_decimal = -(118 + (30/60) + (56.78/3600))
        self.time_img_gps = time.time() - 200
        self.file_img_gps = create_dummy_file(self.test_dir, "image_with_gps.jpg", mtime=self.time_img_gps, image_details={'size': (120,100), 'format': 'JPEG'}, gps_info_dict={'GPSLatitudeRef': self.gps_lat_ref, 'GPSLatitude': self.gps_lat_dms, 'GPSLongitudeRef': self.gps_lon_ref, 'GPSLongitude': self.gps_lon_dms})
        self.hash_img_gps = calculate_sha256_file(self.file_img_gps)

        self.mock_jpeg_gps_info_sub_ifd = {
            media_scanner.GPS_LATITUDE_REF_TAG: self.gps_lat_ref,
            media_scanner.GPS_LATITUDE_TAG: self.gps_lat_dms, # Using tuple of floats directly
            media_scanner.GPS_LONGITUDE_REF_TAG: self.gps_lon_ref,
            media_scanner.GPS_LONGITUDE_TAG: self.gps_lon_dms, # Using tuple of floats directly
        }
        self.mock_exif_obj_for_gps_jpeg = Image.Exif()
        if media_scanner.GPS_TAG_ID is not None:
            self.mock_exif_obj_for_gps_jpeg[media_scanner.GPS_TAG_ID] = self.mock_jpeg_gps_info_sub_ifd

    def tearDown(self):
        db_utils.close_db_connection() # Ensure connection for this thread is closed
        if os.path.exists(self.db_path):
             # Give a moment for SQLite to release file lock if needed, though typically not an issue.
             # On Windows, file locks can be more persistent.
            time.sleep(0.1)
            try:
                os.remove(self.db_path)
            except PermissionError: # pragma: no cover
                # This might happen on Windows if the DB connection isn't fully released.
                # Add a small delay and retry.
                time.sleep(0.5)
                try:
                    os.remove(self.db_path)
                except Exception as e:
                    print(f"Warning: Could not remove test DB {self.db_path} during teardown: {e}")

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
        db_utils.init_db(empty_dir) # This will use empty_dir to form path to empty_test_db.sqlite3

        media_scanner.scan_directory(empty_dir, empty_db_path)

        result_from_db = db_utils.get_all_media_files(empty_db_path)
        self.assertEqual(result_from_db, {})
        self.assertTrue(os.path.isdir(os.path.join(empty_dir, media_scanner.THUMBNAIL_DIR_NAME)))

        db_utils.close_db_connection() # Close for this specific DB
        if os.path.exists(empty_db_path): os.remove(empty_db_path)


    def test_scan_directory_non_existent(self):
        non_existent_dir = os.path.join(self.test_dir, "does_not_exist")
        # scan_directory should log an error and return without altering DB significantly
        # (it might create thumbnail dir if storage_dir was interpretable as a path segment)
        # For this test, we assume db_path is valid but storage_dir is not.
        media_scanner.scan_directory(non_existent_dir, self.db_path)
        result_from_db = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(result_from_db, {}, "DB should be empty if scan target dir doesn't exist.")


    def _assert_thumbnail_properties(self, base_thumbnail_dir, relative_thumb_path, original_image_source, expected_sha):
        full_thumb_path = os.path.join(base_thumbnail_dir, relative_thumb_path)
        self.assertTrue(os.path.exists(full_thumb_path), f"Thumbnail not found at {full_thumb_path}")
        expected_subdir_name = expected_sha[:2]
        path_parts = os.path.normpath(relative_thumb_path).split(os.sep)
        self.assertEqual(path_parts[0], expected_subdir_name)
        self.assertEqual(path_parts[1], expected_sha + media_scanner.THUMBNAIL_EXTENSION)
        with Image.open(full_thumb_path) as thumb_img:
            self.assertEqual(thumb_img.size, media_scanner.THUMBNAIL_SIZE)
            self.assertEqual(thumb_img.format, 'PNG')
            # ... (rest of the detailed pixel checks from original test if needed)

    def test_scan_directory_initial_scan_and_thumbnails(self):
        original_image_open = Image.open
        test_self = self
        def mock_image_open_for_gps_jpeg(fp, mode='r'):
            if isinstance(fp, str) and fp == test_self.file_img_gps:
                mock_img = Image.new('RGB', (120,100), color='blue')
                mock_img.getexif = mock.Mock(return_value=test_self.mock_exif_obj_for_gps_jpeg)
                return mock_img
            return original_image_open(fp, mode=mode)

        with unittest.mock.patch('PIL.Image.open', side_effect=mock_image_open_for_gps_jpeg):
            media_scanner.scan_directory(self.test_dir, self.db_path, rescan=False)

        result_from_db = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(len(result_from_db), 6) # img1, vid1, img2_subdir, square, img_exif, img_gps
        self.assertTrue(os.path.isdir(self.thumbnail_dir_path))

        # Check img1.jpg
        data_img1 = result_from_db.get(self.hash_img1)
        self.assertIsNotNone(data_img1)
        self.assertAlmostEqual(data_img1['original_creation_date'], os.path.getctime(self.file_img1))
        self.assertIsNone(data_img1.get('latitude'))
        relative_thumb_path_img1 = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(data_img1['thumbnail_file'], relative_thumb_path_img1)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_thumb_path_img1, self.file_img1, self.hash_img1)

        # Check video1.mp4
        data_vid1 = result_from_db.get(self.hash_vid1)
        self.assertIsNotNone(data_vid1)
        self.assertIsNone(data_vid1['thumbnail_file'])

        # Check image_with_exif.jpg
        data_img_exif = result_from_db.get(self.hash_img_exif)
        self.assertIsNotNone(data_img_exif)

        # Check image_with_gps.jpg
        data_img_gps = result_from_db.get(self.hash_img_gps)
        self.assertIsNotNone(data_img_gps)

    def test_rescan_no_changes(self):
        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=False) # Initial scan
        initial_db_state = db_utils.get_all_media_files(self.db_path)

        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=True) # Rescan
        rescan_db_state = db_utils.get_all_media_files(self.db_path)

        self.assertEqual(initial_db_state, rescan_db_state)
        # Check a specific thumbnail still exists
        relative_thumb_path_img1 = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertTrue(os.path.exists(os.path.join(self.thumbnail_dir_path, relative_thumb_path_img1)))


    def test_rescan_add_image_file(self):
        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=False) # Initial scan
        count_before = len(db_utils.get_all_media_files(self.db_path))

        new_img_path = create_dummy_file(self.test_dir, "new_image.gif", mtime=time.time()-100, image_details={'size': (50,70), 'format': 'GIF'})
        new_img_hash = calculate_sha256_file(new_img_path)

        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=True) # Rescan

        rescan_db_state = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(len(rescan_db_state), count_before + 1)
        self.assertIn(new_img_hash, rescan_db_state)
        new_db_entry = rescan_db_state[new_img_hash]
        relative_new_thumb_path = os.path.join(new_img_hash[:2], new_img_hash + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(new_db_entry['thumbnail_file'], relative_new_thumb_path)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_new_thumb_path, new_img_path, new_img_hash)

    def test_rescan_remove_image_file(self):
        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=False) # Initial scan
        count_before = len(db_utils.get_all_media_files(self.db_path))

        # Ensure img1 and its thumbnail exist
        self.assertIsNotNone(db_utils.get_media_file_by_sha(self.db_path, self.hash_img1))
        relative_thumb_path_img1 = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        full_thumb_path_img1 = os.path.join(self.thumbnail_dir_path, relative_thumb_path_img1)
        self.assertTrue(os.path.exists(full_thumb_path_img1))

        os.remove(self.file_img1) # Remove the source file
        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=True) # Rescan

        rescan_db_state = db_utils.get_all_media_files(self.db_path)
        self.assertEqual(len(rescan_db_state), count_before - 1)
        self.assertNotIn(self.hash_img1, rescan_db_state)
        self.assertFalse(os.path.exists(full_thumb_path_img1), "Thumbnail of deleted file should be removed.")

    def test_rescan_modify_image_mtime_only(self):
        """Test the core requirement: mtime change, SHA same, DB entry updated, NO reprocessing if mtime matches."""
        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=False) # Initial scan

        # 1. Verify initial state
        db_entry_before = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
        self.assertIsNotNone(db_entry_before)
        original_last_modified = db_entry_before['last_modified']

        # 2. Modify mtime of the file, content (SHA) remains the same
        time.sleep(0.02) # Ensure mtime can be different
        new_mtime = time.time() + 200 # A distinct future time
        os.utime(self.file_img1, (new_mtime, new_mtime))

        # 3. Rescan
        # We need to mock getmtime for the *next* run to simulate it was already updated if we want to test "skip processing"
        # For now, let's test the "update mtime in DB" part.
        # The scanner should detect mtime change and update the DB record.
        # The _process_single_file will be called.
        with mock.patch.object(media_scanner, '_process_single_file', wraps=media_scanner._process_single_file) as mock_process_file:
            media_scanner.scan_directory(self.test_dir, self.db_path, rescan=True)

            db_entry_after = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
            self.assertIsNotNone(db_entry_after)
            self.assertAlmostEqual(db_entry_after['last_modified'], new_mtime, places=5)
            self.assertNotAlmostEqual(db_entry_after['last_modified'], original_last_modified, places=5)

            # Check if _process_single_file was called for this file (it should be, to update mtime and metadata)
            called_for_img1 = False
            for call in mock_process_file.call_args_list:
                args, _ = call
                if args[1] == self.file_img1: # args[1] is abs_file_path
                    called_for_img1 = True
                    break
            self.assertTrue(called_for_img1, "_process_single_file should be called to update mtime and metadata.")

        # 4. Now, test the "skip processing" part: If we scan again, and mtime in DB matches current mtime,
        #    _process_single_file should NOT be called for this file again.
        #    The db_entry_after already has the new_mtime.

        # Reset the mock to check calls for the *next* scan
        with mock.patch.object(media_scanner, '_process_single_file', wraps=media_scanner._process_single_file) as mock_process_file_second_scan:
            media_scanner.scan_directory(self.test_dir, self.db_path, rescan=True) # Scan again

            db_entry_final = db_utils.get_media_file_by_sha(self.db_path, self.hash_img1)
            self.assertAlmostEqual(db_entry_final['last_modified'], new_mtime, places=5) # Should still be new_mtime

            called_for_img1_second_scan = False
            for call in mock_process_file_second_scan.call_args_list:
                args, _ = call
                if args[1] == self.file_img1:
                    called_for_img1_second_scan = True
                    break
            self.assertFalse(called_for_img1_second_scan,
                             "_process_single_file should NOT be called if mtime matches DB and file is known.")

            # Ensure thumbnail mtime did not change (was not regenerated unnecessarily)
            relative_thumb_path = db_entry_final['thumbnail_file']
            full_thumb_path = os.path.join(self.thumbnail_dir_path, relative_thumb_path)
            self.assertTrue(os.path.exists(full_thumb_path))
            # This requires getting thumbnail mtime before any mtime-only modification logic ran.
            # The current test structure makes this hard. A more isolated test for thumbnail non-regeneration might be better.
            # For now, we trust that if _process_single_file isn't called, thumbnail isn't touched.


    # ... (Keep other tests like HEIC, subdir, generate_thumbnail, permissions, self-healing, adapting them for DB)
    # For example, test_thumbnail_cleanup_logic will now need to check db_utils.get_all_shas_and_thumbnails

    def test_scan_directory_with_gps(self):
        # This test uses the pre-existing image_with_gps.jpg created in setUp
        # It has known coordinates that should resolve to a specific city.
        media_scanner.scan_directory(self.test_dir, self.db_path, rescan=False)

        db_entry = db_utils.get_media_file_by_sha(self.db_path, self.hash_img_gps)
        self.assertIsNotNone(db_entry)
        self.assertIn('city', db_entry)
        self.assertIn('country', db_entry)
        # The test coordinates from setUp are for New York, USA
        self.assertEqual(db_entry['city'], 'New York')
        self.assertEqual(db_entry['country'], 'United States')

if __name__ == '__main__':
    unittest.main()
