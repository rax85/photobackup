import os
import hashlib
import mimetypes
from absl import logging
from typing import Dict, Optional, Tuple
from PIL import Image, ImageOps, ExifTags
from datetime import datetime
from pillow_heif import register_heif_opener

# Initialize mimetypes database
mimetypes.init()

# Register HEIF opener for Pillow
register_heif_opener()

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
        thumbnail_dir: Base directory where thumbnails are stored (e.g., .../.thumbnails).
        sha256_hex: SHA256 hash of the original image, used as thumbnail filename.
        target_size: A tuple (width, height) for the thumbnail.

    Returns:
        Relative path to the generated thumbnail within the base thumbnail_dir
        (e.g., 'ab/abcdef123...png'), or None if generation failed.
    """
    if not sha256_hex or len(sha256_hex) < 2:
        logging.error(f"Invalid sha256_hex for thumbnail generation: {sha256_hex}")
        return None

    sha256_prefix = sha256_hex[:2]
    thumbnail_subdir = os.path.join(thumbnail_dir, sha256_prefix)
    os.makedirs(thumbnail_subdir, exist_ok=True)

    thumbnail_filename_only = sha256_hex + THUMBNAIL_EXTENSION
    # Store the path relative to the main thumbnail_dir (e.g. .thumbnails/ab/hash.png)
    # The thumbnail_path is the full absolute path for saving
    thumbnail_path_absolute = os.path.join(thumbnail_subdir, thumbnail_filename_only)
    # The path to be returned and stored in cache should be relative to thumbnail_dir
    thumbnail_path_relative_to_basedir = os.path.join(sha256_prefix, thumbnail_filename_only)


    if os.path.exists(thumbnail_path_absolute):
        logging.debug(f"Thumbnail already exists: {thumbnail_path_absolute}")
        return thumbnail_path_relative_to_basedir

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

            final_thumb.save(thumbnail_path_absolute, "PNG")
            logging.info(f"Generated thumbnail: {thumbnail_path_absolute} for {source_image_path}")
            return thumbnail_path_relative_to_basedir
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
        # Process existing_data: make file_paths absolute for consistent checking, then relative for known_file_paths
        # This is important because 'root' in os.walk might be absolute or relative depending on storage_dir
        abs_storage_dir = os.path.abspath(storage_dir)

        processed_existing_data = {}
        for sha, data_item in existing_data.items():
            # Ensure existing file_path is absolute for reliable os.path.isfile checks later
            # and for comparison with paths from os.walk if storage_dir itself was relative.
            # However, the key for known_file_paths should be the relative path as stored in cache.
            path_in_cache = data_item.get('file_path')
            if path_in_cache:
                # If path_in_cache is already absolute, os.path.join does the right thing.
                # If it's relative, it's joined to abs_storage_dir.
                # This assumes path_in_cache is always relative to storage_dir.
                data_item['_abs_file_path_for_check'] = os.path.normpath(os.path.join(abs_storage_dir, path_in_cache))
            processed_existing_data[sha] = data_item
        current_media_data = processed_existing_data

        shas_to_remove = []
        for sha256_hex, data in current_media_data.items():
            abs_file_path_to_check = data.get('_abs_file_path_for_check')

            if not abs_file_path_to_check or not os.path.isfile(abs_file_path_to_check):
                logging.info(f"File for SHA {sha256_hex} (path: {data.get('file_path', 'unknown')}) no longer exists. Removing.")
                shas_to_remove.append(sha256_hex)
                # Delete corresponding thumbnail
                thumbnail_relative_path_from_cache = data.get('thumbnail_file') # This should be like 'ab/hash.png'
                if thumbnail_relative_path_from_cache:
                    thumbnail_to_delete_abs = os.path.join(thumbnail_dir_path, thumbnail_relative_path_from_cache)
                    if os.path.exists(thumbnail_to_delete_abs):
                        try:
                            os.remove(thumbnail_to_delete_abs)
                            logging.info(f"Deleted thumbnail: {thumbnail_to_delete_abs}")
                        except OSError as e:
                            logging.error(f"Error deleting thumbnail {thumbnail_to_delete_abs}: {e}")
                else:
                    # Fallback for older cache entries or if thumbnail_file was None/incorrectly stored
                    # This part might need careful handling if migrating from old format
                    sha256_prefix = sha256_hex[:2]
                    default_thumbnail_filename_only = f"{sha256_hex}{THUMBNAIL_EXTENSION}"
                    # Try new path structure first
                    potential_thumbnail_path = os.path.join(thumbnail_dir_path, sha256_prefix, default_thumbnail_filename_only)
                    if not os.path.exists(potential_thumbnail_path):
                        # Try old path structure (flat directory) as a fallback for migration
                        potential_thumbnail_path = os.path.join(thumbnail_dir_path, default_thumbnail_filename_only)

                    if os.path.exists(potential_thumbnail_path):
                        try:
                            os.remove(potential_thumbnail_path)
                            logging.info(f"Deleted thumbnail (fallback path logic): {potential_thumbnail_path}")
                        except OSError as e:
                            logging.error(f"Error deleting thumbnail (fallback path logic) {potential_thumbnail_path}: {e}")
                continue

            try:
                # Use absolute path for getmtime and get_file_sha256
                current_last_modified = os.path.getmtime(abs_file_path_to_check)
                if current_last_modified != data.get('last_modified'):
                    logging.info(f"File {data.get('filename', 'unknown')} (path: {data.get('file_path')}) has been modified. Re-hashing.")
                    new_sha256_hex = get_file_sha256(abs_file_path_to_check)
                    if new_sha256_hex and new_sha256_hex != sha256_hex:
                        shas_to_remove.append(sha256_hex)
                        logging.debug(f"SHA changed for {data.get('filename', 'unknown')}. Old: {sha256_hex}, New: {new_sha256_hex}. Old entry removed.")
                        old_thumbnail_relative_path = data.get('thumbnail_file') # e.g. 'ab/hash.png'
                        if old_thumbnail_relative_path:
                            old_thumbnail_to_delete_abs = os.path.join(thumbnail_dir_path, old_thumbnail_relative_path)
                            if os.path.exists(old_thumbnail_to_delete_abs):
                                try:
                                    os.remove(old_thumbnail_to_delete_abs)
                                    logging.info(f"Deleted old thumbnail: {old_thumbnail_to_delete_abs}")
                                except OSError as e:
                                    logging.error(f"Error deleting old thumbnail {old_thumbnail_to_delete_abs}: {e}")
                        else: # Fallback logic if path not in cache or for old format
                            old_sha256_prefix = sha256_hex[:2]
                            default_old_thumb_filename_only = f"{sha256_hex}{THUMBNAIL_EXTENSION}"
                            # Try new path structure first
                            potential_old_thumb_path = os.path.join(thumbnail_dir_path, old_sha256_prefix, default_old_thumb_filename_only)
                            if not os.path.exists(potential_old_thumb_path):
                                # Try old path structure (flat directory)
                                potential_old_thumb_path = os.path.join(thumbnail_dir_path, default_old_thumb_filename_only)

                            if os.path.exists(potential_old_thumb_path):
                                try:
                                    os.remove(potential_old_thumb_path)
                                    logging.info(f"Deleted old thumbnail (fallback path logic): {potential_old_thumb_path}")
                                except OSError as e:
                                    logging.error(f"Error deleting old thumbnail (fallback path logic) {potential_old_thumb_path}: {e}")
                        # New entry (and its thumbnail) will be added by the walk phase if the new SHA is valid.
                    elif new_sha256_hex == sha256_hex: # SHA is same, only mtime changed
                        current_media_data[sha256_hex]['last_modified'] = current_last_modified
                        logging.debug(f"Timestamp updated for {data.get('filename')} (SHA: {sha256_hex})")
                        # Potentially regenerate thumbnail if it's missing, though generate_thumbnail handles "exists"
                        # If thumbnail_file is not in data, or is None, it might mean it failed before.
                        if not data.get('thumbnail_file') and (mime_type := mimetypes.guess_type(abs_file_path_to_check)[0]) and mime_type.startswith('image/'):
                            logging.info(f"Attempting to regenerate missing thumbnail for modified file: {abs_file_path_to_check}")
                            new_thumb_rel_path = generate_thumbnail(abs_file_path_to_check, thumbnail_dir_path, sha256_hex)
                            if new_thumb_rel_path:
                                current_media_data[sha256_hex]['thumbnail_file'] = new_thumb_rel_path
                    elif not new_sha256_hex: # Error hashing the modified file
                        shas_to_remove.append(sha256_hex) # Remove old entry
                        thumb_relative_path_from_cache = data.get('thumbnail_file')
                        if thumb_relative_path_from_cache:
                            thumbnail_to_delete_abs = os.path.join(thumbnail_dir_path, thumb_relative_path_from_cache)
                            if os.path.exists(thumbnail_to_delete_abs):
                                try:
                                    os.remove(thumbnail_to_delete_abs)
                                    logging.info(f"Deleted thumbnail (hashing error for modified file): {thumbnail_to_delete_abs}")
                                except OSError as e:
                                    logging.error(f"Error deleting thumbnail {thumbnail_to_delete_abs}: {e}")
                        else: # Fallback
                            sha256_prefix = sha256_hex[:2]
                            default_thumb_filename_only = f"{sha256_hex}{THUMBNAIL_EXTENSION}"
                            potential_thumb_path = os.path.join(thumbnail_dir_path, sha256_prefix, default_thumb_filename_only)
                            if not os.path.exists(potential_thumb_path):
                                potential_thumb_path = os.path.join(thumbnail_dir_path, default_thumb_filename_only)
                            if os.path.exists(potential_thumb_path):
                                try:
                                    os.remove(potential_thumb_path)
                                    logging.info(f"Deleted thumbnail (hashing error, fallback path): {potential_thumb_path}")
                                except OSError as e:
                                    logging.error(f"Error deleting thumbnail (fallback path) {potential_thumb_path}: {e}")
            except OSError as e: # Error accessing file for mtime or other metadata
                logging.error(f"Could not get metadata for file {abs_file_path_to_check} during rescan: {e}")
                shas_to_remove.append(sha256_hex)
                thumb_relative_path_from_cache = data.get('thumbnail_file')
                if thumb_relative_path_from_cache:
                    thumbnail_to_delete_abs = os.path.join(thumbnail_dir_path, thumb_relative_path_from_cache)
                    if os.path.exists(thumbnail_to_delete_abs):
                        try:
                            os.remove(thumbnail_to_delete_abs)
                            logging.info(f"Deleted thumbnail (metadata error for source file): {thumbnail_to_delete_abs}")
                        except OSError as e_thumb:
                            logging.error(f"Error deleting thumbnail {thumbnail_to_delete_abs}: {e_thumb}")
                else: # Fallback
                    sha256_prefix = sha256_hex[:2]
                    default_thumb_filename_only = f"{sha256_hex}{THUMBNAIL_EXTENSION}"
                    potential_thumb_path = os.path.join(thumbnail_dir_path, sha256_prefix, default_thumb_filename_only)
                    if not os.path.exists(potential_thumb_path):
                        potential_thumb_path = os.path.join(thumbnail_dir_path, default_thumb_filename_only)
                    if os.path.exists(potential_thumb_path):
                        try:
                            os.remove(potential_thumb_path)
                            logging.info(f"Deleted thumbnail (metadata error, fallback path): {potential_thumb_path}")
                        except OSError as e_thumb:
                            logging.error(f"Error deleting thumbnail (fallback path) {potential_thumb_path}: {e_thumb}")

        for sha in shas_to_remove:
            if sha in current_media_data:
                 del current_media_data[sha]

        # Known file paths should be relative to storage_dir for comparison with rel_file_path from walk
        known_file_paths = {data['file_path'] for data in current_media_data.values() if 'file_path' in data}

    else: # Full scan or initial scan
        logging.info(f"Performing full scan of directory: {storage_dir}")
        current_media_data = {} # Start fresh for full scan
        known_file_paths = set()

    abs_storage_dir = os.path.abspath(storage_dir) # Ensure storage_dir is absolute for relpath calculation

    for root, dirs, files in os.walk(storage_dir):
        if THUMBNAIL_DIR_NAME in dirs:
            dirs.remove(THUMBNAIL_DIR_NAME)
            logging.debug(f"Excluding thumbnail directory from scan: {os.path.join(root, THUMBNAIL_DIR_NAME)}")

        for disk_filename in files:
            abs_file_path = os.path.normpath(os.path.join(root, disk_filename))
            rel_file_path = os.path.relpath(abs_file_path, abs_storage_dir)

            if not os.path.isfile(abs_file_path):
                logging.debug(f"Skipping non-file item: {abs_file_path}")
                continue

            # If rescanning and path already checked and exists, skip (unless content changed, handled above)
            # This check is more about avoiding re-processing of unchanged files already in cache.
            if rescan and rel_file_path in known_file_paths:
                # Find which SHA this path belongs to, to see if it was removed due to content change
                # This logic is a bit complex; the earlier loop (shas_to_remove) should handle SHA changes.
                # If it's still in known_file_paths, it means its SHA didn't change and it wasn't deleted.
                # However, it might be that a *different* file now has this path (e.g. user replaced it)
                # For now, if path is known, assume it was processed by the rescan logic above.
                # A more robust check might re-hash if mtime is different, even if path is "known".
                # The current rescan logic already re-hashes if mtime changes for known SHAs.
                # So, if rel_file_path is in known_file_paths, it means it's an existing, unchanged file,
                # or its mtime changed but SHA remained same (timestamp updated), or it was removed.
                # If it was removed (e.g. SHA changed), it won't be in current_media_data by its old SHA.
                # A file at this path whose content (and thus SHA) changed is effectively a new file for cache purposes.
                pass # Already handled by the modification/deletion check pass if rescan=True

            if is_media_file(abs_file_path):
                logging.debug(f"Processing media file: {abs_file_path} (relative: {rel_file_path})")
                sha256_hex = get_file_sha256(abs_file_path)
                if sha256_hex:
                    # thumbnail_file_name will store the relative path like "ab/hash.png"
                    thumbnail_relative_path = None
                    mime_type, _ = mimetypes.guess_type(abs_file_path)
                    if mime_type and mime_type.startswith('image/'):
                        # generate_thumbnail now returns the relative path (e.g., 'ab/hash.png')
                        thumbnail_relative_path = generate_thumbnail(abs_file_path, thumbnail_dir_path, sha256_hex)
                        # No need for os.path.basename here anymore as generate_thumbnail returns the desired format.

                    # Logic for adding or updating cache entry
                    existing_entry_for_sha = current_media_data.get(sha256_hex)
                    if not existing_entry_for_sha or existing_entry_for_sha.get('file_path') != rel_file_path:
                        # New SHA, or existing SHA but file moved/renamed (or multiple files with same SHA)
                        try:
                            last_modified = os.path.getmtime(abs_file_path)
                            filesystem_creation_time = os.path.getctime(abs_file_path)
                            original_creation_date = filesystem_creation_time # Default

                            if mime_type and mime_type.startswith('image/'):
                                try:
                                    with Image.open(abs_file_path) as img:
                                        exif_data = img.getexif()
                                        if exif_data:
                                            date_time_original_tag = 36867 # DateTimeOriginal
                                            if date_time_original_tag in exif_data:
                                                exif_date_str = exif_data[date_time_original_tag]
                                                dt_object = datetime.strptime(exif_date_str, '%Y:%m:%d %H:%M:%S')
                                                original_creation_date = dt_object.timestamp()
                                except Exception as exif_e:
                                    logging.warning(f"Could not read EXIF for {abs_file_path}: {exif_e}. Using filesystem time.")

                            entry_data = {
                                'filename': disk_filename, # Actual name on disk
                                'original_filename': existing_entry_for_sha.get('original_filename', disk_filename) if existing_entry_for_sha else disk_filename,
                                'file_path': rel_file_path,
                                'last_modified': last_modified,
                                'original_creation_date': original_creation_date,
                                'thumbnail_file': thumbnail_relative_path # Store the relative path
                            }
                            current_media_data[sha256_hex] = entry_data
                            logging.debug(f"Cache ADDED/UPDATED for SHA: {sha256_hex}, file: {disk_filename}, path: {rel_file_path}, thumb: {thumbnail_relative_path}")
                            # Add to known_file_paths if it's a new path being processed in this walk
                            known_file_paths.add(rel_file_path)

                        except OSError as e:
                            logging.error(f"Could not get metadata for {abs_file_path}: {e}")
                    # If SHA exists and file_path is the same, it means it was handled by the rescan logic for mtime updates.
            else:
                logging.debug(f"Skipping non-media file: {abs_file_path}")

    # Clean up _abs_file_path_for_check temporary key from data items
    if rescan:
        for sha in current_media_data:
            current_media_data[sha].pop('_abs_file_path_for_check', None)

    # Synchronize .thumbnails directory: remove any orphaned thumbnails
    if os.path.exists(thumbnail_dir_path):
        logging.info(f"Cleaning orphaned thumbnails in {thumbnail_dir_path}...")
        cleaned_count = 0
        # Walk through the thumbnail directory structure (e.g., .thumbnails/ab/hash.png)
        for root, dirs, files in os.walk(thumbnail_dir_path, topdown=False): # topdown=False for rmdir
            for file_name in files:
                if file_name.endswith(THUMBNAIL_EXTENSION):
                    # Construct the SHA from the path and filename
                    # Example: root = /path/to/.thumbnails/ab, file_name = abcdef123.png
                    # We need to check if 'abcdef123' is in current_media_data
                    thumb_sha_from_filename = file_name[:-len(THUMBNAIL_EXTENSION)]

                    # We also need to ensure the thumbnail_file entry in cache matches this structure.
                    # The cache stores 'ab/abcdef123.png' if 'ab' is the prefix dir.
                    # If root is thumbnail_dir_path itself, then it's an old flat thumbnail.
                    subdir_prefix = ""
                    if root != thumbnail_dir_path:
                        subdir_prefix = os.path.basename(root) # Should be 'ab'

                    # Reconstruct the relative path as it would be stored in cache
                    # For new structure: 'ab/hash.png'. For old structure: 'hash.png'
                    expected_cache_thumbnail_file = os.path.join(subdir_prefix, file_name) if subdir_prefix else file_name

                    # Check if this SHA is in current_media_data
                    # And if its 'thumbnail_file' entry matches the current file's relative path
                    media_item = current_media_data.get(thumb_sha_from_filename)
                    is_orphan = True
                    if media_item:
                        if media_item.get('thumbnail_file') == expected_cache_thumbnail_file:
                            is_orphan = False
                        else:
                            # SHA exists, but points to a different thumbnail path (e.g. after migration or error)
                            logging.warning(f"SHA {thumb_sha_from_filename} exists but its cached thumbnail path "
                                            f"'{media_item.get('thumbnail_file')}' does not match current path "
                                            f"'{expected_cache_thumbnail_file}'. Considering current file an orphan.")
                    else: # SHA not in current_media_data at all
                        # This also handles the case where the file is an old flat thumbnail
                        # and its SHA is no longer valid.
                        pass


                    if is_orphan:
                        orphaned_thumb_path_abs = os.path.join(root, file_name)
                        try:
                            os.remove(orphaned_thumb_path_abs)
                            logging.info(f"Removed orphaned thumbnail: {orphaned_thumb_path_abs}")
                            cleaned_count +=1
                        except OSError as e:
                            logging.error(f"Error removing orphaned thumbnail {orphaned_thumb_path_abs}: {e}")

            # After removing files in a directory, if the directory is empty, remove it
            # This applies only to subdirectories (e.g. .thumbnails/ab), not the main .thumbnails dir
            if root != thumbnail_dir_path and not os.listdir(root):
                try:
                    os.rmdir(root)
                    logging.info(f"Removed empty thumbnail subdirectory: {root}")
                except OSError as e:
                    logging.error(f"Error removing empty thumbnail subdirectory {root}: {e}")
        logging.info(f"Orphaned thumbnail cleanup complete. Removed {cleaned_count} files.")

    if rescan:
        logging.info(f"Rescan complete. Found {len(current_media_data)} media files.")
    else:
        logging.info(f"Initial scan complete. Found {len(current_media_data)} media files.")
    return current_media_data
