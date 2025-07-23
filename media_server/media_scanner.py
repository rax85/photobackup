import os
import hashlib
import mimetypes
from absl import logging
from typing import Dict, Optional, Tuple, Set
from PIL import Image, ImageOps, ExifTags
from datetime import datetime
from pillow_heif import register_heif_opener
import concurrent.futures

try:
    from . import database as db_utils  # Relative import for package
    from .geolocator import GeoLocator
    from .image_classifier import ImageClassifier
    from .settings import SettingsManager
except ImportError:
    from media_server import (
        database as db_utils,
    )  # Fallback for direct execution/testing
    from media_server.geolocator import GeoLocator
    from media_server.image_classifier import ImageClassifier
    from media_server.settings import SettingsManager

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

    if ref in ["S", "W"]:
        decimal_degrees = -decimal_degrees
    elif ref not in ["N", "E"]:
        logging.warning(f"Invalid GPS reference: {ref}")
        return None
    return decimal_degrees


def _get_gps_coordinates_from_exif(
    exif_data: dict,
) -> Tuple[Optional[float], Optional[float]]:
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
    """
    Computes the SHA256 hash of a file.

    Args:
        file_path: The absolute path to the file.

    Returns:
        The SHA256 hash as a hexadecimal string, or None if the file
        could not be read.
    """
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
    """
    Determines if a file is a media file based on its MIME type.

    Args:
        file_path: The path to the file.

    Returns:
        True if the file is an image or video, False otherwise.
    """
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type.startswith("image/") or mime_type.startswith("video/")
    return False


def generate_thumbnail(
    source_image_path: str,
    thumbnail_dir: str,  # Absolute path to .thumbnails directory
    sha256_hex: str,
    target_size: Tuple[int, int] = THUMBNAIL_SIZE,
) -> Optional[str]:
    """
    Generates a thumbnail for a given image file.

    The thumbnail is saved in a subdirectory of `thumbnail_dir` named with
    the first two characters of the SHA256 hash.

    Args:
        source_image_path: The absolute path to the source image.
        thumbnail_dir: The absolute path to the base directory for thumbnails.
        sha256_hex: The SHA256 hash of the source image.
        target_size: A tuple specifying the target width and height of the thumbnail.

    Returns:
        The relative path to the generated thumbnail, or None if generation fails.
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
    thumbnail_path_absolute = os.path.join(
        thumbnail_subdir_abs, thumbnail_filename_only
    )
    # Path to be returned and stored in DB should be relative to thumbnail_dir: e.g. 'ab/hash.png'
    thumbnail_path_relative_to_basedir = os.path.join(
        sha256_prefix, thumbnail_filename_only
    )

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
            logging.info(
                f"Generated thumbnail: {thumbnail_path_absolute} for {source_image_path}"
            )
            return thumbnail_path_relative_to_basedir
    except FileNotFoundError:
        logging.error(
            f"Source image not found for thumbnail generation: {source_image_path}"
        )
    except Exception as e:
        logging.error(f"Failed to generate thumbnail for {source_image_path}: {e}")
    return None


def _delete_thumbnail_file(
    thumbnail_dir_abs: str, thumbnail_relative_path: Optional[str]
):
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
        if not os.path.dirname(thumbnail_relative_path):  # It's a flat filename
            # This means thumb_to_delete_abs was already correct for a flat structure.
            # No need for further action if it didn't exist.
            logging.debug(
                f"Thumbnail {thumb_to_delete_abs} (potentially flat) not found for deletion."
            )


def scan_directory(storage_dir: str, db_path: str, rescan: bool = False) -> None:
    if not os.path.isdir(storage_dir):
        logging.error(f"Storage directory not found: {storage_dir}")
        return

    thumbnail_dir_abs = os.path.join(storage_dir, THUMBNAIL_DIR_NAME)
    os.makedirs(thumbnail_dir_abs, exist_ok=True)
    logging.info(f"Thumbnail directory ensured at: {thumbnail_dir_abs}")

    settings_manager = SettingsManager(os.path.join(storage_dir, ".settings.json"))
    settings = settings_manager.get()

    image_classifier = ImageClassifier(settings)
    geolocator = GeoLocator()
    cities_csv_path = os.path.join(os.path.dirname(__file__), "resources", "cities.csv")
    geolocator.load_cities(cities_csv_path)

    abs_storage_dir = os.path.abspath(storage_dir)
    processed_rel_file_paths: Set[str] = set()
    media_to_process = []

    # Rescan logic to find modified/deleted files
    if rescan:
        logging.info(f"Rescanning directory: {storage_dir} using DB: {db_path}")
        db_file_entries = db_utils.get_all_media_files(db_path)
        for sha256_hex, db_entry in db_file_entries.items():
            rel_file_path = db_entry.get("file_path")
            if not rel_file_path:
                continue
            abs_file_path_to_check = os.path.normpath(
                os.path.join(abs_storage_dir, rel_file_path)
            )
            processed_rel_file_paths.add(rel_file_path)

            if not os.path.isfile(abs_file_path_to_check):
                logging.info(
                    f"File for SHA {sha256_hex} (path: {rel_file_path}) no longer exists. Removing from DB."
                )
                _delete_thumbnail_file(
                    thumbnail_dir_abs, db_entry.get("thumbnail_file")
                )
                db_utils.delete_media_file_by_sha(db_path, sha256_hex)
                continue

            current_fs_last_modified = os.path.getmtime(abs_file_path_to_check)
            db_last_modified = db_entry.get("last_modified")
            if abs(current_fs_last_modified - db_last_modified) > 1e-6 or (
                db_entry.get("tagging_model") != settings.tagging_model
                and settings.tagging_model != "Off"
            ):
                media_to_process.append(
                    (
                        abs_file_path_to_check,
                        os.path.basename(rel_file_path),
                        db_entry,
                    )
                )

    # Filesystem walk for new files
    logging.info("Scanning filesystem for new or changed files...")
    for root, dirs, files in os.walk(abs_storage_dir):
        if THUMBNAIL_DIR_NAME in dirs:
            dirs.remove(THUMBNAIL_DIR_NAME)
        for disk_filename in files:
            abs_file_path = os.path.normpath(os.path.join(root, disk_filename))
            rel_file_path = os.path.relpath(abs_file_path, abs_storage_dir)
            if rel_file_path in processed_rel_file_paths and rescan:
                continue
            if is_media_file(abs_file_path):
                db_entry_for_path = db_utils.get_media_file_by_path(
                    db_path, rel_file_path
                )
                media_to_process.append((abs_file_path, disk_filename, db_entry_for_path))
                processed_rel_file_paths.add(rel_file_path)

    # Process all identified files
    all_media_data = []
    for abs_path, filename, db_entry in media_to_process:
        sha = get_file_sha256(abs_path)
        if sha:
            data = _process_single_file(
                abs_storage_dir,
                abs_path,
                sha,
                db_path,
                thumbnail_dir_abs,
                geolocator,
                image_classifier,
                settings,
                filename,
                db_entry,
            )
            if data:
                all_media_data.append(data)

    # Thumbnail generation in parallel
    thumbnail_futures = {}
    with concurrent.futures.ProcessPoolExecutor() as executor:
        for media_data in all_media_data:
            if media_data.get("_thumbnail_needed"):
                future = executor.submit(
                    generate_thumbnail,
                    media_data["_abs_file_path"],
                    thumbnail_dir_abs,
                    media_data["sha256_hex"],
                )
                thumbnail_futures[future] = media_data

    for future in concurrent.futures.as_completed(thumbnail_futures):
        media_data = thumbnail_futures[future]
        try:
            thumbnail_path = future.result()
            if thumbnail_path:
                media_data["thumbnail_file"] = thumbnail_path
        except Exception as exc:
            logging.error(
                f"Thumbnail generation failed for {media_data['_abs_file_path']}: {exc}"
            )

    # Update database with all collected data
    for media_data in all_media_data:
        # Clean up temporary keys before DB insertion
        media_data.pop("_thumbnail_needed", None)
        media_data.pop("_abs_file_path", None)
        db_utils.add_or_update_media_file(db_path, media_data)

    # Cleanup phases
    if rescan:
        all_db_paths = db_utils.get_all_db_file_paths(db_path)
        for db_rel_path in all_db_paths:
            if db_rel_path not in processed_rel_file_paths:
                entry_to_delete = db_utils.get_media_file_by_path(db_path, db_rel_path)
                if entry_to_delete:
                    _delete_thumbnail_file(
                        thumbnail_dir_abs, entry_to_delete.get("thumbnail_file")
                    )
                    db_utils.delete_media_file_by_sha(
                        db_path, entry_to_delete["sha256_hex"]
                    )
    _cleanup_orphaned_thumbnails(db_path, thumbnail_dir_abs)

    media_count = len(db_utils.get_all_media_files(db_path))
    logging.info(f"Scan complete. Database contains {media_count} media files.")


import json


def _process_single_file(
    abs_storage_dir: str,
    abs_file_path: str,
    sha256_hex: str,
    db_path: str,
    thumbnail_dir_abs: str,
    geolocator: GeoLocator,
    image_classifier: ImageClassifier,
    settings: SettingsManager,
    disk_filename: str,
    existing_db_entry_for_path: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Helper to process a single media file, returning its metadata dictionary.
    This version does NOT generate the thumbnail itself but returns info to do so.
    """
    rel_file_path = os.path.relpath(abs_file_path, abs_storage_dir)
    logging.debug(f"Processing details for: {rel_file_path} (SHA: {sha256_hex})")

    mime_type, _ = mimetypes.guess_type(abs_file_path)
    filesize = os.path.getsize(abs_file_path)
    tags = None
    thumbnail_needed = False

    existing_entry_for_sha = db_utils.get_media_file_by_sha(db_path, sha256_hex)

    if mime_type and mime_type.startswith("image/"):
        thumbnail_needed = True  # Mark that a thumbnail is needed
        tagging_model_in_db = (
            existing_entry_for_sha.get("tagging_model")
            if existing_entry_for_sha
            else None
        )

        if (
            settings.tagging_model != "Off"
            and settings.tagging_model != tagging_model_in_db
        ):
            tags = image_classifier.classify_image(abs_file_path)
        elif existing_entry_for_sha:
            tags = (
                json.loads(existing_entry_for_sha.get("tags"))
                if existing_entry_for_sha.get("tags")
                else None
            )

    try:
        last_modified = os.path.getmtime(abs_file_path)
        filesystem_creation_time = os.path.getctime(abs_file_path)
        original_creation_date = filesystem_creation_time
        image_width, image_height = None, None
        latitude, longitude, city, country = None, None, None, None

        if mime_type and mime_type.startswith("image/"):
            try:
                with Image.open(abs_file_path) as img:
                    image_width, image_height = img.size
                    exif_data = img.getexif()
                    if exif_data:
                        date_time_original_tag, date_time_tag = 36867, 306
                        exif_date_str = exif_data.get(
                            date_time_original_tag
                        ) or exif_data.get(date_time_tag)
                        if exif_date_str:
                            try:
                                dt_object = datetime.strptime(
                                    exif_date_str, "%Y:%m:%d %H:%M:%S"
                                )
                                original_creation_date = dt_object.timestamp()
                            except (ValueError, TypeError):
                                logging.warning(
                                    f"Malformed EXIF date string '{exif_date_str}' in {abs_file_path}."
                                )
                        parsed_lat, parsed_lon = _get_gps_coordinates_from_exif(
                            exif_data
                        )
                        if parsed_lat is not None:
                            latitude = parsed_lat
                        if parsed_lon is not None:
                            longitude = parsed_lon
                        if latitude and longitude:
                            closest_city = geolocator.nearest_city(latitude, longitude)
                            if closest_city:
                                city, country = closest_city.name, closest_city.country
            except Exception as exif_e:
                logging.warning(
                    f"Could not read metadata for {abs_file_path}: {exif_e}."
                )

        original_filename = disk_filename
        if existing_entry_for_sha:
            original_filename = existing_entry_for_sha.get(
                "original_filename", disk_filename
            )
        elif existing_db_entry_for_path:
            original_filename = disk_filename

        media_data = {
            "sha256_hex": sha256_hex,
            "filename": disk_filename,
            "original_filename": original_filename,
            "file_path": rel_file_path,
            "last_modified": last_modified,
            "original_creation_date": original_creation_date,
            "thumbnail_file": None,  # Will be filled in later
            "width": image_width,
            "height": image_height,
            "latitude": latitude,
            "longitude": longitude,
            "city": city,
            "country": country,
            "mime_type": mime_type,
            "filesize": filesize,
            "tags": json.dumps(tags) if tags else None,
            "tagging_model": settings.tagging_model if tags else None,
            # Add a temporary flag for the main scanner function
            "_thumbnail_needed": thumbnail_needed,
            "_abs_file_path": abs_file_path,
        }
        return media_data

    except OSError as e:
        logging.error(f"Could not get OS metadata for {abs_file_path}: {e}")
    except Exception as e:
        logging.error(
            f"Unexpected error processing file {abs_file_path}: {e}", exc_info=True
        )
    return None


def _cleanup_orphaned_thumbnails(db_path: str, thumbnail_dir_abs: str):
    """Removes thumbnail files that are not referenced in the database."""
    if not os.path.exists(thumbnail_dir_abs):
        logging.debug("Thumbnail directory does not exist, no cleanup needed.")
        return

    logging.info(f"Cleaning orphaned thumbnails in {thumbnail_dir_abs}...")
    db_thumbnails = db_utils.get_all_shas_and_thumbnails(
        db_path
    )  # {sha: thumbnail_rel_path}
    # Set of expected thumbnail relative paths (e.g., {"ab/hash1.png", "cd/hash2.png"})
    expected_thumb_rel_paths = {
        thumb_path for thumb_path in db_thumbnails.values() if thumb_path
    }

    cleaned_count = 0
    # Walk through the thumbnail directory structure (e.g., .thumbnails/ab/hash.png)
    for root, dirs, files in os.walk(
        thumbnail_dir_abs, topdown=False
    ):  # topdown=False for rmdir
        for file_name in files:
            if file_name.endswith(THUMBNAIL_EXTENSION):
                # Construct the relative path of the thumbnail on disk
                # root is like /path/to/.thumbnails/ab, file_name is hash.png
                # We need 'ab/hash.png' to compare with expected_thumb_rel_paths
                thumb_on_disk_rel_path = os.path.relpath(
                    os.path.join(root, file_name), thumbnail_dir_abs
                )

                if thumb_on_disk_rel_path not in expected_thumb_rel_paths:
                    orphaned_thumb_path_abs = os.path.join(root, file_name)
                    try:
                        os.remove(orphaned_thumb_path_abs)
                        logging.info(
                            f"Removed orphaned thumbnail: {orphaned_thumb_path_abs}"
                        )
                        cleaned_count += 1
                    except OSError as e:
                        logging.error(
                            f"Error removing orphaned thumbnail {orphaned_thumb_path_abs}: {e}"
                        )

        # After removing files in a directory, if the directory is empty, remove it
        # This applies only to subdirectories (e.g. .thumbnails/ab), not the main .thumbnails dir
        if root != thumbnail_dir_abs and not os.listdir(root):
            try:
                os.rmdir(root)
                logging.info(f"Removed empty thumbnail subdirectory: {root}")
            except OSError as e:
                logging.error(
                    f"Error removing empty thumbnail subdirectory {root}: {e}"
                )
    logging.info(f"Orphaned thumbnail cleanup complete. Removed {cleaned_count} files.")
