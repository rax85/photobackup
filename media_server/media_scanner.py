import concurrent.futures
from datetime import datetime
import hashlib
import io
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Optional, Set, Tuple
from absl import logging
from PIL import ExifTags, Image, ImageDraw, ImageOps
from pillow_heif import register_heif_opener

try:
    from . import database as db_utils
    from .geolocator import GeoLocator
    from .image_classifier import ImageClassifier
    from .settings import SettingsManager
except ImportError:
    from media_server import database as db_utils
    from media_server.geolocator import GeoLocator
    from media_server.image_classifier import ImageClassifier
    from media_server.settings import SettingsManager

# Initialize mimetypes database and HEIF support
mimetypes.init()
register_heif_opener()

# GPS EXIF Tag IDs
GPS_TAG_ID = None
for k, v in ExifTags.TAGS.items():
    if v == "GPSInfo":
        GPS_TAG_ID = k
        break

GPS_LATITUDE_REF_TAG = 1
GPS_LATITUDE_TAG = 2
GPS_LONGITUDE_REF_TAG = 3
GPS_LONGITUDE_TAG = 4

THUMBNAIL_DIR_NAME = ".thumbnails"
THUMBNAIL_SIZE = (256, 256)
THUMBNAIL_EXTENSION = ".png"


def _convert_dms_to_decimal(
    dms_tuple: Tuple[Any, ...], ref: str
) -> Optional[float]:
    """Converts GPS DMS (Degrees, Minutes, Seconds) to decimal degrees."""
    if not dms_tuple or len(dms_tuple) != 3:
        return None

    try:
        def to_float(val):
            if isinstance(val, tuple) and len(val) == 2:
                return float(val[0]) / float(val[1]) if val[1] != 0 else 0.0
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
    exif_data: Any,
) -> Tuple[Optional[float], Optional[float]]:
    """Extracts GPS latitude and longitude from EXIF data."""
    latitude = None
    longitude = None

    if not exif_data or not GPS_TAG_ID:
        return None, None

    gps_info = None
    try:
        if hasattr(exif_data, "get_ifd"):
            gps_info = exif_data.get_ifd(GPS_TAG_ID)
        elif isinstance(exif_data, dict) and GPS_TAG_ID in exif_data:
            gps_info = exif_data[GPS_TAG_ID]
    except (KeyError, AttributeError, Exception):
        return None, None

    if not gps_info:
        return None, None

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
        logging.warning(f"Error parsing GPS EXIF data: {e}")
        return None, None

    return latitude, longitude


def get_file_sha256(file_path: str) -> Optional[str]:
    """Computes SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except (IOError, OSError):
        logging.error(f"Could not read file for hashing: {file_path}")
        return None


def is_media_file(file_path: str) -> bool:
    """Checks if a file is an image or video based on MIME type or extension."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type and (
        mime_type.startswith("image/") or mime_type.startswith("video/")
    ):
        return True
    ext = os.path.splitext(file_path)[1].lower()
    return ext in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".heic",
        ".heif",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
    }


def _is_plausible_video_binary(file_path: str) -> bool:
    """Fast check if file has plausible video binary headers."""
    try:
        if not os.path.isfile(file_path) or os.path.getsize(file_path) < 32:
            return False
        with open(file_path, "rb") as f:
            header = f.read(32)
        if len(header) < 16:
            return False
        # MP4/MOV: box type in header[4:8]
        if header[4:8] in {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"}:
            return True
        # AVI: RIFF ... AVI
        if header.startswith(b"RIFF") and b"AVI" in header[:16]:
            return True
        # Matroska / WebM
        if header.startswith(b"\x1a\x45\xdf\xa3"):
            return True
        # MPEG
        if header.startswith(b"\x00\x00\x01\xba") or header.startswith(b"\x00\x00\x01\xb3"):
            return True
        return False
    except Exception:
        return False


def _extract_video_frame(video_path: str) -> Optional[Image.Image]:
    """
    Extracts a representative video frame using ffmpeg or macOS QuickLook.
    """
    if not _is_plausible_video_binary(video_path):
        return None

    # 1. Try ffmpeg CLI if installed
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            cmd = [
                ffmpeg_path,
                "-ss",
                "00:00:01",
                "-i",
                video_path,
                "-vframes",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-loglevel",
                "quiet",
                "pipe:1",
            ]
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4
            )
            if proc.returncode == 0 and proc.stdout:
                return Image.open(io.BytesIO(proc.stdout)).convert("RGBA")
        except Exception:
            pass

    # 2. Try macOS qlmanage
    qlmanage_path = shutil.which("qlmanage")
    if qlmanage_path:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cmd = [qlmanage_path, "-t", "-s", "512", "-o", tmpdir, video_path]
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=4,
                )
                if proc.returncode == 0:
                    for root, _, files in os.walk(tmpdir):
                        for f in files:
                            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                                cand_path = os.path.join(root, f)
                                with Image.open(cand_path) as img:
                                    return img.copy().convert("RGBA")
        except Exception:
            pass

    return None


def _save_image_atomic(img: Image.Image, output_path: str, format: str = "PNG") -> None:
    """Atomically writes a PIL Image to disk using a temporary file and os.replace."""
    dir_name = os.path.dirname(output_path)
    os.makedirs(dir_name, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dir_name, delete=False, suffix=".tmp") as tmp:
        tmp_path = tmp.name
    try:
        img.save(tmp_path, format)
        os.replace(tmp_path, output_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _create_video_poster_thumbnail(
    output_path: str, filename: str, target_size: Tuple[int, int]
) -> None:
    """Generates a high-quality video placeholder thumbnail."""
    width, height = target_size
    img = Image.new("RGBA", target_size, (17, 24, 39, 255))
    draw = ImageDraw.Draw(img)

    center_x, center_y = width // 2, height // 2 - 10
    radius = 32
    draw.ellipse(
        [
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        ],
        fill=(59, 130, 246, 220),
        outline=(255, 255, 255, 180),
        width=2,
    )

    tri_points = [
        (center_x - 8, center_y - 14),
        (center_x - 8, center_y + 14),
        (center_x + 14, center_y),
    ]
    draw.polygon(tri_points, fill=(255, 255, 255, 255))

    ext = os.path.splitext(filename)[1].upper().replace(".", "") or "VIDEO"
    badge_w, badge_h = 60, 20
    badge_x = (width - badge_w) // 2
    badge_y = height - 40
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=4,
        fill=(30, 41, 59, 230),
    )
    draw.text((badge_x + 10, badge_y + 4), ext, fill=(255, 255, 255, 255))
    _save_image_atomic(img, output_path, "PNG")


def generate_thumbnail(
    source_media_path: str,
    thumbnail_dir: str,
    sha256_hex: str,
    target_size: Tuple[int, int] = THUMBNAIL_SIZE,
) -> Optional[str]:
    """
    Generates a proportional 256x256 PNG thumbnail for an image or video.

    Args:
        source_media_path: Absolute path to media file.
        thumbnail_dir: Absolute path to .thumbnails directory.
        sha256_hex: SHA256 content hash.
        target_size: Target (width, height) tuple.

    Returns:
        Relative path (e.g. 'ab/hash.png') or None on failure.
    """
    if not sha256_hex or len(sha256_hex) < 2:
        return None

    prefix = sha256_hex[:2]
    subdir_abs = os.path.join(thumbnail_dir, prefix)
    os.makedirs(subdir_abs, exist_ok=True)

    thumb_filename = sha256_hex + THUMBNAIL_EXTENSION
    thumb_path_abs = os.path.join(subdir_abs, thumb_filename)
    thumb_rel_path = os.path.join(prefix, thumb_filename)

    if os.path.exists(thumb_path_abs):
        return thumb_rel_path

    mime_type, _ = mimetypes.guess_type(source_media_path)
    is_video = bool(mime_type and mime_type.startswith("video/"))
    if not is_video:
        ext = os.path.splitext(source_media_path)[1].lower()
        if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            is_video = True

    if is_video:
        extracted = _extract_video_frame(source_media_path)
        if extracted:
            try:
                extracted.thumbnail(target_size, Image.Resampling.LANCZOS)
                final_thumb = Image.new("RGBA", target_size, (0, 0, 0, 255))
                paste_x = (target_size[0] - extracted.width) // 2
                paste_y = (target_size[1] - extracted.height) // 2
                final_thumb.paste(extracted, (paste_x, paste_y))
                _save_image_atomic(final_thumb, thumb_path_abs, "PNG")
                return thumb_rel_path
            except Exception as e:
                logging.warning(f"Error saving extracted video thumbnail: {e}")

        # Fallback to poster thumbnail
        try:
            _create_video_poster_thumbnail(
                thumb_path_abs, os.path.basename(source_media_path), target_size
            )
            return thumb_rel_path
        except Exception as e:
            logging.error(f"Failed to generate video poster thumbnail: {e}")
            return None

    # Handle image thumbnailing
    try:
        with Image.open(source_media_path) as img:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            img.thumbnail(target_size, Image.Resampling.LANCZOS)
            final_thumb = Image.new("RGBA", target_size, (0, 0, 0, 0))
            paste_x = (target_size[0] - img.width) // 2
            paste_y = (target_size[1] - img.height) // 2
            final_thumb.paste(img, (paste_x, paste_y))
            _save_image_atomic(final_thumb, thumb_path_abs, "PNG")
            return thumb_rel_path
    except FileNotFoundError:
        logging.error(f"Source file not found for thumbnail: {source_media_path}")
    except Exception as e:
        logging.error(f"Failed to generate thumbnail for {source_media_path}: {e}")
    return None


def _delete_thumbnail_file(
    thumbnail_dir_abs: str, thumbnail_relative_path: Optional[str]
) -> None:
    """Deletes a thumbnail file given its relative path."""
    if not thumbnail_relative_path:
        return
    thumb_abs = os.path.join(thumbnail_dir_abs, thumbnail_relative_path)
    if os.path.exists(thumb_abs):
        try:
            os.remove(thumb_abs)
        except OSError as e:
            logging.error(f"Error deleting thumbnail {thumb_abs}: {e}")


def _process_single_file(
    abs_storage_dir: str,
    abs_file_path: str,
    sha256_hex: str,
    db_path: str,
    thumbnail_dir_abs: str,
    geolocator: GeoLocator,
    image_classifier: ImageClassifier,
    disk_filename: str,
    existing_db_entry_for_path: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Processes a single file and extracts its complete metadata."""
    rel_file_path = os.path.relpath(abs_file_path, abs_storage_dir)
    mime_type, _ = mimetypes.guess_type(abs_file_path)
    if not mime_type:
        ext = os.path.splitext(abs_file_path)[1].lower()
        if ext in {".jpg", ".jpeg"}:
            mime_type = "image/jpeg"
        elif ext == ".png":
            mime_type = "image/png"
        elif ext in {".heic", ".heif"}:
            mime_type = "image/heic"
        elif ext == ".mp4":
            mime_type = "video/mp4"

    filesize = os.path.getsize(abs_file_path)
    existing_entry_for_sha = db_utils.get_media_file_by_sha(db_path, sha256_hex)

    tags = None
    if mime_type and mime_type.startswith("image/"):
        tagging_model_in_db = (
            existing_entry_for_sha.get("tagging_model")
            if existing_entry_for_sha
            else None
        )
        if (
            image_classifier.settings.tagging_model != "Off"
            and image_classifier.settings.tagging_model != tagging_model_in_db
        ):
            tags = image_classifier.classify_image(abs_file_path)
        elif existing_entry_for_sha and existing_entry_for_sha.get("tags"):
            try:
                tags = json.loads(existing_entry_for_sha["tags"])
            except Exception:
                tags = None

    try:
        st = os.stat(abs_file_path)
        last_modified = st.st_mtime
        if hasattr(st, "st_birthtime"):
            filesystem_creation_time = st.st_birthtime
        else:
            filesystem_creation_time = st.st_mtime
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
                                    str(exif_date_str), "%Y:%m:%d %H:%M:%S"
                                )
                                original_creation_date = dt_object.timestamp()
                            except (ValueError, TypeError):
                                pass
                        parsed_lat, parsed_lon = _get_gps_coordinates_from_exif(
                            exif_data
                        )
                        if parsed_lat is not None:
                            latitude = parsed_lat
                        if parsed_lon is not None:
                            longitude = parsed_lon
                        if latitude is not None and longitude is not None:
                            closest_city = geolocator.nearest_city(
                                latitude, longitude
                            )
                            if closest_city:
                                city, country = closest_city.name, closest_city.country
            except Exception as e:
                logging.warning(f"Could not read metadata for {abs_file_path}: {e}")

        original_filename = disk_filename
        if existing_entry_for_sha:
            original_filename = existing_entry_for_sha.get(
                "original_filename", disk_filename
            )

        thumbnail_file = None
        if existing_entry_for_sha:
            thumbnail_file = existing_entry_for_sha.get("thumbnail_file")

        # Mark thumbnail needed for all media files (images and videos)
        thumbnail_needed = is_media_file(abs_file_path)

        media_data = {
            "sha256_hex": sha256_hex,
            "filename": disk_filename,
            "original_filename": original_filename,
            "file_path": rel_file_path,
            "last_modified": last_modified,
            "original_creation_date": original_creation_date,
            "thumbnail_file": thumbnail_file,
            "width": image_width,
            "height": image_height,
            "latitude": latitude,
            "longitude": longitude,
            "city": city,
            "country": country,
            "mime_type": mime_type,
            "filesize": filesize,
            "tags": json.dumps(tags) if tags else None,
            "tagging_model": (
                image_classifier.settings.tagging_model if tags else None
            ),
            "_thumbnail_needed": thumbnail_needed,
            "_abs_file_path": abs_file_path,
        }
        return media_data
    except Exception as e:
        logging.error(f"Error processing file {abs_file_path}: {e}")
        return None


def _cleanup_orphaned_thumbnails(db_path: str, thumbnail_dir_abs: str) -> None:
    """Cleans up thumbnails on disk that are not registered in the database."""
    if not os.path.exists(thumbnail_dir_abs):
        return

    db_thumbnails = db_utils.get_all_shas_and_thumbnails(db_path)
    expected_rel_paths = {
        thumb for thumb in db_thumbnails.values() if thumb
    }

    for root, dirs, files in os.walk(thumbnail_dir_abs, topdown=False):
        for file_name in files:
            if file_name.endswith(THUMBNAIL_EXTENSION):
                rel_path = os.path.relpath(
                    os.path.join(root, file_name), thumbnail_dir_abs
                )
                if rel_path not in expected_rel_paths:
                    try:
                        os.remove(os.path.join(root, file_name))
                    except OSError:
                        pass
        if root != thumbnail_dir_abs and not os.listdir(root):
            try:
                os.rmdir(root)
            except OSError:
                pass


def scan_directory(
    storage_dir: str,
    db_path: str,
    image_classifier: ImageClassifier,
    rescan: bool = False,
    progress_callback: Optional[Any] = None,
) -> None:
    """
    Scans a storage directory, indexes media files, generates thumbnails,
    and cleans up deleted files.
    """
    if not os.path.isdir(storage_dir):
        logging.error(f"Storage directory not found: {storage_dir}")
        return

    if progress_callback:
        try:
            progress_callback({
                "phase": "discovering",
                "message": "Discovering media files in storage directory...",
                "current": 0,
                "total": 0,
                "percent": 0.0,
            })
        except Exception:
            pass

    thumbnail_dir_abs = os.path.join(storage_dir, THUMBNAIL_DIR_NAME)
    os.makedirs(thumbnail_dir_abs, exist_ok=True)

    settings_manager = SettingsManager(os.path.join(storage_dir, "settings.json"))
    settings = settings_manager.get()

    geolocator = GeoLocator()
    cities_csv_path = os.path.join(os.path.dirname(__file__), "resources", "cities.csv")
    geolocator.load_cities(cities_csv_path)

    abs_storage_dir = os.path.abspath(storage_dir)
    processed_rel_paths: Set[str] = set()
    media_to_process = []

    existing_db_entries = db_utils.get_all_media_files(db_path)
    existing_by_path: Dict[str, Dict[str, Any]] = {
        entry["file_path"]: entry
        for entry in existing_db_entries.values()
        if entry.get("file_path")
    }

    if rescan:
        for sha256_hex, db_entry in existing_db_entries.items():
            rel_path = db_entry.get("file_path")
            if not rel_path:
                continue
            abs_check_path = os.path.normpath(
                os.path.join(abs_storage_dir, rel_path)
            )
            processed_rel_paths.add(rel_path)

            if not os.path.isfile(abs_check_path):
                _delete_thumbnail_file(
                    thumbnail_dir_abs, db_entry.get("thumbnail_file")
                )
                db_utils.delete_media_file_by_sha(db_path, sha256_hex)
                continue

            current_mtime = os.path.getmtime(abs_check_path)
            db_mtime = db_entry.get("last_modified") or 0.0
            if abs(current_mtime - db_mtime) > 1e-5 or (
                db_entry.get("tagging_model") != settings.tagging_model
                and settings.tagging_model != "Off"
            ):
                media_to_process.append(
                    (abs_check_path, os.path.basename(rel_path), db_entry)
                )

    for root, dirs, files in os.walk(abs_storage_dir):
        if THUMBNAIL_DIR_NAME in dirs:
            dirs.remove(THUMBNAIL_DIR_NAME)
        for disk_filename in files:
            abs_path = os.path.normpath(os.path.join(root, disk_filename))
            rel_path = os.path.relpath(abs_path, abs_storage_dir)
            if rel_path in processed_rel_paths and rescan:
                continue
            if is_media_file(abs_path):
                db_entry = existing_by_path.get(rel_path)
                media_to_process.append((abs_path, disk_filename, db_entry))
                processed_rel_paths.add(rel_path)

    total = len(media_to_process)
    if progress_callback:
        try:
            msg = (
                f"Found {total} media item{'s' if total != 1 else ''} to index."
                if total > 0
                else "No new media items to process."
            )
            progress_callback({
                "phase": "processing" if total > 0 else "finalizing",
                "message": msg,
                "current": 0,
                "total": total,
                "percent": 0.0 if total > 0 else 100.0,
            })
        except Exception:
            pass

    def _process_item_task(item):
        try:
            abs_path, disk_filename, db_entry = item
            sha = get_file_sha256(abs_path)
            if not sha:
                return None
            data = _process_single_file(
                abs_storage_dir,
                abs_path,
                sha,
                db_path,
                thumbnail_dir_abs,
                geolocator,
                image_classifier,
                disk_filename,
                db_entry,
            )
            if not data:
                return None
            if data.get("_thumbnail_needed"):
                try:
                    thumb_path = generate_thumbnail(
                        abs_path, thumbnail_dir_abs, sha
                    )
                    if thumb_path:
                        data["thumbnail_file"] = thumb_path
                except Exception as e:
                    logging.error(f"Thumbnail error for {abs_path}: {e}")
            data.pop("_thumbnail_needed", None)
            data.pop("_abs_file_path", None)
            return data
        finally:
            db_utils.close_db_connection()

    max_workers = min(32, max(4, (os.cpu_count() or 4) * 2))
    BATCH_SIZE = 500
    batch_buffer = []
    processed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_process_item_task, item) for item in media_to_process]
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                if res:
                    batch_buffer.append(res)
                    if len(batch_buffer) >= BATCH_SIZE:
                        db_utils.batch_add_or_update_media_files(db_path, batch_buffer)
                        batch_buffer.clear()
            except Exception as exc:
                logging.error(f"Task processing error: {exc}")

            processed_count += 1
            if progress_callback and total > 0:
                try:
                    pct = round((processed_count / total) * 100, 1)
                    progress_callback({
                        "phase": "processing",
                        "message": f"Processing media items ({processed_count}/{total})...",
                        "current": processed_count,
                        "total": total,
                        "percent": pct,
                    })
                except Exception:
                    pass

    if batch_buffer:
        db_utils.batch_add_or_update_media_files(db_path, batch_buffer)
        batch_buffer.clear()

    if rescan:
        all_db_paths = db_utils.get_all_db_file_paths(db_path)
        for db_rel_path in all_db_paths:
            if db_rel_path not in processed_rel_paths:
                entry_to_delete = db_utils.get_media_file_by_path(db_path, db_rel_path)
                if entry_to_delete:
                    _delete_thumbnail_file(
                        thumbnail_dir_abs, entry_to_delete.get("thumbnail_file")
                    )
                    db_utils.delete_media_file_by_sha(
                        db_path, entry_to_delete["sha256_hex"]
                    )

    _cleanup_orphaned_thumbnails(db_path, thumbnail_dir_abs)

    if progress_callback:
        try:
            progress_callback({
                "phase": "complete",
                "message": "Media library scan complete.",
                "current": total,
                "total": total,
                "percent": 100.0,
            })
        except Exception:
            pass
