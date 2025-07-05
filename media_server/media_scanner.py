import os
import hashlib
import mimetypes
from absl import logging
from typing import Dict, Optional, Tuple
from PIL import Image, ImageOps, ExifTags
from datetime import datetime

# Initialize mimetypes database
mimetypes.init()

THUMBNAIL_DIR_NAME = ".thumbnails"
THUMBNAIL_SIZE = (256, 256)
THUMBNAIL_EXTENSION = ".png"

def get_file_sha256(file_path: str) -> Optional[str]:
    """Computes the SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except IOError:
        logging.error(f"Could not read file for hashing: {file_path}")
        return None

def is_media_file(file_path: str) -> bool:
    """Checks if a file is an image or video based on its MIME type."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type.startswith('image/') or mime_type.startswith('video/')
    return False

def generate_thumbnail(source_image_path: str,
                       thumbnail_dir: str,
                       sha256_hex: str,
                       target_size: Tuple[int, int] = THUMBNAIL_SIZE) -> Optional[str]:
    """
    Generates a thumbnail for the given image.

    Args:
        source_image_path: Path to the original image.
        thumbnail_dir: Directory where thumbnails are stored.
        sha256_hex: SHA256 hash of the original image, used as thumbnail filename.
        target_size: A tuple (width, height) for the thumbnail.

    Returns:
        Path to the generated thumbnail, or None if generation failed.
    """
    thumbnail_filename = sha256_hex + THUMBNAIL_EXTENSION
    thumbnail_path = os.path.join(thumbnail_dir, thumbnail_filename)

    if os.path.exists(thumbnail_path):
        # Could add mtime check here if we want to update existing thumbnails
        # For now, if it exists, we assume it's correct.
        logging.debug(f"Thumbnail already exists: {thumbnail_path}")
        return thumbnail_path

    try:
        with Image.open(source_image_path) as img:
            # Use ImageOps.fit to resize and crop if necessary,
            # or create a letterbox/pillarbox effect.
            # To maintain aspect ratio and add transparent bands:
            img.thumbnail(target_size, Image.Resampling.LANCZOS)

            # Create a new image with transparent background
            final_thumb = Image.new("RGBA", target_size, (0, 0, 0, 0))

            # Calculate position to paste the resized image (centered)
            paste_x = (target_size[0] - img.width) // 2
            paste_y = (target_size[1] - img.height) // 2

            final_thumb.paste(img, (paste_x, paste_y))

            final_thumb.save(thumbnail_path, "PNG")
            logging.info(f"Generated thumbnail: {thumbnail_path} for {source_image_path}")
            return thumbnail_path
    except FileNotFoundError:
        logging.error(f"Source image not found for thumbnail generation: {source_image_path}")
        return None
    except Exception as e:
        logging.error(f"Failed to generate thumbnail for {source_image_path}: {e}")
        return None

def scan_directory(storage_dir: str,
                   existing_data: Optional[Dict[str, dict]] = None,
                   rescan: bool = False) -> Dict[str, dict]:
    """
    Scans a directory for media files and returns a dictionary with their
    SHA256 hash, filename, and last modified time.

    Args:
        storage_dir: The path to the directory to scan.
        existing_data: Optional. A dictionary of existing media file data to update.
                       If None, a full scan is performed.
        rescan: Optional. If True and existing_data is provided, performs a rescan
                checking for modifications and deletions.

    Returns:
        A dictionary where keys are SHA256 hashes and values are dicts
        containing 'filename', 'last_modified' timestamp, and 'file_path'.
    """
    if not os.path.isdir(storage_dir):
        logging.error(f"Storage directory not found: {storage_dir}")
        return {}

    thumbnail_dir_path = os.path.join(storage_dir, THUMBNAIL_DIR_NAME)
    os.makedirs(thumbnail_dir_path, exist_ok=True)
    logging.info(f"Thumbnail directory ensured at: {thumbnail_dir_path}")

    current_media_data = {}
    if existing_data and rescan:
        logging.info(f"Rescanning directory: {storage_dir}")
        current_media_data = existing_data.copy() # Start with a copy of existing data

        # Check for modifications and deletions
        shas_to_remove = []
        for sha256_hex, data in current_media_data.items():
            file_path = data.get('file_path') # Assumes file_path is stored
            if not file_path or not os.path.isfile(file_path):
                logging.info(f"File {data.get('filename', 'unknown')} (SHA: {sha256_hex}) no longer exists or path is missing. Removing.")
                shas_to_remove.append(sha256_hex)
                # Delete corresponding thumbnail
                thumbnail_to_delete = os.path.join(thumbnail_dir_path, sha256_hex + THUMBNAIL_EXTENSION)
                if os.path.exists(thumbnail_to_delete):
                    try:
                        os.remove(thumbnail_to_delete)
                        logging.info(f"Deleted thumbnail for removed file: {thumbnail_to_delete}")
                    except OSError as e:
                        logging.error(f"Error deleting thumbnail {thumbnail_to_delete}: {e}")
                continue

            try:
                current_last_modified = os.path.getmtime(file_path)
                if current_last_modified != data['last_modified']:
                    logging.info(f"File {data['filename']} has been modified. Re-hashing.")
                    new_sha256_hex = get_file_sha256(file_path)
                    if new_sha256_hex and new_sha256_hex != sha256_hex:
                        # SHA changed, means content changed. Remove old, new one will be added.
                        shas_to_remove.append(sha256_hex)
                        logging.debug(f"SHA changed for {data['filename']}. Old SHA: {sha256_hex}, New SHA: {new_sha256_hex}")
                        # Delete old thumbnail
                        old_thumbnail_to_delete = os.path.join(thumbnail_dir_path, sha256_hex + THUMBNAIL_EXTENSION)
                        if os.path.exists(old_thumbnail_to_delete):
                            try:
                                os.remove(old_thumbnail_to_delete)
                                logging.info(f"Deleted old thumbnail due to SHA change: {old_thumbnail_to_delete}")
                            except OSError as e:
                                logging.error(f"Error deleting old thumbnail {old_thumbnail_to_delete}: {e}")
                        # The new entry and its thumbnail will be added during the walk phase
                    elif new_sha256_hex == sha256_hex:
                        # Content is same (SHA same) but mtime changed. Just update mtime.
                        current_media_data[sha256_hex]['last_modified'] = current_last_modified
                        logging.debug(f"Timestamp updated for {data['filename']} (SHA: {sha256_hex})")
                        # Optionally, regenerate thumbnail if mtime changes, even if SHA is same
                        # For now, we don't regenerate if SHA is the same.
                    elif not new_sha256_hex: # Error hashing
                        shas_to_remove.append(sha256_hex) # Remove if hashing failed
                        # Also remove its thumbnail
                        thumbnail_to_delete = os.path.join(thumbnail_dir_path, sha256_hex + THUMBNAIL_EXTENSION)
                        if os.path.exists(thumbnail_to_delete):
                            try:
                                os.remove(thumbnail_to_delete)
                                logging.info(f"Deleted thumbnail due to hashing error on original: {thumbnail_to_delete}")
                            except OSError as e:
                                logging.error(f"Error deleting thumbnail {thumbnail_to_delete}: {e}")

            except OSError as e:
                logging.error(f"Could not get metadata for file {file_path} during rescan: {e}")
                shas_to_remove.append(sha256_hex) # Remove if metadata access fails
                 # Also remove its thumbnail
                thumbnail_to_delete = os.path.join(thumbnail_dir_path, sha256_hex + THUMBNAIL_EXTENSION)
                if os.path.exists(thumbnail_to_delete):
                    try:
                        os.remove(thumbnail_to_delete)
                        logging.info(f"Deleted thumbnail due to metadata error on original: {thumbnail_to_delete}")
                    except OSError as e_thumb:
                        logging.error(f"Error deleting thumbnail {thumbnail_to_delete}: {e_thumb}")


        for sha in shas_to_remove:
            if sha in current_media_data: # Ensure it wasn't already removed by some other logic
                 del current_media_data[sha]


        # Create a set of known file paths for quick lookup
        known_file_paths = {data['file_path'] for data in current_media_data.values() if 'file_path' in data}

    else: # Full scan or initial scan
        logging.info(f"Performing full scan of directory: {storage_dir}")
        known_file_paths = set() # No known files yet

    # Walk the directory for new files or files not in existing_data (if rescanning)
    for root, dirs, files in os.walk(storage_dir):
        # Exclude the thumbnail directory from scanning
        if THUMBNAIL_DIR_NAME in dirs:
            dirs.remove(THUMBNAIL_DIR_NAME)
            logging.debug(f"Excluding thumbnail directory from scan: {os.path.join(root, THUMBNAIL_DIR_NAME)}")

        for filename in files:
            file_path = os.path.join(root, filename)

            if not os.path.isfile(file_path): # Should not happen with os.walk's files list but good practice
                logging.debug(f"Skipping non-file item: {file_path}")
                continue

            if file_path in known_file_paths and rescan: # Already processed and checked if rescanning
                continue

            if is_media_file(file_path):
                logging.debug(f"Processing media file: {file_path}")
                sha256_hex = get_file_sha256(file_path)
                if sha256_hex:
                    # Generate thumbnail (it will check for existence internally)
                    # This is done for both new files and files whose SHA changed (old entry removed).
                    mime_type, _ = mimetypes.guess_type(file_path)
                    if mime_type and mime_type.startswith('image/'): # Only generate for images
                        generate_thumbnail(file_path, thumbnail_dir_path, sha256_hex)

                    if sha256_hex not in current_media_data or \
                       current_media_data[sha256_hex].get('file_path') != file_path: # Handle hash collisions or different paths
                        try:
                            last_modified = os.path.getmtime(file_path)
                            filesystem_creation_time = os.path.getctime(file_path)
                            original_creation_date = filesystem_creation_time # Default

                            if mime_type and mime_type.startswith('image/'):
                                try:
                                    with Image.open(file_path) as img:
                                        exif_data = img._getexif()
                                        if exif_data:
                                            # Tag ID for DateTimeOriginal
                                            date_time_original_tag = 36867
                                            if date_time_original_tag in exif_data:
                                                exif_date_str = exif_data[date_time_original_tag]
                                                # EXIF date format is typically 'YYYY:MM:DD HH:MM:SS'
                                                dt_object = datetime.strptime(exif_date_str, '%Y:%m:%d %H:%M:%S')
                                                original_creation_date = dt_object.timestamp()
                                                logging.debug(f"Found EXIF DateTimeOriginal for {filename}: {exif_date_str}")
                                            else:
                                                logging.debug(f"EXIF DateTimeOriginal tag not found for {filename}. Using filesystem creation time.")
                                        else:
                                            logging.debug(f"No EXIF data found for {filename}. Using filesystem creation time.")
                                except Exception as exif_e:
                                    logging.warning(f"Could not read or parse EXIF for {file_path}: {exif_e}. Using filesystem creation time.")
                            else:
                                logging.debug(f"Not an image or no MIME type for {filename}, using filesystem creation time for original_creation_date.")


                            current_media_data[sha256_hex] = {
                                'filename': filename,
                                'last_modified': last_modified,
                                'file_path': file_path,  # Store full path
                                'original_creation_date': original_creation_date
                            }
                            logging.debug(f"Added/Updated map for: {filename} (SHA256: {sha256_hex}) at path {file_path}")
                        except OSError as e:
                            logging.error(f"Could not get metadata for new/updated file {file_path}: {e}")
            else:
                logging.debug(f"Skipping non-media file: {file_path}")

    # Synchronize .thumbnails directory: remove any orphaned thumbnails
    if os.path.exists(thumbnail_dir_path):
        try:
            for thumb_filename in os.listdir(thumbnail_dir_path):
                if thumb_filename.endswith(THUMBNAIL_EXTENSION):
                    thumb_sha = thumb_filename[:-len(THUMBNAIL_EXTENSION)]
                    if thumb_sha not in current_media_data:
                        orphaned_thumb_path = os.path.join(thumbnail_dir_path, thumb_filename)
                        try:
                            os.remove(orphaned_thumb_path)
                            logging.info(f"Removed orphaned thumbnail: {orphaned_thumb_path}")
                        except OSError as e:
                            logging.error(f"Error removing orphaned thumbnail {orphaned_thumb_path}: {e}")
        except OSError as e:
            logging.error(f"Could not list thumbnail directory for cleanup {thumbnail_dir_path}: {e}")


    if rescan:
        logging.info(f"Rescan complete. Found {len(current_media_data)} media files.")
    else:
        logging.info(f"Initial scan complete. Found {len(current_media_data)} media files.")
    return current_media_data

if __name__ == '__main__':
    # Example Usage (for testing purposes)
    # Create a dummy directory and files
    if not os.path.exists("dummy_storage"):
        os.makedirs("dummy_storage/subdir")

    with open("dummy_storage/image.jpg", "w") as f: f.write("dummy image content")
    with open("dummy_storage/video.mp4", "w") as f: f.write("dummy video content")
    with open("dummy_storage/text.txt", "w") as f: f.write("dummy text content")
    with open("dummy_storage/subdir/another_image.png", "w") as f: f.write("another dummy image")

    # Configure absl logging for standalone script execution
    from absl import app
    from absl import flags
    FLAGS = flags.FLAGS
    # Define a dummy flag to satisfy absl.app.run
    try:
        flags.DEFINE_string('script_runner_flag', '', 'A dummy flag.')
    except flags.FlagsError:
        pass # Flag already defined

    def main(argv):
        del argv # Unused.
        logging.set_verbosity(logging.DEBUG)
        scanned_data = scan_directory("dummy_storage")
        print("Scanned Media Files:")
        for sha, data in scanned_data.items():
            print(f"  SHA256: {sha}, Filename: {data['filename']}, Last Modified: {data['last_modified']}")

        # Clean up dummy files and directory
        os.remove("dummy_storage/image.jpg")
        os.remove("dummy_storage/video.mp4")
        os.remove("dummy_storage/text.txt")
        os.remove("dummy_storage/subdir/another_image.png")
        os.rmdir("dummy_storage/subdir")
        os.rmdir("dummy_storage")

    app.run(main)
