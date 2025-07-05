import unittest
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

    def _assert_thumbnail_properties(self, thumb_path, original_image_path, expected_sha):
        self.assertTrue(os.path.exists(thumb_path), f"Thumbnail not found at {thumb_path}")
        with Image.open(thumb_path) as thumb_img:
            self.assertEqual(thumb_img.size, media_scanner.THUMBNAIL_SIZE, "Thumbnail dimensions are incorrect.")
            self.assertEqual(thumb_img.format, 'PNG', "Thumbnail format is not PNG.")

            with Image.open(original_image_path) as orig_img:
                orig_w, orig_h = orig_img.size
                thumb_w, thumb_h = media_scanner.THUMBNAIL_SIZE

                if orig_w == orig_h: # Square image
                    # For square images, there should be no transparency if scaled correctly
                    # unless the image itself had alpha. Assuming opaque test images for simplicity.
                    if thumb_img.mode == 'RGBA': # It will be RGBA due to Image.new("RGBA", ...)
                        # Check that it's not fully transparent. Sum of alpha should be > 0.
                        # For a perfectly opaque square image, all alpha values would be 255.
                        # Sum would be 255 * thumb_w * thumb_h
                        alpha_channel = thumb_img.getchannel('A')
                        is_transparent_everywhere = all(p == 0 for p in alpha_channel.getdata())
                        is_opaque_everywhere = all(p == 255 for p in alpha_channel.getdata())

                        # If original was perfectly square and opaque, thumbnail should be opaque.
                        # This depends on whether original test images are RGBA or RGB.
                        # Our dummy square image is JPEG, so it's RGB.
                        self.assertTrue(is_opaque_everywhere, "Square image thumbnail has unexpected transparency.")
                else: # Non-square image, expect padding
                    self.assertEqual(thumb_img.mode, 'RGBA', "Non-square image thumbnail is not RGBA (expected transparency).")
                    # Check corners for transparency (alpha value is 0)
                    self.assertEqual(thumb_img.getpixel((0,0))[3], 0, "Top-left pixel not transparent for non-square.")
                    self.assertEqual(thumb_img.getpixel((thumb_w-1,0))[3], 0, "Top-right pixel not transparent for non-square.")
                    self.assertEqual(thumb_img.getpixel((0,thumb_h-1))[3], 0, "Bottom-left pixel not transparent for non-square.")
                    self.assertEqual(thumb_img.getpixel((thumb_w-1,thumb_h-1))[3], 0, "Bottom-right pixel not transparent for non-square.")

                    # Check center area is not transparent (alpha value is 255)
                    center_x, center_y = thumb_w // 2, thumb_h // 2
                    self.assertEqual(thumb_img.getpixel((center_x, center_y))[3], 255, "Center pixel is transparent for non-square.")


    def test_scan_directory_initial_scan_and_thumbnails(self):
        result = media_scanner.scan_directory(self.test_dir)

        # Expected number of files: img1.jpg, video1.mp4, subdir/image2.png, square.jpg, image_with_exif.jpg
        self.assertEqual(len(result), 5)
        self.assertTrue(os.path.isdir(self.thumbnail_dir_path))

        # Check img1.jpg (no EXIF, should use ctime)
        self.assertIn(self.hash_img1, result)
        self.assertIn('original_creation_date', result[self.hash_img1])
        self.assertAlmostEqual(result[self.hash_img1]['original_creation_date'], os.path.getctime(self.file_img1), places=7)
        thumb_path_img1 = os.path.join(self.thumbnail_dir_path, self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self._assert_thumbnail_properties(thumb_path_img1, self.file_img1, self.hash_img1)

        # Check square.jpg (no EXIF, should use ctime)
        self.assertIn(self.hash_img3_square, result)
        self.assertIn('original_creation_date', result[self.hash_img3_square])
        self.assertAlmostEqual(result[self.hash_img3_square]['original_creation_date'], os.path.getctime(self.file_img3_square), places=7)
        thumb_path_img3 = os.path.join(self.thumbnail_dir_path, self.hash_img3_square + media_scanner.THUMBNAIL_EXTENSION)
        self._assert_thumbnail_properties(thumb_path_img3, self.file_img3_square, self.hash_img3_square)

        # Check video1.mp4 (no EXIF, should use ctime)
        self.assertIn(self.hash_vid1, result)
        self.assertIn('original_creation_date', result[self.hash_vid1])
        self.assertAlmostEqual(result[self.hash_vid1]['original_creation_date'], os.path.getctime(self.file_vid1), places=7)
        expected_thumb_path_vid1 = os.path.join(self.thumbnail_dir_path, self.hash_vid1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertFalse(os.path.exists(expected_thumb_path_vid1)) # No thumbnail for video

        # Check subdir/image2.png (no EXIF, should use ctime)
        self.assertIn(self.hash_img2, result)
        self.assertIn('original_creation_date', result[self.hash_img2])
        self.assertAlmostEqual(result[self.hash_img2]['original_creation_date'], os.path.getctime(self.file_img2_subdir), places=7)
        thumb_path_img2 = os.path.join(self.thumbnail_dir_path, self.hash_img2 + media_scanner.THUMBNAIL_EXTENSION)
        self._assert_thumbnail_properties(thumb_path_img2, self.file_img2_subdir, self.hash_img2)

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
        thumb_path_img_exif = os.path.join(self.thumbnail_dir_path, self.hash_img_exif + media_scanner.THUMBNAIL_EXTENSION)
        self._assert_thumbnail_properties(thumb_path_img_exif, self.file_img_exif, self.hash_img_exif)


        # Ensure .thumbnails directory content is not in scan results
        for item_sha in result:
            self.assertFalse(media_scanner.THUMBNAIL_DIR_NAME in result[item_sha]['file_path'])

    def test_rescan_no_changes(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        thumb_path_img1 = os.path.join(self.thumbnail_dir_path, self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertTrue(os.path.exists(thumb_path_img1))

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)
        self.assertEqual(initial_scan, rescan_result) # Should be identical if no changes
        self.assertTrue(os.path.exists(thumb_path_img1)) # Thumbnail still there

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
        new_thumb_path = os.path.join(self.thumbnail_dir_path, new_img_hash + media_scanner.THUMBNAIL_EXTENSION)
        self._assert_thumbnail_properties(new_thumb_path, new_img_path, new_img_hash)


    def test_rescan_remove_image_file(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        thumb_path_img1 = os.path.join(self.thumbnail_dir_path, self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertTrue(os.path.exists(thumb_path_img1))

        os.remove(self.file_img1)
        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan) - 1)
        self.assertNotIn(self.hash_img1, rescan_result)
        self.assertFalse(os.path.exists(thumb_path_img1))

    def test_rescan_modify_image_content_sha_changes(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        old_thumb_path_img1 = os.path.join(self.thumbnail_dir_path, self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertTrue(os.path.exists(old_thumb_path_img1))

        # Overwrite self.file_img1 with new content/image
        create_dummy_file(
            self.test_dir, os.path.basename(self.file_img1), # ensure same filename
            mtime=time.time() - 50, # ensure different mtime
            image_details={'size': (350, 350), 'color': 'purple', 'format': 'JPEG'} # New square image
        )
        new_hash_img1 = calculate_sha256_file(self.file_img1) # Recalculate hash for the modified file
        self.assertNotEqual(self.hash_img1, new_hash_img1, "SHA should change after content modification.")

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan))
        self.assertNotIn(self.hash_img1, rescan_result) # Old SHA removed
        self.assertFalse(os.path.exists(old_thumb_path_img1)) # Old thumbnail deleted

        self.assertIn(new_hash_img1, rescan_result) # New SHA added
        new_thumb_path_img1 = os.path.join(self.thumbnail_dir_path, new_hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self._assert_thumbnail_properties(new_thumb_path_img1, self.file_img1, new_hash_img1) # Check new thumbnail


    def test_rescan_modify_image_mtime_only_no_thumbnail_regen(self):
        initial_scan = media_scanner.scan_directory(self.test_dir)
        thumb_path = os.path.join(self.thumbnail_dir_path, self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertTrue(os.path.exists(thumb_path))
        thumb_mtime_before = os.path.getmtime(thumb_path)

        time.sleep(0.01) # Ensure mtime can change noticeably if file is touched
        new_mtime = time.time() + 100 # Make it distinct
        os.utime(self.file_img1, (new_mtime, new_mtime))

        rescan_result = media_scanner.scan_directory(self.test_dir, existing_data=initial_scan, rescan=True)

        self.assertEqual(len(rescan_result), len(initial_scan))
        self.assertIn(self.hash_img1, rescan_result)
        self.assertAlmostEqual(rescan_result[self.hash_img1]['last_modified'], new_mtime, places=7)

        self.assertTrue(os.path.exists(thumb_path))
        thumb_mtime_after = os.path.getmtime(thumb_path)
        self.assertEqual(thumb_mtime_before, thumb_mtime_after,
                         "Thumbnail mtime changed, indicating regeneration for mtime-only file change, which is not desired.")


    def test_thumbnail_cleanup_orphaned_and_non_image_in_thumbnails_dir(self):
        media_scanner.scan_directory(self.test_dir) # Initial scan to create .thumbnails and valid thumbs
        thumb_img1_path = os.path.join(self.thumbnail_dir_path, self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)
        self.assertTrue(os.path.exists(thumb_img1_path))

        # Create orphaned thumbnail
        orphaned_thumb_path = os.path.join(self.thumbnail_dir_path, "orphaned_sha123" + media_scanner.THUMBNAIL_EXTENSION)
        Image.new('RGB', (10,10), color='pink').save(orphaned_thumb_path, 'PNG') # Dummy PNG
        self.assertTrue(os.path.exists(orphaned_thumb_path))

        # Create non-thumbnail file in .thumbnails
        non_thumbnail_file_path = os.path.join(self.thumbnail_dir_path, "data.json")
        with open(non_thumbnail_file_path, "w") as f: f.write("{}")
        self.assertTrue(os.path.exists(non_thumbnail_file_path))

        # Rescan (use existing_data=None for a full fresh scan to trigger cleanup based on current state)
        current_media = media_scanner.scan_directory(self.test_dir, rescan=False) # This scan itself will perform cleanup

        self.assertTrue(os.path.exists(thumb_img1_path)) # Valid thumbnail remains
        self.assertFalse(os.path.exists(orphaned_thumb_path)) # Orphaned .png thumbnail removed
        self.assertTrue(os.path.exists(non_thumbnail_file_path)) # Non-thumbnail file remains

    def test_thumbnail_generation_for_image_in_subdir(self):
        # This is implicitly tested by test_scan_directory_initial_scan_and_thumbnails
        # but an explicit check can be here too.
        result = media_scanner.scan_directory(self.test_dir)
        self.assertIn(self.hash_img2, result) # img2 is in self.subdir
        thumb_path_img2 = os.path.join(self.thumbnail_dir_path, self.hash_img2 + media_scanner.THUMBNAIL_EXTENSION)
        self._assert_thumbnail_properties(thumb_path_img2, self.file_img2_subdir, self.hash_img2)

    def test_scan_directory_permissions_error_on_metadata(self):
        # This test is tricky to set up reliably across platforms for getmtime.
        # media_scanner logs errors from os.path.getmtime and skips the file.
        tricky_file_path = create_dummy_file(
            self.test_dir, "tricky.jpg",
            image_details={'size':(20,20), 'format':'JPEG'}
        )
        hash_tricky = calculate_sha256_file(tricky_file_path)


        original_os_path_getmtime = media_scanner.os.path.getmtime # Save original from module
        def mock_getmtime(path):
            if "tricky.jpg" in path:
                raise OSError("Simulated metadata read error")
            return original_os_path_getmtime(path) # Call original for other files

        media_scanner.os.path.getmtime = mock_getmtime

        # Perform a scan. Initial data is empty or non-existent for this particular tricky file.
        result = media_scanner.scan_directory(self.test_dir, existing_data={}, rescan=True)

        media_scanner.os.path.getmtime = original_os_path_getmtime # Restore

        self.assertNotIn(hash_tricky, result, "File with simulated getmtime error should be skipped.")
        thumb_tricky_path = os.path.join(self.thumbnail_dir_path, hash_tricky + media_scanner.THUMBNAIL_EXTENSION)
        self.assertFalse(os.path.exists(thumb_tricky_path),
                         "Thumbnail for file with getmtime error should not exist or be cleaned up if error happens during rescan logic for it.")

        # Other files should still be there and have thumbnails
        self.assertIn(self.hash_img1, result)
        self.assertTrue(os.path.exists(os.path.join(self.thumbnail_dir_path, self.hash_img1 + media_scanner.THUMBNAIL_EXTENSION)))


if __name__ == '__main__':
    unittest.main()
