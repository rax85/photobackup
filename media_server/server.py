import datetime
import hashlib
import json
import mimetypes
import os
import sys
import tempfile
import threading
from typing import Optional

# Ensure project root is in sys.path
if __name__ == "__main__" and __package__ is None:
    PROJECT_ROOT_FOR_SERVER = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
    if PROJECT_ROOT_FOR_SERVER not in sys.path:
        sys.path.insert(0, PROJECT_ROOT_FOR_SERVER)

from absl import app as absl_app
from absl import flags, logging
from flask import (
    Flask,
    abort,
    g as flask_g,
    jsonify,
    request,
    send_from_directory,
)
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.utils import secure_filename

try:
    from . import archival as archival_utils
    from . import database as db_utils
    from . import media_scanner
    from . import settings as settings_utils
    from .image_classifier import ImageClassifier
except ImportError:
    from media_server import archival as archival_utils
    from media_server import database as db_utils
    from media_server import media_scanner
    from media_server import settings as settings_utils
    from media_server.image_classifier import ImageClassifier

FLAGS = flags.FLAGS
try:
    flags.DEFINE_string("storage_dir", None, "Directory to scan for media files.")
    flags.DEFINE_integer("port", 8000, "Port for the HTTP server.")
    flags.DEFINE_string(
        "db_name", db_utils.DATABASE_NAME, "Name of the SQLite database file."
    )
    if __name__ == "__main__":
        flags.mark_flag_as_required("storage_dir")
except flags.Error:
    pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB_DIR_ABSOLUTE = os.path.join(PROJECT_ROOT, "web")

app = Flask(__name__, static_folder=WEB_DIR_ABSOLUTE, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB limit
settings_manager: Optional[settings_utils.SettingsManager] = None
scanner_wakeup_event = threading.Event()

_cached_classifier = None
_cached_classifier_lock = threading.Lock()


class ScanStatus:
    """Thread-safe state container tracking library scanning progress."""

    def __init__(self):
        self._lock = threading.Lock()
        self.is_scanning = False
        self.initial_scan_in_progress = False
        self.initial_scan_completed = True
        self.phase = "idle"  # "idle", "discovering", "processing", "finalizing", "complete"
        self.message = "Idle"
        self.current = 0
        self.total = 0
        self.percent = 0.0
        self.error: Optional[str] = None

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def to_dict(self):
        with self._lock:
            return {
                "is_scanning": self.is_scanning,
                "initial_scan_in_progress": self.initial_scan_in_progress,
                "initial_scan_completed": self.initial_scan_completed,
                "phase": self.phase,
                "message": self.message,
                "current": self.current,
                "total": self.total,
                "percent": self.percent,
                "error": self.error,
            }


scan_status = ScanStatus()


def get_image_classifier(settings: settings_utils.Settings) -> ImageClassifier:
    """Returns a cached ImageClassifier instance, reloading only when model changes."""
    global _cached_classifier
    with _cached_classifier_lock:
        if (
            _cached_classifier is None
            or _cached_classifier.settings.tagging_model != settings.tagging_model
        ):
            if _cached_classifier is not None:
                _cached_classifier.unload()
            _cached_classifier = ImageClassifier(settings)
        return _cached_classifier


def get_settings_mgr() -> settings_utils.SettingsManager:
    """Helper to retrieve the active SettingsManager."""
    global settings_manager
    if settings_manager is not None:
        return settings_manager
    storage_dir = app.config.get("STORAGE_DIR", os.getcwd())
    settings_manager = settings_utils.SettingsManager(
        os.path.join(storage_dir, "settings.json")
    )
    return settings_manager


# --- Error Handling ---
@app.errorhandler(HTTPException)
def handle_http_exception(e: HTTPException):
    """Returns standardized JSON error responses."""
    response = e.get_response()
    response.data = json.dumps(
        {
            "error": e.description,
            "status_code": e.code,
        }
    )
    response.content_type = "application/json"
    return response, e.code


# --- Database Connection Handling ---
def get_db():
    """Returns a database connection for current request context."""
    if not hasattr(flask_g, "sqlite_db"):
        db_path = app.config.get("DATABASE_PATH") or db_utils.get_db_path(
            app.config.get("STORAGE_DIR")
        )
        flask_g.sqlite_db = db_utils.get_db_connection(db_path)
    return flask_g.sqlite_db


@app.teardown_appcontext
def close_db(error):
    """Closes DB connection at the end of the request."""
    db_utils.close_db_connection()
    if hasattr(flask_g, "sqlite_db"):
        try:
            flask_g.sqlite_db.close()
        except Exception:
            pass
        delattr(flask_g, "sqlite_db")


# --- Background Scanner ---
def background_scanner_task(app_context):
    """Background worker that performs initial scan and periodically rescans storage directory."""
    with app_context:
        storage_dir = app.config.get("STORAGE_DIR")
        db_path = app.config.get("DATABASE_PATH")
        if not storage_dir or not db_path:
            logging.error("Background scanner cannot start: missing config.")
            scan_status.update(
                is_scanning=False,
                initial_scan_in_progress=False,
                initial_scan_completed=True,
                phase="idle",
                message="Missing storage directory or database configuration.",
            )
            return

        def progress_cb(info):
            scan_status.update(
                phase=info.get("phase", scan_status.phase),
                message=info.get("message", scan_status.message),
                current=info.get("current", scan_status.current),
                total=info.get("total", scan_status.total),
                percent=info.get("percent", scan_status.percent),
            )

        # 1. Initial Scan execution (if requested)
        if scan_status.initial_scan_in_progress:
            logging.info(f"Background scanner running initial scan for dir: {storage_dir}")
            try:
                mgr = get_settings_mgr()
                settings = mgr.get()
                image_classifier = get_image_classifier(settings)
                media_scanner.scan_directory(
                    storage_dir,
                    db_path,
                    image_classifier,
                    rescan=False,
                    progress_callback=progress_cb,
                )
                logging.info("Initial scan complete.")
            except Exception as e:
                logging.error(f"Error during initial scan: {e}", exc_info=True)
                scan_status.update(error=str(e))
            finally:
                db_utils.close_db_connection()
                has_err = bool(scan_status.error)
                scan_status.update(
                    is_scanning=False,
                    initial_scan_in_progress=False,
                    initial_scan_completed=True,
                    phase="error" if has_err else "complete",
                    message=f"Initial scan encountered error: {scan_status.error}" if has_err else "Initial scan complete.",
                    percent=100.0,
                )

        # 2. Periodic rescan loop
        logging.info(f"Background scanner ready for periodic rescans: {storage_dir}")
        while True:
            mgr = get_settings_mgr()
            settings = mgr.get()
            rescan_interval = settings.rescan_interval

            if rescan_interval <= 0:
                logging.info("Rescanning disabled, sleeping until settings update.")
                scanner_wakeup_event.wait()
                scanner_wakeup_event.clear()
            else:
                woken = scanner_wakeup_event.wait(timeout=rescan_interval)
                if woken:
                    scanner_wakeup_event.clear()

            try:
                logging.info("Background scanner performing rescan...")
                scan_status.update(
                    is_scanning=True,
                    phase="discovering",
                    message="Scanning for library changes...",
                    current=0,
                    total=0,
                    percent=0.0,
                    error=None,
                )
                settings = mgr.get()
                image_classifier = get_image_classifier(settings)
                media_scanner.scan_directory(
                    storage_dir,
                    db_path,
                    image_classifier,
                    rescan=True,
                    progress_callback=progress_cb,
                )
                logging.info("Background rescan complete.")
            except Exception as e:
                logging.error(f"Error during background scan: {e}", exc_info=True)
                scan_status.update(error=str(e))
            finally:
                db_utils.close_db_connection()
                has_err = bool(scan_status.error)
                scan_status.update(
                    is_scanning=False,
                    phase="error" if has_err else "complete",
                    message=f"Rescan encountered error: {scan_status.error}" if has_err else "Rescan complete.",
                    percent=100.0,
                )


# --- API Routes ---
@app.route("/")
def root():
    """Serves the frontend SPA, or the scanning progress page if initial scan is active."""
    if scan_status.initial_scan_in_progress:
        return app.send_static_file("scanning.html")
    return app.send_static_file("index.html")


@app.route("/scanning")
def scanning_page():
    """Serves the scanning progress page."""
    return app.send_static_file("scanning.html")


@app.route("/list", methods=["GET"])
def list_media():
    """Returns media files in database, supporting limit and offset."""
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int)
    db_path = app.config["DATABASE_PATH"]
    all_media = db_utils.get_all_media_files(db_path, limit=limit, offset=offset)
    return jsonify(all_media)


@app.route("/api/media", methods=["GET"])
def api_media_paginated():
    """Returns paginated media records with total count and metadata."""
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)
    db_path = app.config["DATABASE_PATH"]
    total = db_utils.get_total_media_count(db_path)
    media_dict = db_utils.get_all_media_files(db_path, limit=limit, offset=offset)
    items = list(media_dict.values())
    return jsonify(
        {
            "items": items,
            "total_count": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(items)) < total,
        }
    )


@app.route("/list/date/<string:date_str>", methods=["GET"])
def list_media_by_date(date_str):
    """Lists media files for a specific date (YYYY-MM-DD)."""
    try:
        dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        timestamp = dt_obj.timestamp()
        media_files = db_utils.get_media_files_by_date(
            app.config["DATABASE_PATH"], timestamp
        )
        return jsonify(media_files)
    except ValueError:
        abort(400, description="Invalid date format. Please use YYYY-MM-DD.")


@app.route(
    "/list/daterange/<string:start_date_str>/<string:end_date_str>", methods=["GET"]
)
def list_media_by_date_range(start_date_str, end_date_str):
    """Lists media files within a date range (YYYY-MM-DD)."""
    try:
        start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
        end_dt = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        start_timestamp = start_dt.timestamp()
        end_timestamp = end_dt.timestamp()

        if start_timestamp > end_timestamp:
            abort(400, description="Start date must be before end date.")

        media_files = db_utils.get_media_files_by_date_range(
            app.config["DATABASE_PATH"], start_timestamp, end_timestamp
        )
        return jsonify(media_files)
    except ValueError:
        abort(400, description="Invalid date format. Please use YYYY-MM-DD.")


@app.route("/list/location/<string:city>", methods=["GET"])
@app.route("/list/location/<string:city>/<string:country>", methods=["GET"])
def list_media_by_location(city, country=None):
    """Lists media files for a specific location."""
    media_files = db_utils.get_media_files_by_location(
        app.config["DATABASE_PATH"], city, country
    )
    return jsonify(media_files)


@app.route("/api/search", methods=["GET"])
def api_search():
    """
    Smart multi-field search endpoint.
    Query params:
      q: Search query text
      type: 'image', 'video', or 'all'
      limit: Maximum records to return
      offset: Pagination offset
    """
    query = request.args.get("q", "").strip()
    media_type = request.args.get("type")
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int)

    results = db_utils.search_media_files(
        app.config["DATABASE_PATH"],
        query=query,
        media_type=media_type if media_type in ("image", "video") else None,
        limit=limit,
        offset=offset,
    )
    return jsonify(results)


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Returns library statistics."""
    stats = db_utils.get_database_stats(app.config["DATABASE_PATH"])
    return jsonify(stats)


@app.route("/api/scan/status", methods=["GET"])
def api_scan_status():
    """Returns current scan progress and status."""
    return jsonify(scan_status.to_dict())


@app.route("/api/scan", methods=["GET", "POST"])
def api_trigger_scan():
    """Triggers an immediate background rescan (POST) or returns scan status (GET)."""
    if request.method == "POST":
        scanner_wakeup_event.set()
        return jsonify({"message": "Rescan triggered successfully.", "status": scan_status.to_dict()})
    return jsonify(scan_status.to_dict())


ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "heic",
    "heif",
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
}


def allowed_file(filename: str) -> bool:
    """Validates allowed media extensions."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/image/<path:filename>", methods=["PUT"])
def put_image(filename):
    """Uploads a new media file."""
    if "file" not in request.files:
        abort(400, description="No file part in the request.")

    file_from_request = request.files["file"]
    original_client_filename = file_from_request.filename

    if not original_client_filename:
        abort(400, description="No selected file.")

    if not allowed_file(original_client_filename):
        abort(
            400,
            description=f"Invalid file type for '{original_client_filename}'. Allowed: {ALLOWED_EXTENSIONS}",
        )

    s_filename = secure_filename(filename)
    if not s_filename:
        s_filename = secure_filename(original_client_filename) or "unnamed_upload"

    today_str = datetime.datetime.now().strftime("%Y%m%d")
    upload_subdir_rel = os.path.join("uploads", today_str)
    upload_dir_abs = os.path.join(app.config["STORAGE_DIR"], upload_subdir_rel)
    os.makedirs(upload_dir_abs, exist_ok=True)

    sha256_calc = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=upload_dir_abs, delete=False, suffix=".tmp") as tmp_file:
        tmp_path = tmp_file.name
        while True:
            chunk = file_from_request.stream.read(65536)
            if not chunk:
                break
            sha256_calc.update(chunk)
            tmp_file.write(chunk)

    sha256_hash = sha256_calc.hexdigest()
    db_path = app.config["DATABASE_PATH"]

    existing_entry = db_utils.get_media_file_by_sha(db_path, sha256_hash)
    if existing_entry:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return (
            jsonify(
                {
                    "message": "Image content already exists in DB.",
                    "sha256": sha256_hash,
                    "filename": existing_entry.get("filename"),
                    "file_path": existing_entry.get("file_path"),
                }
            ),
            200,
        )

    base, ext = os.path.splitext(s_filename)
    ext = ext.lower()
    final_filename_on_disk = f"{base}{ext}"
    target_path = os.path.join(upload_dir_abs, final_filename_on_disk)
    counter = 0
    while os.path.exists(target_path):
        counter += 1
        final_filename_on_disk = f"{base}_{counter}{ext}"
        target_path = os.path.join(upload_dir_abs, final_filename_on_disk)

    try:
        os.replace(tmp_path, target_path)
    except OSError as e:
        logging.error(f"Failed to save file: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        abort(500, description="Failed to save media to disk.")

    thumbnail_dir_abs = app.config["THUMBNAIL_DIR"]
    thumbnail_relative_path = media_scanner.generate_thumbnail(
        target_path, thumbnail_dir_abs, sha256_hash
    )

    mime_type_upload, _ = mimetypes.guess_type(target_path)
    filesize = os.path.getsize(target_path)
    last_modified = os.path.getmtime(target_path)
    original_creation_date = os.path.getctime(target_path)
    image_width, image_height = None, None
    latitude, longitude, city, country = None, None, None, None

    if mime_type_upload and mime_type_upload.startswith("image/"):
        try:
            from PIL import Image as PILImage

            with PILImage.open(target_path) as img:
                image_width, image_height = img.size
                exif_data = img.getexif()
                if exif_data:
                    date_time_original_tag = 36867
                    date_time_tag = 306
                    exif_date_str = exif_data.get(
                        date_time_original_tag
                    ) or exif_data.get(date_time_tag)
                    if exif_date_str:
                        try:
                            dt_obj = datetime.datetime.strptime(
                                str(exif_date_str), "%Y:%m:%d %H:%M:%S"
                            )
                            original_creation_date = dt_obj.timestamp()
                        except (ValueError, TypeError):
                            pass

                    lat, lon = media_scanner._get_gps_coordinates_from_exif(exif_data)
                    if lat is not None:
                        latitude = lat
                    if lon is not None:
                        longitude = lon
                    if latitude is not None and longitude is not None:
                        geolocator = media_scanner.GeoLocator()
                        cities_csv_path = os.path.join(
                            os.path.dirname(__file__), "resources", "cities.csv"
                        )
                        geolocator.load_cities(cities_csv_path)
                        closest_city = geolocator.nearest_city(latitude, longitude)
                        if closest_city:
                            city, country = closest_city.name, closest_city.country
        except Exception as e:
            logging.warning(f"Could not read metadata for uploaded file: {e}")

    settings = get_settings_mgr().get()
    image_classifier = get_image_classifier(settings)
    tags = None
    if mime_type_upload and mime_type_upload.startswith("image/"):
        tags = image_classifier.classify_image(target_path)

    relative_file_path_for_db = os.path.join(upload_subdir_rel, final_filename_on_disk)
    media_data = {
        "sha256_hex": sha256_hash,
        "filename": final_filename_on_disk,
        "original_filename": original_client_filename,
        "file_path": relative_file_path_for_db,
        "last_modified": last_modified,
        "original_creation_date": original_creation_date,
        "thumbnail_file": thumbnail_relative_path,
        "width": image_width,
        "height": image_height,
        "latitude": latitude,
        "longitude": longitude,
        "city": city,
        "country": country,
        "mime_type": mime_type_upload,
        "filesize": filesize,
        "tags": json.dumps(tags) if tags else None,
        "tagging_model": settings.tagging_model if tags else None,
    }
    db_utils.add_or_update_media_file(db_path, media_data)

    return (
        jsonify(
            {
                "message": "Image uploaded and processed successfully.",
                "sha256": sha256_hash,
                "filename": final_filename_on_disk,
                "file_path": relative_file_path_for_db,
                "thumbnail_file": thumbnail_relative_path,
                "width": image_width,
                "height": image_height,
            }
        ),
        201,
    )


@app.route("/image/<string:sha256_hex>", methods=["GET"])
@app.route("/image/sha256/<string:sha256_hex>", methods=["GET"])
def get_image(sha256_hex):
    """Serves media file with HTTP Range support for streaming."""
    if not (
        len(sha256_hex) == 64 and all(c in "0123456789abcdefABCDEF" for c in sha256_hex)
    ):
        abort(400, description="Invalid SHA256 format.")

    db_entry = db_utils.get_media_file_by_sha(app.config["DATABASE_PATH"], sha256_hex)
    if not db_entry:
        abort(404, description="Image not found (SHA unknown in DB).")

    file_path_relative = db_entry.get("file_path")
    if not file_path_relative:
        abort(500, description="Server error: Image metadata incomplete in DB.")

    storage_dir_abs = app.config["STORAGE_DIR"]
    full_file_path = os.path.normpath(os.path.join(storage_dir_abs, file_path_relative))
    if not full_file_path.startswith(
        os.path.normpath(storage_dir_abs) + os.sep
    ) and full_file_path != os.path.normpath(storage_dir_abs):
        abort(400, description="Invalid file path generated.")

    ext = os.path.splitext(file_path_relative)[1].lower()

    # Web browsers cannot render HEIC natively in <img> tags.
    # Serve a cached high-quality JPEG preview.
    if ext in {".heic", ".heif"}:
        preview_dir = os.path.join(app.config["THUMBNAIL_DIR"], "previews", sha256_hex[:2])
        os.makedirs(preview_dir, exist_ok=True)
        preview_file = os.path.join(preview_dir, f"{sha256_hex}.jpg")

        if not os.path.isfile(preview_file) or os.path.getsize(preview_file) == 0:
            try:
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except ImportError:
                    pass
                from PIL import Image, ImageOps
                with Image.open(full_file_path) as img:
                    img = ImageOps.exif_transpose(img)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.save(preview_file, "JPEG", quality=92, optimize=True)
            except Exception as e:
                logging.error(f"Failed to convert HEIC to JPEG preview: {e}")
                if os.path.exists("/usr/bin/sips"):
                    try:
                        import subprocess
                        subprocess.run(
                            ["/usr/bin/sips", "-s", "format", "jpeg", full_file_path, "--out", preview_file],
                            check=True,
                            capture_output=True,
                        )
                    except Exception as sips_err:
                        logging.error(f"SIPS fallback failed: {sips_err}")

        if os.path.isfile(preview_file) and os.path.getsize(preview_file) > 0:
            return send_from_directory(
                preview_dir, f"{sha256_hex}.jpg", mimetype="image/jpeg", conditional=True
            )

    mimetype = None
    if ext in {".mov", ".mp4", ".m4v"}:
        mimetype = "video/mp4"
    elif ext == ".webm":
        mimetype = "video/webm"
    elif ext in {".jpg", ".jpeg"}:
        mimetype = "image/jpeg"
    elif ext == ".png":
        mimetype = "image/png"

    try:
        return send_from_directory(
            storage_dir_abs, file_path_relative, mimetype=mimetype, conditional=True
        )
    except NotFound:
        abort(404, description="Image file not found on disk.")


@app.route("/thumbnail/<string:sha256_hex>", methods=["GET"])
def get_thumbnail(sha256_hex):
    """Serves generated thumbnail image, generating on demand if needed."""
    if not (
        len(sha256_hex) == 64 and all(c in "0123456789abcdefABCDEF" for c in sha256_hex)
    ):
        abort(400, description="Invalid SHA256 format.")

    db_entry = db_utils.get_media_file_by_sha(app.config["DATABASE_PATH"], sha256_hex)
    if not db_entry:
        abort(404, description="Image SHA not found in DB, so no thumbnail.")

    thumbnail_dir_abs = app.config["THUMBNAIL_DIR"]
    if not os.path.isdir(thumbnail_dir_abs):
        os.makedirs(thumbnail_dir_abs, exist_ok=True)

    thumbnail_relative_path = db_entry.get("thumbnail_file")
    storage_dir_abs = app.config["STORAGE_DIR"]
    file_path_relative = db_entry.get("file_path")
    full_source_path = (
        os.path.normpath(os.path.join(storage_dir_abs, file_path_relative))
        if file_path_relative
        else None
    )

    full_thumb_path = (
        os.path.normpath(os.path.join(thumbnail_dir_abs, thumbnail_relative_path))
        if thumbnail_relative_path
        else None
    )

    if not full_thumb_path or not os.path.isfile(full_thumb_path):
        if full_source_path and os.path.isfile(full_source_path):
            thumbnail_relative_path = media_scanner.generate_thumbnail(
                full_source_path, thumbnail_dir_abs, sha256_hex
            )
            if thumbnail_relative_path:
                db_utils.update_media_file_fields(
                    app.config["DATABASE_PATH"],
                    sha256_hex,
                    {"thumbnail_file": thumbnail_relative_path},
                )
                full_thumb_path = os.path.normpath(
                    os.path.join(thumbnail_dir_abs, thumbnail_relative_path)
                )

    if (
        not thumbnail_relative_path
        or not full_thumb_path
        or not os.path.isfile(full_thumb_path)
    ):
        abort(404, description="Thumbnail not available for this item.")

    if not full_thumb_path.startswith(os.path.normpath(thumbnail_dir_abs) + os.sep):
        abort(400, description="Invalid thumbnail path.")

    try:
        return send_from_directory(
            thumbnail_dir_abs, thumbnail_relative_path, mimetype="image/png"
        )
    except NotFound:
        abort(404, description="Thumbnail file missing on disk.")


@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Retrieves current application settings."""
    mgr = get_settings_mgr()
    return jsonify(mgr.get().to_dict())


@app.route("/api/settings", methods=["PUT"])
def put_settings():
    """Updates application settings and wakes up scanner if necessary."""
    if not request.json:
        abort(400, description="Request body must be a JSON object.")

    try:
        mgr = get_settings_mgr()
        current_settings = mgr.get()
        new_settings = settings_utils.Settings(**request.json)
        mgr.write_settings(new_settings)

        if (
            current_settings.rescan_interval != new_settings.rescan_interval
            or current_settings.tagging_model != new_settings.tagging_model
        ):
            scanner_wakeup_event.set()

        return jsonify(new_settings.to_dict())
    except (TypeError, ValueError) as e:
        abort(400, description=f"Invalid settings format: {e}")


@app.route("/api/archival/test", methods=["POST"])
def test_archival_connection():
    """Tests cloud archival connectivity."""
    mgr = get_settings_mgr()
    archival_mgr = archival_utils.ArchivalManager(mgr.get())
    return jsonify(archival_mgr.test_status())


def run_flask_app(argv):
    """Configures and runs the Flask production/dev server."""
    del argv
    logging.set_verbosity(logging.INFO)

    storage_dir = FLAGS.storage_dir
    if not storage_dir:
        logging.error("Storage directory not provided.")
        sys.exit(1)

    storage_dir = os.path.abspath(storage_dir)
    os.makedirs(storage_dir, exist_ok=True)

    app.config["STORAGE_DIR"] = storage_dir
    app.config["THUMBNAIL_DIR"] = os.path.join(
        storage_dir, media_scanner.THUMBNAIL_DIR_NAME
    )
    os.makedirs(app.config["THUMBNAIL_DIR"], exist_ok=True)
    app.config["DATABASE_PATH"] = db_utils.get_db_path(storage_dir)

    global settings_manager
    settings_manager = settings_utils.SettingsManager(
        os.path.join(storage_dir, "settings.json")
    )

    db_utils.init_db(storage_dir)
    db_utils.close_db_connection()

    # Mark initial scan as active so that visiting users see the progress page
    scan_status.update(
        is_scanning=True,
        initial_scan_in_progress=True,
        initial_scan_completed=False,
        phase="discovering",
        message="Discovering media files for initial scan...",
        current=0,
        total=0,
        percent=0.0,
        error=None,
    )

    # Background scanner thread (handles initial scan and periodic rescans)
    scanner_thread = threading.Thread(
        target=background_scanner_task,
        args=(app.app_context(),),
        daemon=True,
    )
    scanner_thread.start()

    logging.info(f"Starting PhotoBackup server immediately on port {FLAGS.port}...")
    app.run(host="0.0.0.0", port=FLAGS.port, debug=False, use_reloader=False)


def main_flask():
    absl_app.run(run_flask_app)


if __name__ == "__main__":
    main_flask()
