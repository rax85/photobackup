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
from PIL import Image, ExifTags
from datetime import datetime as dt # Alias to avoid conflict with time module

# Helper to create dummy files with specific content and mtime
def create_dummy_file(dir_path, filename, content="dummy content", mtime=None, image_details=None, exif_datetime_original_str=None):
    filepath = os.path.join(dir_path, filename)
    exif_bytes = b''
    if image_details: # Create a real (but basic) image file
        try:
            img = Image.new(image_details.get('mode', 'RGB'),
                            image_details.get('size', (100,100)),
                            image_details.get('color', 'blue'))

            if exif_datetime_original_str and image_details.get('format', '').upper() in ['JPEG', 'TIFF']:
                exif_dict = {}
                # DateTimeOriginal tag ID is 36867
                # Pillow expects exif data as a dict where keys are tag IDs from ExifTags.TAGS
                # However, for saving, it needs the raw bytes from an Exif object.
                # A simpler way for testing is to construct minimal EXIF bytes.
                # For DateTimeOriginal (tag 36867 or 0x9003), the type is ASCII (2) and it needs a null terminator.
                # Format: TIFF header (MM for big endian, II for little) -> IFD0 offset -> Number of tags -> Tag entries
                # This is complex to build manually. Let's try using Pillow's Exif object if possible,
                # or ensure the test image format supports EXIF (JPEG, TIFF).

                # Pillow's img.save can take `exif=exif_bytes` argument.
                # We need to construct these bytes.
                # A more robust way is to load an image that has EXIF, modify it, and save.
                # For controlled testing, we can try to build a minimal one.
                # Example: exif_dict[ExifTags.TAGS.get('DateTimeOriginal')] = exif_datetime_original_str
                # This is for reading. For writing, it's more direct with bytes.

                try:
                    # Get an Exif object. If one doesn't exist, Pillow creates it.
                    exif = img.getexif()
                    exif[0x9003] = exif_datetime_original_str  # Set DateTimeOriginal (tag ID 36867 or 0x9003)
                    # The `save` method needs the EXIF data as bytes.
                    exif_bytes_to_save = exif.tobytes()
                    img.save(filepath, image_details.get('format', 'JPEG'), exif=exif_bytes_to_save)
                except Exception as exif_write_e:
                    # Adding a print for debugging in test environment if something goes wrong.
                    print(f"Warning: Test utility could not write EXIF data to {filename}: {exif_write_e}")
                    # Fallback to saving without EXIF if writing failed
                    img.save(filepath, image_details.get('format', 'JPEG'))
            else:
                # No EXIF requested or not a suitable format, save normally.
                img.save(filepath, image_details.get('format', 'JPEG'))

            # Note: content arg is ignored if image_details is provided, SHA will be of image file
        except Exception as e:
            # Fallback or error if Pillow fails (e.g. format not supported for saving)
            # print(f"Error creating dummy image {filepath}: {e}. Falling back to text file.")
            with open(filepath, "wb" if isinstance(content, bytes) else "w") as f: # write bytes if content is bytes
                f.write(content) # Fallback content
    else:
        with open(filepath, "wb" if isinstance(content, bytes) else "w") as f:
            f.write(content)


    if mtime is not None:
        os.utime(filepath, (mtime, mtime))
    return filepath

# Helper to calculate SHA256 for verification
def calculate_sha256_str(content_str):
    # Decode if bytes, because get_file_sha256 in media_scanner reads "rb" then decodes implicitly or explicitly for text files
    # For this helper, we assume if it's bytes, it's meant to be treated as a binary file's content string representation
    if isinstance(content_str, bytes):
        content_to_hash = content_str
    else:
        content_to_hash = content_str.encode('utf-8')
    return hashlib.sha256(content_to_hash).hexdigest()

def calculate_sha256_file(filepath):
    return media_scanner.get_file_sha256(filepath)


class TestMediaScanner(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp(prefix="media_server_test_")
        self.subdir = os.path.join(self.test_dir, "subdir")
        os.makedirs(self.subdir)
        self.thumbnail_dir_path = os.path.join(self.test_dir, media_scanner.THUMBNAIL_DIR_NAME)
        # scan_directory should create self.thumbnail_dir_path

        # For text-based dummy files for non-image media or simple tests
        self.content_vid1 = b"this is video1" # Use bytes for content for consistency if some files are binary
        self.hash_vid1 = calculate_sha256_str(self.content_vid1)

        # Create actual image files for thumbnail testing
        self.time_img1 = time.time() - 1000
        self.file_img1 = create_dummy_file(
            self.test_dir, "image1.jpg",
            content=b"fallback jpg content", # Fallback content if image creation fails
            mtime=self.time_img1,
            image_details={'size': (600, 400), 'color': 'red', 'format': 'JPEG'}
        )
        self.hash_img1 = calculate_sha256_file(self.file_img1) # SHA of actual image file

        self.time_vid1 = time.time() - 2000
        self.file_vid1 = create_dummy_file(self.test_dir, "video1.mp4", self.content_vid1, mtime=self.time_vid1)

        self.file_txt1 = create_dummy_file(self.test_dir, "document.txt", "this is a text document")

        self.time_img2 = time.time() - 500
        self.file_img2_subdir = create_dummy_file(
            self.subdir, "image2.png",
            content=b"fallback png content",
            mtime=self.time_img2,
            image_details={'size': (300, 500), 'color': 'green', 'format': 'PNG'}
        )
        self.hash_img2 = calculate_sha256_file(self.file_img2_subdir)

        self.file_img3_square = create_dummy_file(
            self.test_dir, "square.jpg",
            mtime=time.time() - 400,
            image_details={'size': (400,400), 'color': 'blue', 'format': 'JPEG'}
        )
        self.hash_img3_square = calculate_sha256_file(self.file_img3_square)

        # Image with EXIF data
        self.exif_date_str = "2001:01:01 10:00:00"
        self.exif_datetime_obj = dt.strptime(self.exif_date_str, "%Y:%m:%d %H:%M:%S")
        self.exif_timestamp = self.exif_datetime_obj.timestamp()
        self.time_img_exif = time.time() - 300
        self.file_img_exif = create_dummy_file(
            self.test_dir, "image_with_exif.jpg",
            mtime=self.time_img_exif,
            image_details={'size': (80,90), 'color': 'yellow', 'format': 'JPEG'},
            exif_datetime_original_str=self.exif_date_str
        )
        self.hash_img_exif = calculate_sha256_file(self.file_img_exif)


        self.file_unknown_ext = create_dummy_file(self.test_dir, "archive.xyz", b"unknown extension")

    def tearDown(self):
        # Clean up the temporary directory
        shutil.rmtree(self.test_dir)

    def test_is_media_file(self):
        self.assertTrue(media_scanner.is_media_file("test.jpg"))
        self.assertTrue(media_scanner.is_media_file("test.jpeg"))
        self.assertTrue(media_scanner.is_media_file("test.png"))
        self.assertTrue(media_scanner.is_media_file("test.gif"))
        self.assertTrue(media_scanner.is_media_file("test.mp4"))
        self.assertTrue(media_scanner.is_media_file("test.avi"))
        self.assertTrue(media_scanner.is_media_file("test.mov"))
        self.assertTrue(media_scanner.is_media_file("test.heic"))
        self.assertTrue(media_scanner.is_media_file("test.heif"))
        self.assertFalse(media_scanner.is_media_file("test.txt"))
        self.assertFalse(media_scanner.is_media_file("test.doc"))
        self.assertFalse(media_scanner.is_media_file("test.xyz")) # Unknown extension
        self.assertFalse(media_scanner.is_media_file("test_no_extension"))

    def test_get_file_sha256(self): # Combined test for sha256
        expected_hash = self.hash_img1
        actual_hash = media_scanner.get_file_sha256(self.file_img1)
        self.assertEqual(actual_hash, expected_hash)
        self.assertIsNone(media_scanner.get_file_sha256("non_existent_file.jpg"))

    def test_scan_directory_empty(self):
        empty_dir = os.path.join(self.test_dir, "empty_subdir")
        os.makedirs(empty_dir)
        result = media_scanner.scan_directory(empty_dir)
        self.assertEqual(result, {})
        self.assertTrue(os.path.isdir(os.path.join(empty_dir, media_scanner.THUMBNAIL_DIR_NAME)))

    def test_scan_directory_non_existent(self):
        result = media_scanner.scan_directory(os.path.join(self.test_dir, "does_not_exist"))
        self.assertEqual(result, {})

    def _assert_thumbnail_properties(self, base_thumbnail_dir, relative_thumb_path, original_image_source, expected_sha):
        """
        Asserts properties of a generated thumbnail.
        original_image_source: Can be a file path (str) or a PIL Image object.
        """
        # relative_thumb_path is like "ab/abcdef123.png"
        # base_thumbnail_dir is like "/tmp/test_dir/.thumbnails"
        full_thumb_path = os.path.join(base_thumbnail_dir, relative_thumb_path)
        self.assertTrue(os.path.exists(full_thumb_path), f"Thumbnail not found at {full_thumb_path}")

        # Check that the subdirectory matches the first two chars of SHA
        expected_subdir_name = expected_sha[:2]
        path_parts = os.path.normpath(relative_thumb_path).split(os.sep)
        self.assertEqual(path_parts[0], expected_subdir_name,
                         f"Thumbnail subdirectory '{path_parts[0]}' does not match SHA prefix '{expected_subdir_name}'.")
        self.assertEqual(path_parts[1], expected_sha + media_scanner.THUMBNAIL_EXTENSION,
                         f"Thumbnail filename '{path_parts[1]}' does not match expected SHA-based name.")


        with Image.open(full_thumb_path) as thumb_img:
            self.assertEqual(thumb_img.size, media_scanner.THUMBNAIL_SIZE, "Thumbnail dimensions are incorrect.")
            self.assertEqual(thumb_img.format, 'PNG', "Thumbnail format is not PNG.")

            opened_original_image = None
            if isinstance(original_image_source, str):
                opened_original_image = Image.open(original_image_source)
                orig_img_to_process = opened_original_image
            elif isinstance(original_image_source, Image.Image):
                orig_img_to_process = original_image_source # It's already an Image object
            else:
                self.fail(f"Unsupported original_image_source type: {type(original_image_source)}")

            try:
                # Simulate the resize dimensions that would occur in generate_thumbnail
                temp_orig_for_sim = orig_img_to_process.copy()
                temp_orig_for_sim.thumbnail(media_scanner.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                pasted_w, pasted_h = temp_orig_for_sim.size

                thumb_target_w, thumb_target_h = media_scanner.THUMBNAIL_SIZE
                # Calculate paste position
                paste_x_start = (thumb_target_w - pasted_w) // 2
                paste_y_start = (thumb_target_h - pasted_h) // 2

                self.assertEqual(thumb_img.mode, 'RGBA', "Thumbnail is not RGBA (expected transparency for padding).")

                # Check corners of the thumbnail canvas for transparency if there's any padding
                if pasted_w < thumb_target_w or pasted_h < thumb_target_h:
                    self.assertEqual(thumb_img.getpixel((0,0))[3], 0,
                                     f"Top-left pixel not transparent when padding exists. Pasted: {pasted_w}x{pasted_h}, Target: {thumb_target_w}x{thumb_target_h}")
                    self.assertEqual(thumb_img.getpixel((thumb_target_w-1,0))[3], 0,
                                     "Top-right pixel not transparent when padding exists.")
                    self.assertEqual(thumb_img.getpixel((0,thumb_target_h-1))[3], 0,
                                     "Bottom-left pixel not transparent when padding exists.")
                    self.assertEqual(thumb_img.getpixel((thumb_target_w-1,thumb_target_h-1))[3], 0,
                                     "Bottom-right pixel not transparent when padding exists.")

                # Check a point within the pasted image area for opacity (assuming original is opaque)
                # Take a pixel from the center of the pasted area.
                center_of_pasted_x = paste_x_start + pasted_w // 2
                center_of_pasted_y = paste_y_start + pasted_h // 2

                if 0 <= center_of_pasted_x < thumb_target_w and 0 <= center_of_pasted_y < thumb_target_h:
                    if pasted_w > 0 and pasted_h > 0: # Only check if there's an actual pasted image
                        self.assertEqual(thumb_img.getpixel((center_of_pasted_x, center_of_pasted_y))[3], 255,
                                         f"Center pixel of pasted image area ({center_of_pasted_x},{center_of_pasted_y}) is transparent. Pasted dims: {pasted_w}x{pasted_h}")
                elif pasted_w > 0 and pasted_h > 0 :
                    self.fail(f"Calculated center of pasted image ({center_of_pasted_x},{center_of_pasted_y}) is outside thumbnail dimensions ({thumb_target_w}x{thumb_target_h}). Pasted: {pasted_w}x{pasted_h}")
            finally:
                if opened_original_image: # Close the image if we opened it from a path
                    opened_original_image.close()


    def test_scan_directory_initial_scan_and_thumbnails(self):
        result = media_scanner.scan_directory(self.test_dir)

        # Expected number of files: img1.jpg, video1.mp4, subdir/image2.png, square.jpg, image_with_exif.jpg
        self.assertEqual(len(result), 5)
        self.assertTrue(os.path.isdir(self.thumbnail_dir_path))

        # Check img1.jpg (no EXIF, should use ctime)
        self.assertIn(self.hash_img1, result)
        self.assertIn('original_creation_date', result[self.hash_img1])
        self.assertAlmostEqual(result[self.hash_img1]['original_creation_date'], os.path.getctime(self.file_img1), places=7)
        relative_thumb_path_img1 = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(result[self.hash_img1]['thumbnail_file'], relative_thumb_path_img1)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_thumb_path_img1, self.file_img1, self.hash_img1)

        # Check square.jpg (no EXIF, should use ctime)
        self.assertIn(self.hash_img3_square, result)
        self.assertIn('original_creation_date', result[self.hash_img3_square])
        self.assertAlmostEqual(result[self.hash_img3_square]['original_creation_date'], os.path.getctime(self.file_img3_square), places=7)
        relative_thumb_path_img3 = os.path.join(self.hash_img3_square[:2], self.hash_img3_square + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(result[self.hash_img3_square]['thumbnail_file'], relative_thumb_path_img3)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_thumb_path_img3, self.file_img3_square, self.hash_img3_square)

        # Check video1.mp4 (no EXIF, should use ctime)
        self.assertIn(self.hash_vid1, result)
        self.assertIn('original_creation_date', result[self.hash_vid1])
        self.assertAlmostEqual(result[self.hash_vid1]['original_creation_date'], os.path.getctime(self.file_vid1), places=7)
        self.assertIsNone(result[self.hash_vid1]['thumbnail_file']) # No thumbnail for video
        # Check that no thumbnail file was created (neither new nor old style)
        old_style_thumb_path_vid1 = os.path.join(self.thumbnail_dir_path, self.hash_vid1 + media_scanner.THUMBNAIL_EXTENSION)
        new_style_thumb_path_vid1 = os.path.join(self.thumbnail_dir_path, self.hash_vid1[:2], self.hash_vid1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertFalse(os.path.exists(old_style_thumb_path_vid1))
        self.assertFalse(os.path.exists(new_style_thumb_path_vid1))


        # Check subdir/image2.png (no EXIF, should use ctime)
        self.assertIn(self.hash_img2, result)
        self.assertIn('original_creation_date', result[self.hash_img2])
        self.assertAlmostEqual(result[self.hash_img2]['original_creation_date'], os.path.getctime(self.file_img2_subdir), places=7)
        relative_thumb_path_img2 = os.path.join(self.hash_img2[:2], self.hash_img2 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(result[self.hash_img2]['thumbnail_file'], relative_thumb_path_img2)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_thumb_path_img2, self.file_img2_subdir, self.hash_img2)

        # Check image_with_exif.jpg (should use EXIF date)
        self.assertIn(self.hash_img_exif, result)
        self.assertIn('original_creation_date', result[self.hash_img_exif])
        # Ensure the EXIF writing worked, otherwise this test is not valid.
        # We can try to read it back here to be sure.
        try:
            with Image.open(self.file_img_exif) as img_check:
                exif_read_back = img_check._getexif()
                self.assertIsNotNone(exif_read_back, "EXIF data was not written to test file.")
                if exif_read_back: # if not None
                     self.assertEqual(exif_read_back.get(36867), self.exif_date_str, "DateTimeOriginal not written correctly to test file.")
        except Exception as e:
            self.fail(f"Failed to read EXIF from test file {self.file_img_exif}: {e}")

        self.assertAlmostEqual(result[self.hash_img_exif]['original_creation_date'], self.exif_timestamp, places=7,
                               msg=f"EXIF original date mismatch. Expected {self.exif_timestamp}, got {result[self.hash_img_exif]['original_creation_date']}")
        relative_thumb_path_img_exif = os.path.join(self.hash_img_exif[:2], self.hash_img_exif + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(result[self.hash_img_exif]['thumbnail_file'], relative_thumb_path_img_exif)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_thumb_path_img_exif, self.file_img_exif, self.hash_img_exif)


        # Ensure .thumbnails directory content is not in scan results
        for item_sha in result:
            self.assertFalse(media_scanner.THUMBNAIL_DIR_NAME in result[item_sha]['file_path'])

    def test_rescan_no_changes(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        # Construct the expected relative path for the thumbnail
        relative_thumb_path_img1 = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        full_thumb_path_img1 = os.path.join(self.thumbnail_dir_path, relative_thumb_path_img1)
        self.assertTrue(os.path.exists(full_thumb_path_img1))

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)
        self.assertEqual(initial_scan, rescan_result) # Should be identical if no changes
        self.assertTrue(os.path.exists(full_thumb_path_img1)) # Thumbnail still there
        self.assertEqual(rescan_result[self.hash_img1]['thumbnail_file'], relative_thumb_path_img1)


    def test_rescan_add_image_file(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        new_img_path = create_dummy_file(
            self.test_dir, "new_image.gif",
            mtime=time.time() -100, # ensure different mtime
            image_details={'size': (50,70), 'format': 'GIF'} # Non-square GIF
        )
        new_img_hash = calculate_sha256_file(new_img_path)

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)
        self.assertEqual(len(rescan_result), len(initial_scan) + 1)
        self.assertIn(new_img_hash, rescan_result)
        relative_new_thumb_path = os.path.join(new_img_hash[:2], new_img_hash + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(rescan_result[new_img_hash]['thumbnail_file'], relative_new_thumb_path)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_new_thumb_path, new_img_path, new_img_hash)


    def test_rescan_remove_image_file(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        relative_thumb_path_img1 = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        full_thumb_path_img1 = os.path.join(self.thumbnail_dir_path, relative_thumb_path_img1)
        self.assertTrue(os.path.exists(full_thumb_path_img1))
        thumb_subdir = os.path.dirname(full_thumb_path_img1)
        self.assertTrue(os.path.isdir(thumb_subdir))


        os.remove(self.file_img1)
        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan) - 1)
        self.assertNotIn(self.hash_img1, rescan_result)
        self.assertFalse(os.path.exists(full_thumb_path_img1))
        # Subdirectory should also be removed if it becomes empty (assuming only this thumb was in it for the test)
        # This depends on the orphan cleanup logic. If other files share the same prefix, it won't be removed.
        # For this test, hash_img1 is unique enough that its prefix dir should be unique too.
        if not any(sha.startswith(self.hash_img1[:2]) for sha in rescan_result if sha != self.hash_img1):
             self.assertFalse(os.path.exists(thumb_subdir), "Thumbnail subdirectory should be removed if empty.")


    def test_rescan_modify_image_content_sha_changes(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        old_relative_thumb_path_img1 = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        old_full_thumb_path_img1 = os.path.join(self.thumbnail_dir_path, old_relative_thumb_path_img1)
        self.assertTrue(os.path.exists(old_full_thumb_path_img1))
        old_thumb_subdir = os.path.dirname(old_full_thumb_path_img1)

        # Overwrite self.file_img1 with new content/image
        create_dummy_file(
            self.test_dir, os.path.basename(self.file_img1), # ensure same filename
            mtime=time.time() - 50, # ensure different mtime
            image_details={'size': (350, 350), 'color': 'purple', 'format': 'JPEG'} # New square image
        )
        new_hash_img1 = calculate_sha256_file(self.file_img1) # Recalculate hash for the modified file
        self.assertNotEqual(self.hash_img1, new_hash_img1, "SHA should change after content modification.")

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan)) # Length is same, one removed, one added
        self.assertNotIn(self.hash_img1, rescan_result) # Old SHA removed
        self.assertFalse(os.path.exists(old_full_thumb_path_img1)) # Old thumbnail deleted
        # Check if old subdirectory was removed, if it became empty
        if not any(sha.startswith(self.hash_img1[:2]) for sha in rescan_result):
            self.assertFalse(os.path.exists(old_thumb_subdir), "Old thumbnail subdirectory should be removed if empty.")


        self.assertIn(new_hash_img1, rescan_result) # New SHA added
        new_relative_thumb_path_img1 = os.path.join(new_hash_img1[:2], new_hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(rescan_result[new_hash_img1]['thumbnail_file'], new_relative_thumb_path_img1)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, new_relative_thumb_path_img1, self.file_img1, new_hash_img1) # Check new thumbnail


    def test_rescan_modify_image_mtime_only_no_thumbnail_regen(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        relative_thumb_path = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        full_thumb_path = os.path.join(self.thumbnail_dir_path, relative_thumb_path)
        self.assertTrue(os.path.exists(full_thumb_path))
        thumb_mtime_before = os.path.getmtime(full_thumb_path)

        time.sleep(0.01) # Ensure mtime can change noticeably if file is touched
        new_mtime = time.time() + 100 # Make it distinct
        os.utime(self.file_img1, (new_mtime, new_mtime))

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan))
        self.assertIn(self.hash_img1, rescan_result)
        self.assertAlmostEqual(rescan_result[self.hash_img1]['last_modified'], new_mtime, places=7)
        self.assertEqual(rescan_result[self.hash_img1]['thumbnail_file'], relative_thumb_path)


        self.assertTrue(os.path.exists(full_thumb_path))
        thumb_mtime_after = os.path.getmtime(full_thumb_path)
        self.assertEqual(thumb_mtime_before, thumb_mtime_after,
                         "Thumbnail mtime changed, indicating regeneration for mtime-only file change, which is not desired.")


    def test_thumbnail_cleanup_logic(self):
        # 1. Initial scan to create valid thumbnails and subdirs
        initial_scan_result = media_scanner.scan_directory(self.test_dir)
        valid_thumb_rel_path = initial_scan_result[self.hash_img1]['thumbnail_file']
        valid_thumb_full_path = os.path.join(self.thumbnail_dir_path, valid_thumb_rel_path)
        valid_thumb_subdir = os.path.dirname(valid_thumb_full_path)
        self.assertTrue(os.path.exists(valid_thumb_full_path))
        self.assertTrue(os.path.isdir(valid_thumb_subdir))

        # 2. Create an orphaned thumbnail in a new-style subdirectory
        orphan_sha_new_style = "aa" + "b" * 62 # e.g., aa/aabbb...bbb.png
        orphan_subdir_new_style = os.path.join(self.thumbnail_dir_path, orphan_sha_new_style[:2])
        os.makedirs(orphan_subdir_new_style, exist_ok=True)
        orphan_thumb_path_new_style = os.path.join(orphan_subdir_new_style, orphan_sha_new_style + media_scanner.THUMBNAIL_EXTENSION)
        Image.new('RGB', (10,10), color='pink').save(orphan_thumb_path_new_style, 'PNG')
        self.assertTrue(os.path.exists(orphan_thumb_path_new_style))

        # 3. Create an orphaned thumbnail in the old flat style (root of .thumbnails)
        orphan_sha_old_style = "cc" + "d" * 62
        orphan_thumb_path_old_style = os.path.join(self.thumbnail_dir_path, orphan_sha_old_style + media_scanner.THUMBNAIL_EXTENSION)
        Image.new('RGB', (10,10), color='green').save(orphan_thumb_path_old_style, 'PNG')
        self.assertTrue(os.path.exists(orphan_thumb_path_old_style))

        # 4. Create a non-thumbnail file in a thumbnail subdirectory
        non_thumbnail_file_in_subdir_path = os.path.join(valid_thumb_subdir, "data.json")
        with open(non_thumbnail_file_in_subdir_path, "w") as f: f.write("{}")
        self.assertTrue(os.path.exists(non_thumbnail_file_in_subdir_path))

        # 5. Create a non-thumbnail file in the root of .thumbnails
        non_thumbnail_file_in_root_path = os.path.join(self.thumbnail_dir_path, "notes.txt")
        with open(non_thumbnail_file_in_root_path, "w") as f: f.write("notes")
        self.assertTrue(os.path.exists(non_thumbnail_file_in_root_path))

        # 6. Create an empty subdirectory (should be removed)
        empty_thumb_subdir = os.path.join(self.thumbnail_dir_path, "ee")
        os.makedirs(empty_thumb_subdir, exist_ok=True)
        self.assertTrue(os.path.isdir(empty_thumb_subdir))


        # Perform a rescan. Cleanup happens at the end of scan_directory.
        # We pass the initial_scan_result as existing_data, so it knows about valid files.
        media_scanner.scan_directory(self.test_dir, existing_data=initial_scan_result, rescan=True)

        # Assertions:
        self.assertTrue(os.path.exists(valid_thumb_full_path), "Valid thumbnail should remain.")
        self.assertTrue(os.path.isdir(valid_thumb_subdir), "Valid thumbnail's subdirectory should remain.")

        self.assertFalse(os.path.exists(orphan_thumb_path_new_style), "New-style orphaned thumbnail should be removed.")
        self.assertFalse(os.path.exists(orphan_subdir_new_style), "New-style orphaned thumbnail's subdirectory should be removed as it's now empty.")

        self.assertFalse(os.path.exists(orphan_thumb_path_old_style), "Old-style orphaned thumbnail should be removed.")

        self.assertTrue(os.path.exists(non_thumbnail_file_in_subdir_path), "Non-thumbnail file in a valid subdir should remain.")
        self.assertTrue(os.path.exists(non_thumbnail_file_in_root_path), "Non-thumbnail file in .thumbnails root should remain.")
        self.assertFalse(os.path.exists(empty_thumb_subdir), "Empty thumbnail subdirectory should be removed.")
        self.assertTrue(os.path.isdir(self.thumbnail_dir_path), ".thumbnails directory itself should not be removed.")

    def test_scan_directory_heic_image(self):
        """Tests scanning and thumbnail generation for a HEIC image."""
        # NOTE: This test uses a mock for PIL.Image.open for HEIC files because
        # creating actual HEIC files programmatically is complex.
        # For more robust testing, replace 'dummy.heic' with a real, small HEIC file
        # and remove the mock if pillow-heif is expected to handle it directly.

        heic_filename = "test_image.heic"
        heic_content = b"simulated heic content" # Content doesn't matter due to mock
        heic_mtime = time.time() - 250

        # Create a dummy HEIC file. Its content doesn't need to be a real HEIC for this mocked test.
        file_heic_path = create_dummy_file(
            self.test_dir, heic_filename, content=heic_content, mtime=heic_mtime
        )
        # The hash will be of the dummy content, which is fine for testing the scanner logic.
        hash_heic = calculate_sha256_file(file_heic_path)

        # Create a mock PIL Image object that Image.open will return for the HEIC file
        mock_heic_image = Image.new('RGB', (100, 150), 'purple')

        original_image_open = Image.open # Keep a reference to the original Image.open

        def mock_image_open(fp, mode='r'):
            if isinstance(fp, str) and fp.endswith('.heic'):
                # Return a copy so that operations within generate_thumbnail (like close) don't affect the mock
                return mock_heic_image.copy()
            return original_image_open(fp, mode=mode)

        with unittest.mock.patch('PIL.Image.open', side_effect=mock_image_open) as mock_open:
            # Also need to mock getexif if we want to control that part for HEIC
            # For this test, assume no EXIF or default behavior is fine.
            # If specific EXIF handling for HEIC is needed, mock_heic_image.getexif could be set.
            mock_heic_image.getexif = mock.Mock(return_value=None) # No EXIF for this test case

            result = media_scanner.scan_directory(self.test_dir)

        self.assertIn(hash_heic, result, "HEIC image hash not found in scan results.")
        heic_data = result[hash_heic]
        self.assertEqual(heic_data['filename'], heic_filename)
        self.assertEqual(heic_data['file_path'], heic_filename) # Relative to test_dir
        self.assertAlmostEqual(heic_data['last_modified'], heic_mtime, places=7)
        # Default to ctime if no EXIF
        self.assertAlmostEqual(heic_data['original_creation_date'], os.path.getctime(file_heic_path), places=7)


        expected_thumb_rel_path = os.path.join(hash_heic[:2], hash_heic + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(heic_data['thumbnail_file'], expected_thumb_rel_path)

        # Verify the thumbnail was actually created and has correct properties
        # Pass the mock_heic_image directly, as file_heic_path is a dummy file.
        self._assert_thumbnail_properties(self.thumbnail_dir_path, expected_thumb_rel_path, mock_heic_image, hash_heic)

        # Check that Image.open was called for our HEIC file
        # Check if any call to mock_open had the heic_file_path as its first argument
        was_called_with_heic_path = False
        for call_args in mock_open.call_args_list:
            args, _ = call_args
            if args and args[0] == file_heic_path:
                was_called_with_heic_path = True
                break
        self.assertTrue(was_called_with_heic_path, f"PIL.Image.open was not called with the HEIC file path: {file_heic_path}")


    def test_thumbnail_generation_for_image_in_subdir(self):
        # This is implicitly tested by test_scan_directory_initial_scan_and_thumbnails
        # but an explicit check can be here too.
        result = media_scanner.scan_directory(self.test_dir) # Runs full scan
        self.assertIn(self.hash_img2, result) # img2 is in self.subdir
        relative_thumb_path_img2 = os.path.join(self.hash_img2[:2], self.hash_img2 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(result[self.hash_img2]['thumbnail_file'], relative_thumb_path_img2)
        self._assert_thumbnail_properties(self.thumbnail_dir_path, relative_thumb_path_img2, self.file_img2_subdir, self.hash_img2)


    def test_generate_thumbnail_return_value_and_creation(self):
        """Explicitly test generate_thumbnail's return value and file creation."""
        thumb_rel_path = media_scanner.generate_thumbnail(
            self.file_img1, self.thumbnail_dir_path, self.hash_img1
        )
        expected_rel_path = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(thumb_rel_path, expected_rel_path)

        full_thumb_path = os.path.join(self.thumbnail_dir_path, expected_rel_path)
        self.assertTrue(os.path.exists(full_thumb_path))
        # Can add more _assert_thumbnail_properties if needed, but it's covered elsewhere

    def test_scan_directory_permissions_error_on_metadata(self):
        # This test is tricky to set up reliably across platforms for getmtime.
        # media_scanner logs errors from os.path.getmtime and skips the file.
        tricky_file_path = create_dummy_file(
            self.test_dir, "tricky.jpg",
            image_details={'size':(20,20), 'format':'JPEG'}
        )
        hash_tricky = calculate_sha256_file(tricky_file_path)


        original_os_path_getmtime = os.path.getmtime # Save original from global os
        def mock_getmtime(path):
            if "tricky.jpg" in path:
                raise OSError("Simulated metadata read error")
            return original_os_path_getmtime(path) # Call original for other files

        # Mock os.path.getmtime within the media_scanner module's scope for the test
        with unittest.mock.patch('media_server.media_scanner.os.path.getmtime', mock_getmtime):
            # Perform a scan. Initial data is empty or non-existent for this particular tricky file.
            result = media_scanner.scan_directory(self.test_dir, existing_data={}, rescan=True)

        self.assertNotIn(hash_tricky, result, "File with simulated getmtime error should be skipped.")
        # Check both old and new style thumbnail paths for non-existence
        old_style_thumb_tricky_path = os.path.join(self.thumbnail_dir_path, hash_tricky + media_scanner.THUMBNAIL_EXTENSION)
        new_style_thumb_tricky_path = os.path.join(self.thumbnail_dir_path, hash_tricky[:2], hash_tricky + media_scanner.THUMBNAIL_EXTENSION)
        self.assertFalse(os.path.exists(old_style_thumb_tricky_path),
                         "Old style thumbnail for file with getmtime error should not exist.")
        self.assertFalse(os.path.exists(new_style_thumb_tricky_path),
                         "New style thumbnail for file with getmtime error should not exist.")
        thumb_tricky_subdir = os.path.join(self.thumbnail_dir_path, hash_tricky[:2])
        if os.path.exists(thumb_tricky_subdir): # Subdir might exist if other files had same prefix
            self.assertFalse(any(f.startswith(hash_tricky) for f in os.listdir(thumb_tricky_subdir)))


        # Other files should still be there and have thumbnails
        self.assertIn(self.hash_img1, result)
        valid_thumb_rel_path = os.path.join(self.hash_img1[:2], self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertTrue(os.path.exists(os.path.join(self.thumbnail_dir_path, valid_thumb_rel_path)))


    def test_scan_self_healing_from_flat_thumbnail(self):
        """Test if scan_directory correctly handles a file whose thumbnail is currently flat."""
        # 1. Create a source image
        img_path = create_dummy_file(
            self.test_dir, "self_heal_img.jpg",
            image_details={'size': (50, 50), 'color': 'cyan', 'format': 'JPEG'}
        )
        img_hash = calculate_sha256_file(img_path)

        # 2. Ensure .thumbnails directory exists
        os.makedirs(self.thumbnail_dir_path, exist_ok=True)

        # 3. Manually create its thumbnail in the old flat style
        old_flat_thumb_path = os.path.join(self.thumbnail_dir_path, img_hash + media_scanner.THUMBNAIL_EXTENSION)
        Image.new('RGB', media_scanner.THUMBNAIL_SIZE, 'magenta').save(old_flat_thumb_path, 'PNG')
        self.assertTrue(os.path.exists(old_flat_thumb_path))

        # 4. Ensure the new-style path does NOT exist yet
        new_style_subdir = os.path.join(self.thumbnail_dir_path, img_hash[:2])
        new_style_thumb_path = os.path.join(new_style_subdir, img_hash + media_scanner.THUMBNAIL_EXTENSION)
        self.assertFalse(os.path.exists(new_style_thumb_path))
        if os.path.exists(new_style_subdir): # cleanup if it exists from a prior test state for this prefix
            shutil.rmtree(new_style_subdir)


        # 5. Scan the directory.
        # Pass existing_data that either doesn't know about this SHA, or has no 'thumbnail_file' for it,
        # or has an incorrect 'thumbnail_file' (like the flat one).
        # Using rescan=False for a fresh build based on filesystem state.
        scan_result = media_scanner.scan_directory(self.test_dir, rescan=False)

        # 6. Assertions
        self.assertIn(img_hash, scan_result)
        # Cache should now point to the new, correct relative path
        expected_new_relative_path = os.path.join(img_hash[:2], img_hash + media_scanner.THUMBNAIL_EXTENSION)
        self.assertEqual(scan_result[img_hash]['thumbnail_file'], expected_new_relative_path)

        # New thumbnail should exist in the subdirectory
        self.assertTrue(os.path.exists(new_style_thumb_path), "New style thumbnail was not created.")
        self._assert_thumbnail_properties(self.thumbnail_dir_path,expected_new_relative_path,img_path,img_hash )


        # Old flat thumbnail should have been removed by orphan cleanup
        self.assertFalse(os.path.exists(old_flat_thumb_path),
                         "Old flat thumbnail was not removed after new one was generated.")


if __name__ == '__main__':
    unittest.main()
