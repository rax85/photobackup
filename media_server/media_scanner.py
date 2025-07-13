import os
import hashlib
import mimetypes
from absl import logging
from typing import Dict, Optional, Tuple, Set
from PIL import Image, ImageOps, ExifTags
from datetime import datetime
from pillow_heif import register_heif_opener

try:
    from . import database as db_utils # Relative import for package
    from .geolocator import GeoLocator
except ImportError:
    from media_server import database as db_utils # Fallback for direct execution/testing
    from media_server.geolocator import GeoLocator

# Initialize mimetypes database
mimetypes.init()

# Register HEIF opener for Pillow
register_heif_opener()

# GPS EXIF Processing
GPS_TAG_ID = None
for k, v in ExifTags.TAGS.items():
    if v == "GPSInfo":
        GPS_TAG_ID = k
        break

# GPSInfo sub-tags (values are integers)
GPS_LATITUDE_REF_TAG = 1
GPS_LATITUDE_TAG = 2
GPS_LONGITUDE_REF_TAG = 3
GPS_LONGITUDE_TAG = 4


def _convert_dms_to_decimal(dms_tuple: Tuple[float, ...], ref: str) -> Optional[float]:
    """Converts GPS DMS (Degrees, Minutes, Seconds) to decimal degrees."""
    if not dms_tuple or len(dms_tuple) != 3:
        return None

    try:
        def to_float(val):
            if isinstance(val, tuple) and len(val) == 2:
                return float(val[0]) / float(val[1])
            return float(val)

        degrees_val = to_float(dms_tuple[0])
        minutes_val = to_float(dms_tuple[1])
        seconds_val = to_float(dms_tuple[2])
    except (TypeError, ValueError, ZeroDivisionError) as e:
        logging.warning(f"Could not parse DMS component: {dms_tuple}. Error: {e}")
        return None

    decimal_degrees = degrees_val + (minutes_val / 60.0) + (seconds_val / 3600.0)

    if ref in ['S', 'W']:
        decimal_degrees = -decimal_degrees
    elif ref not in ['N', 'E']:
        logging.warning(f"Invalid GPS reference: {ref}")
        return None
    return decimal_degrees


def _get_gps_coordinates_from_exif(exif_data: dict) -> Tuple[Optional[float], Optional[float]]:
    """Extracts GPS latitude and longitude from EXIF data."""
    latitude = None
    longitude = None

    if not exif_data or not GPS_TAG_ID:
        return None, None

    try:
        gps_info = exif_data.get_ifd(GPS_TAG_ID)
    except KeyError:
        return None, None
    if not gps_info:
        return None, None

    logging.info(f"GPS Info: {gps_info}")
    try:
        gps_latitude_raw = gps_info.get(GPS_LATITUDE_TAG)
        gps_latitude_ref = gps_info.get(GPS_LATITUDE_REF_TAG)
        if gps_latitude_raw and gps_latitude_ref:
            latitude = _convert_dms_to_decimal(gps_latitude_raw, gps_latitude_ref)

        gps_longitude_raw = gps_info.get(GPS_LONGITUDE_TAG)
        gps_longitude_ref = gps_info.get(GPS_LONGITUDE_REF_TAG)
        if gps_longitude_raw and gps_longitude_ref:
            longitude = _convert_dms_to_decimal(gps_longitude_raw, gps_longitude_ref)
    except Exception as e:
        logging.warning(f"Error parsing GPS EXIF data: {e}. GPS Info was: {gps_info}")
        return None, None

    return latitude, longitude


THUMBNAIL_DIR_NAME = ".thumbnails"
THUMBNAIL_SIZE = (256, 256)
THUMBNAIL_EXTENSION = ".png"

def get_file_sha256(file_path: str) -> Optional[str]:
    """Computes the SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
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
                       thumbnail_dir: str, # Absolute path to .thumbnails directory
                       sha256_hex: str,
                       target_size: Tuple[int, int] = THUMBNAIL_SIZE) -> Optional[str]:
    """
    Generates a thumbnail for the given image.
    Returns: Relative path to the generated thumbnail within the base thumbnail_dir (e.g., 'ab/hash.png').
    """
    if not sha256_hex or len(sha256_hex) < 2:
        logging.error(f"Invalid sha256_hex for thumbnail generation: {sha256_hex}")
        return None

    sha256_prefix = sha256_hex[:2]
    # thumbnail_subdir is absolute: e.g. /path/to/storage/.thumbnails/ab
    thumbnail_subdir_abs = os.path.join(thumbnail_dir, sha256_prefix)
    os.makedirs(thumbnail_subdir_abs, exist_ok=True)

    thumbnail_filename_only = sha256_hex + THUMBNAIL_EXTENSION
    # thumbnail_path_absolute is the full absolute path for saving: e.g. /path/to/storage/.thumbnails/ab/hash.png
    thumbnail_path_absolute = os.path.join(thumbnail_subdir_abs, thumbnail_filename_only)
    # Path to be returned and stored in DB should be relative to thumbnail_dir: e.g. 'ab/hash.png'
    thumbnail_path_relative_to_basedir = os.path.join(sha256_prefix, thumbnail_filename_only)

    if os.path.exists(thumbnail_path_absolute):
        logging.debug(f"Thumbnail already exists: {thumbnail_path_absolute}")
        return thumbnail_path_relative_to_basedir

    try:
        with Image.open(source_image_path) as img:
            img.thumbnail(target_size, Image.Resampling.LANCZOS)
            final_thumb = Image.new("RGBA", target_size, (0, 0, 0, 0))
            paste_x = (target_size[0] - img.width) // 2
            paste_y = (target_size[1] - img.height) // 2
            final_thumb.paste(img, (paste_x, paste_y))
            final_thumb.save(thumbnail_path_absolute, "PNG")
            logging.info(f"Generated thumbnail: {thumbnail_path_absolute} for {source_image_path}")
            return thumbnail_path_relative_to_basedir
    except FileNotFoundError:
        logging.error(f"Source image not found for thumbnail generation: {source_image_path}")
    except Exception as e:
        logging.error(f"Failed to generate thumbnail for {source_image_path}: {e}")
    return None


def _delete_thumbnail_file(thumbnail_dir_abs: str, thumbnail_relative_path: Optional[str]):
    """Deletes a thumbnail file given its relative path and the absolute thumbnail base directory."""
    if not thumbnail_relative_path:
        return

    # Try the relative path directly (e.g., 'ab/hash.png')
    thumb_to_delete_abs = os.path.join(thumbnail_dir_abs, thumbnail_relative_path)

    # Also construct path from SHA if relative path is just filename (legacy or error)
    # This part is tricky if thumbnail_relative_path is malformed or from an old system.
    # For now, assume thumbnail_relative_path is correctly 'prefix/hash.ext' or 'hash.ext'.
    # If it's just 'hash.ext', os.path.join(thumbnail_dir_abs, 'hash.ext') is correct for flat structure.

    if os.path.exists(thumb_to_delete_abs):
        try:
            os.remove(thumb_to_delete_abs)
            logging.info(f"Deleted thumbnail: {thumb_to_delete_abs}")
        except OSError as e:
            logging.error(f"Error deleting thumbnail {thumb_to_delete_abs}: {e}")
    else:
        # If the path was just 'hash.ext', it might be an old flat thumbnail.
        # This case is less likely if generate_thumbnail always returns prefix/hash.ext
        # but could be relevant if old data exists or if thumbnail_relative_path is just filename.
        if not os.path.dirname(thumbnail_relative_path): # It's a flat filename
             # This means thumb_to_delete_abs was already correct for a flat structure.
             # No need for further action if it didn't exist.
             logging.debug(f"Thumbnail {thumb_to_delete_abs} (potentially flat) not found for deletion.")


def scan_directory(storage_dir: str, db_path: str, rescan: bool = False) -> None:
    """
    Scans a directory for media files, updating the SQLite database.

    Args:
        storage_dir: The path to the directory to scan.
        db_path: Path to the SQLite database file.
        rescan: If True, performs a rescan checking for modifications and deletions.
                If False, performs a full scan, adding new files and updating existing
                ones if their last_modified time has changed (or if they are new).
    """
    if not os.path.isdir(storage_dir):
        logging.error(f"Storage directory not found: {storage_dir}")
        return

    thumbnail_dir_abs = os.path.join(storage_dir, THUMBNAIL_DIR_NAME)
    os.makedirs(thumbnail_dir_abs, exist_ok=True)
    logging.info(f"Thumbnail directory ensured at: {thumbnail_dir_abs}")

    geolocator = GeoLocator()
    cities_csv_path = os.path.join(os.path.dirname(__file__), 'resources', 'cities.csv')
    geolocator.load_cities(cities_csv_path)

    abs_storage_dir = os.path.abspath(storage_dir)
    processed_rel_file_paths: Set[str] = set() # Keep track of files processed in this scan run

    # Phase 1: Handle existing files in DB during a rescan
    if rescan:
        logging.info(f"Rescanning directory: {storage_dir} using DB: {db_path}")
        db_file_entries = db_utils.get_all_media_files(db_path) # Get all entries: {sha: data}

        for sha256_hex, db_entry in db_file_entries.items():
            rel_file_path = db_entry.get('file_path')
            if not rel_file_path:
                logging.warning(f"DB entry for SHA {sha256_hex} is missing file_path. Skipping.")
                continue

            abs_file_path_to_check = os.path.normpath(os.path.join(abs_storage_dir, rel_file_path))
            processed_rel_file_paths.add(rel_file_path) # Mark as seen from DB perspective

            if not os.path.isfile(abs_file_path_to_check):
                logging.info(f"File for SHA {sha256_hex} (path: {rel_file_path}) no longer exists. Removing from DB.")
                _delete_thumbnail_file(thumbnail_dir_abs, db_entry.get('thumbnail_file'))
                db_utils.delete_media_file_by_sha(db_path, sha256_hex)
                continue

            try:
                current_fs_last_modified = os.path.getmtime(abs_file_path_to_check)
                db_last_modified = db_entry.get('last_modified')

                if abs(current_fs_last_modified - db_last_modified) > 1e-6: # Compare floats carefully
                    logging.info(f"File {rel_file_path} (SHA: {sha256_hex}) has been modified. Re-processing.")
                    # File content might have changed, leading to a new SHA, or just metadata like mtime.
                    new_sha256_hex = get_file_sha256(abs_file_path_to_check)

                    if not new_sha256_hex: # Error hashing, treat as problematic
                        logging.error(f"Could not re-hash modified file {rel_file_path}. Removing old DB entry.")
                        _delete_thumbnail_file(thumbnail_dir_abs, db_entry.get('thumbnail_file'))
                        db_utils.delete_media_file_by_sha(db_path, sha256_hex)
                        continue

                    if new_sha256_hex != sha256_hex:
                        logging.info(f"SHA changed for {rel_file_path}. Old: {sha256_hex}, New: {new_sha256_hex}. Updating DB.")
                        # Delete old entry (and its thumbnail)
                        _delete_thumbnail_file(thumbnail_dir_abs, db_entry.get('thumbnail_file'))
                        db_utils.delete_media_file_by_sha(db_path, sha256_hex)
                        # The new SHA version will be picked up by the walk phase as a new file.
                        # We remove it from processed_rel_file_paths so the walk processes it.
                        processed_rel_file_paths.remove(rel_file_path)
                    else: # SHA is the same, only mtime (and possibly other metadata) changed
                        logging.info(f"Timestamp updated for {rel_file_path} (SHA: {sha256_hex}). Re-extracting metadata.")
                        # Re-extract metadata and update DB. Thumbnail should be fine if SHA is same.
                        # However, if thumbnail was missing, try to regenerate.
                        _process_single_file(abs_storage_dir, abs_file_path_to_check, sha256_hex, db_path, thumbnail_dir_abs, geolocator, db_entry.get('original_filename', os.path.basename(rel_file_path)))
                        # No need to remove from processed_rel_file_paths, as it's updated.
                else:
                    # File exists and last_modified is same.
                    # Check if thumbnail exists if it's supposed to.
                    mime_type, _ = mimetypes.guess_type(abs_file_path_to_check)
                    if mime_type and mime_type.startswith('image/') and db_entry.get('thumbnail_file'):
                        thumb_rel_path = db_entry['thumbnail_file']
                        if not os.path.exists(os.path.join(thumbnail_dir_abs, thumb_rel_path)):
                            logging.info(f"Thumbnail missing for {rel_file_path} (SHA: {sha256_hex}). Regenerating.")
                            new_thumb_rel_path = generate_thumbnail(abs_file_path_to_check, thumbnail_dir_abs, sha256_hex)
                            if new_thumb_rel_path:
                                db_utils.update_media_file_fields(db_path, sha256_hex, {'thumbnail_file': new_thumb_rel_path})
                    logging.debug(f"File {rel_file_path} (SHA: {sha256_hex}) is unchanged.")

            except OSError as e:
                logging.error(f"Could not get metadata for file {abs_file_path_to_check} during rescan: {e}. Removing from DB.")
                _delete_thumbnail_file(thumbnail_dir_abs, db_entry.get('thumbnail_file'))
                db_utils.delete_media_file_by_sha(db_path, sha256_hex)

    else: # Full scan (rescan=False) or initial scan
        logging.info(f"Performing full/initial scan of directory: {storage_dir} using DB: {db_path}")
        # We will iterate all files. If a file is already in DB with same mtime, we can skip.
        # Otherwise, we process and add/update.
        # Files in DB not found on disk will be handled by a cleanup phase later if rescan=False.
        # For now, rescan=False focuses on adding/updating from disk.

    # Phase 2: Walk the directory for new files or files not handled by rescan's DB check
    logging.info("Scanning filesystem for new or changed files...")
    for root, dirs, files in os.walk(abs_storage_dir):
        if THUMBNAIL_DIR_NAME in dirs: # Correctly compare with basename
            dirs.remove(THUMBNAIL_DIR_NAME) # Exclude .thumbnails from scan

        for disk_filename in files:
            abs_file_path = os.path.normpath(os.path.join(root, disk_filename))
            rel_file_path = os.path.relpath(abs_file_path, abs_storage_dir)

            if not os.path.isfile(abs_file_path): # Should not happen with os.walk's `files`
                logging.debug(f"Skipping non-file item: {abs_file_path}")
                continue

            if rel_file_path in processed_rel_file_paths and rescan:
                # This file was already handled by the rescan logic (Phase 1)
                # or it was a file whose SHA changed and was removed from processed_rel_file_paths
                # to be re-added here. If it's still in processed_rel_file_paths, it means it was
                # confirmed up-to-date or mtime was updated for same SHA.
                logging.debug(f"File {rel_file_path} already processed or checked during rescan phase.")
                continue

            if is_media_file(abs_file_path):
                logging.debug(f"Processing media file: {abs_file_path} (relative: {rel_file_path})")

                # Check DB for this file_path and its last_modified time
                # This is relevant for both `rescan=True` (new files not in DB yet)
                # and `rescan=False` (checking if file needs update)
                db_entry_for_path = db_utils.get_media_file_by_path(db_path, rel_file_path)
                current_fs_last_modified = os.path.getmtime(abs_file_path)

                if db_entry_for_path and abs(current_fs_last_modified - db_entry_for_path.get('last_modified', 0.0)) < 1e-6:
                    # File exists in DB and its modification time is the same. Skip.
                    logging.debug(f"File {rel_file_path} found in DB and is unchanged. Skipping full processing.")
                    processed_rel_file_paths.add(rel_file_path) # Ensure it's marked
                    # Check thumbnail integrity even if mtime is same
                    if (mime_type := mimetypes.guess_type(abs_file_path)[0]) and \
                       mime_type.startswith('image/') and \
                       db_entry_for_path.get('thumbnail_file') and \
                       not os.path.exists(os.path.join(thumbnail_dir_abs, db_entry_for_path['thumbnail_file'])):
                        logging.info(f"Thumbnail missing for {rel_file_path} (SHA: {db_entry_for_path['sha256_hex']}). Regenerating.")
                        new_thumb_rel_path = generate_thumbnail(abs_file_path, thumbnail_dir_abs, db_entry_for_path['sha256_hex'])
                        if new_thumb_rel_path:
                            db_utils.update_media_file_fields(db_path, db_entry_for_path['sha256_hex'], {'thumbnail_file': new_thumb_rel_path})
                    continue

                # If we reach here, the file is either new, or modified, or not in DB by this path.
                # Or it's rescan=false and we are doing a full pass.
                sha256_hex = get_file_sha256(abs_file_path)
                if sha256_hex:
                    _process_single_file(abs_storage_dir, abs_file_path, sha256_hex, db_path, thumbnail_dir_abs, geolocator, disk_filename, db_entry_for_path)
                    processed_rel_file_paths.add(rel_file_path)
                else:
                    logging.warning(f"Could not get SHA256 for {abs_file_path}. Skipping.")
            else:
                logging.debug(f"Skipping non-media file: {abs_file_path}")

    # Phase 3: Cleanup (Only if `rescan` is True, to remove DB entries for files no longer on disk)
    # If `rescan` is False, this phase is skipped because we assume it's an additive/updating scan.
    # The previous rescan logic (Phase 1) already handles deletions for files it knew about.
    # This explicit phase ensures any file in DB not touched/seen by the walk is removed.
    if rescan:
        logging.info("Finalizing rescan: Checking for DB entries not found on filesystem...")
        all_db_paths = db_utils.get_all_db_file_paths(db_path)
        for db_rel_path in all_db_paths:
            if db_rel_path not in processed_rel_file_paths:
                # This file is in the DB but was not found on the filesystem during the walk
                # and was not handled by the initial DB check (e.g. if it was deleted before scan started)
                logging.info(f"File {db_rel_path} is in DB but not on filesystem. Removing from DB.")
                # Need to get SHA to delete associated thumbnail
                entry_to_delete = db_utils.get_media_file_by_path(db_path, db_rel_path)
                if entry_to_delete:
                    _delete_thumbnail_file(thumbnail_dir_abs, entry_to_delete.get('thumbnail_file'))
                    db_utils.delete_media_file_by_sha(db_path, entry_to_delete['sha256_hex']) # Delete by SHA to ensure data consistency
                else: # Should not happen if get_all_db_file_paths worked
                    db_utils.delete_media_file_by_path(db_path, db_rel_path)


    # Phase 4: Synchronize .thumbnails directory: remove any orphaned thumbnails
    _cleanup_orphaned_thumbnails(db_path, thumbnail_dir_abs)

    media_count = len(db_utils.get_all_media_files(db_path))
    if rescan:
        logging.info(f"Rescan complete. Database contains {media_count} media files.")
    else:
        logging.info(f"Initial/Full scan complete. Database contains {media_count} media files.")
    # This function no longer returns the data directly.
    # Callers should query the DB as needed.

def _process_single_file(abs_storage_dir: str, abs_file_path: str, sha256_hex: str, db_path: str, thumbnail_dir_abs: str, geolocator: GeoLocator, disk_filename: str, existing_db_entry_for_path: Optional[Dict] = None):
    """Helper to process a single media file and update the database."""
    rel_file_path = os.path.relpath(abs_file_path, abs_storage_dir)
    logging.debug(f"Processing details for: {rel_file_path} (SHA: {sha256_hex})")

    thumbnail_relative_path = None
    mime_type, _ = mimetypes.guess_type(abs_file_path)
    filesize = os.path.getsize(abs_file_path)

    if mime_type and mime_type.startswith('image/'):
        thumbnail_relative_path = generate_thumbnail(abs_file_path, thumbnail_dir_abs, sha256_hex)

    try:
        last_modified = os.path.getmtime(abs_file_path)
        filesystem_creation_time = os.path.getctime(abs_file_path)
        original_creation_date = filesystem_creation_time
        image_width, image_height = None, None
        latitude, longitude, city, country = None, None, None, None

        if mime_type and mime_type.startswith('image/'):
            try:
                with Image.open(abs_file_path) as img:
                    image_width, image_height = img.size
                    exif_data = img.getexif()
                    if exif_data:
                        date_time_original_tag = 36867 # DateTimeOriginal
                        if date_time_original_tag in exif_data:
                            exif_date_str = exif_data[date_time_original_tag]
                            try:
                                dt_object = datetime.strptime(exif_date_str, '%Y:%m:%d %H:%M:%S')
                                original_creation_date = dt_object.timestamp()
                            except (ValueError, TypeError):
                                logging.warning(f"Malformed DateTimeOriginal '{exif_date_str}' in {abs_file_path}.")
                        parsed_lat, parsed_lon = _get_gps_coordinates_from_exif(exif_data)
                        if parsed_lat is not None: latitude = parsed_lat
                        if parsed_lon is not None: longitude = parsed_lon

                        if latitude and longitude:
                            closest_city = geolocator.nearest_city(latitude, longitude)
                            if closest_city:
                                city = closest_city.name
                                country = closest_city.country
            except Exception as exif_e:
                logging.warning(f"Could not read metadata for {abs_file_path}: {exif_e}.")

        # Determine original_filename
        # If there's an existing DB entry for this SHA, use its original_filename.
        # Otherwise, if there's an existing entry for this path (but different SHA), it's a replacement, use current disk_filename.
        # Otherwise (new file), use current disk_filename.
        original_filename = disk_filename
        existing_entry_for_sha = db_utils.get_media_file_by_sha(db_path, sha256_hex)
        if existing_entry_for_sha:
            original_filename = existing_entry_for_sha.get('original_filename', disk_filename)
        elif existing_db_entry_for_path: # File path existed, but SHA is new (file was replaced)
             original_filename = disk_filename # Treat as new original

        media_data = {
            'sha256_hex': sha256_hex,
            'filename': disk_filename,
            'original_filename': original_filename,
            'file_path': rel_file_path,
            'last_modified': last_modified,
            'original_creation_date': original_creation_date,
            'thumbnail_file': thumbnail_relative_path,
            'width': image_width,
            'height': image_height,
            'latitude': latitude,
            'longitude': longitude,
            'city': city,
            'country': country,
            'mime_type': mime_type,
            'filesize': filesize,
        }
        db_utils.add_or_update_media_file(db_path, media_data)
        logging.debug(f"DB ADDED/UPDATED for SHA: {sha256_hex}, file: {disk_filename}, path: {rel_file_path}")

    except OSError as e:
        logging.error(f"Could not get OS metadata for {abs_file_path}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error processing file {abs_file_path}: {e}", exc_info=True)


def _cleanup_orphaned_thumbnails(db_path: str, thumbnail_dir_abs: str):
    """Removes thumbnail files that are not referenced in the database."""
    if not os.path.exists(thumbnail_dir_abs):
        logging.debug("Thumbnail directory does not exist, no cleanup needed.")
        return

    logging.info(f"Cleaning orphaned thumbnails in {thumbnail_dir_abs}...")
    db_thumbnails = db_utils.get_all_shas_and_thumbnails(db_path) # {sha: thumbnail_rel_path}
    # Set of expected thumbnail relative paths (e.g., {"ab/hash1.png", "cd/hash2.png"})
    expected_thumb_rel_paths = {thumb_path for thumb_path in db_thumbnails.values() if thumb_path}

    cleaned_count = 0
    # Walk through the thumbnail directory structure (e.g., .thumbnails/ab/hash.png)
    for root, dirs, files in os.walk(thumbnail_dir_abs, topdown=False): # topdown=False for rmdir
        for file_name in files:
            if file_name.endswith(THUMBNAIL_EXTENSION):
                # Construct the relative path of the thumbnail on disk
                # root is like /path/to/.thumbnails/ab, file_name is hash.png
                # We need 'ab/hash.png' to compare with expected_thumb_rel_paths
                thumb_on_disk_rel_path = os.path.relpath(os.path.join(root, file_name), thumbnail_dir_abs)

                if thumb_on_disk_rel_path not in expected_thumb_rel_paths:
                    orphaned_thumb_path_abs = os.path.join(root, file_name)
                    try:
                        os.remove(orphaned_thumb_path_abs)
                        logging.info(f"Removed orphaned thumbnail: {orphaned_thumb_path_abs}")
                        cleaned_count +=1
                    except OSError as e:
                        logging.error(f"Error removing orphaned thumbnail {orphaned_thumb_path_abs}: {e}")

        # After removing files in a directory, if the directory is empty, remove it
        # This applies only to subdirectories (e.g. .thumbnails/ab), not the main .thumbnails dir
        if root != thumbnail_dir_abs and not os.listdir(root):
            try:
                os.rmdir(root)
                logging.info(f"Removed empty thumbnail subdirectory: {root}")
            except OSError as e:
                logging.error(f"Error removing empty thumbnail subdirectory {root}: {e}")
    logging.info(f"Orphaned thumbnail cleanup complete. Removed {cleaned_count} files.")
