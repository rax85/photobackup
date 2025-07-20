# At the very beginning of media_server/server.py
import os
import sys

# Ensure the project root is in sys.path for direct execution
if __name__ == '__main__' and __package__ is None:
    PROJECT_ROOT_FOR_SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if PROJECT_ROOT_FOR_SERVER not in sys.path:
        sys.path.insert(0, PROJECT_ROOT_FOR_SERVER)

import dataclasses
import threading
import time
import datetime
import hashlib
import mimetypes # for guessing mime type of uploaded file
from werkzeug.utils import secure_filename
from werkzeug.exceptions import NotFound
from flask import request, g as flask_g # Added g for db connection per request

from absl import app as absl_app
from absl import flags, logging
from flask import Flask, jsonify, abort, send_from_directory

# Correctly import from the same package
try:
    from . import media_scanner
    from . import database as db_utils
    from . import settings as settings_utils
except ImportError:
    from media_server import media_scanner # Fallback for direct execution
    from media_server import database as db_utils
    from media_server import settings as settings_utils


FLAGS = flags.FLAGS

# Define flags if not already defined
try:
    flags.DEFINE_string('storage_dir', None, 'Directory to scan for media files.')
    flags.DEFINE_integer('port', 8000, 'Port for the HTTP server.')
    flags.DEFINE_integer('rescan_interval', 0, 'Interval in seconds for background rescanning. 0 to disable.')
    flags.DEFINE_string('db_name', db_utils.DATABASE_NAME, 'Name of the SQLite database file.')
    if __name__ == "__main__": # Mark as required only if this script is the entry point
        flags.mark_flag_as_required('storage_dir')
except flags.Error:
    pass # Flags are already defined


# Determine the absolute path to the project's root directory
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WEB_DIR_ABSOLUTE = os.path.join(PROJECT_ROOT, 'web')

app = Flask(__name__, static_folder=WEB_DIR_ABSOLUTE, static_url_path='')

# --- Database Connection Handling ---
def get_db():
    """
    Returns a database connection for the current application context.

    If a connection does not exist, it creates one and stores it in the
    application context (`flask.g`) for reuse during the same request.

    Returns:
        A sqlite3.Connection object.
    """
    if not hasattr(flask_g, 'sqlite_db'):
        db_path = app.config.get('DATABASE_PATH')
        if not db_path:
            # This should ideally not happen if app is configured correctly
            logging.error("DATABASE_PATH not configured in Flask app.")
            # Fallback to default path construction, though storage_dir might not be known here
            # This part of get_db might need to be more robust if app.config isn't ready.
            # For now, assume DATABASE_PATH is set during app initialization.
            # A possible issue: if get_db() is called outside request context AND before app config is fully set.
            # However, db_utils.get_db_connection itself can derive from storage_dir if given.
            # The main Flask app setup will put the correct DB path into app.config['DATABASE_PATH']
            # which db_utils.get_db_connection will use via flask_g.
            # If this is called from background thread, flask_g won't be available.
            # Background thread needs its own connection management.
            # The db_utils.thread_local should handle this.
            # This flask_g based one is for request threads.
            flask_g.sqlite_db = db_utils.get_db_connection(db_utils.get_db_path(app.config.get('STORAGE_DIR')))
        else:
            flask_g.sqlite_db = db_utils.get_db_connection(db_path)
    return flask_g.sqlite_db

@app.teardown_appcontext
def close_db(error):
    """
    Closes the database connection at the end of the request.

    This function is registered with Flask's `teardown_appcontext` and is
    automatically called when the application context is popped.

    Args:
        error: An exception that occurred during the request, if any.
    """
    if hasattr(flask_g, 'sqlite_db'):
        db_utils.close_db_connection() # This uses thread_local.connection
        delattr(flask_g, 'sqlite_db') # Remove from flask_g

# --- Background Scanner ---
def background_scanner_task(app_context):
    """
    A background task that periodically rescans the storage directory.

    This function runs in a separate thread and triggers a rescan of the
    media directory at a configurable interval.

    Args:
        app_context: The Flask application context.
    """
    # Background thread needs to manage its own DB connection via db_utils.thread_local
    # It doesn't use flask_g.
    # The app_context is passed to allow the thread to configure logging or other app settings if needed
    # but primarily for accessing app.config values like STORAGE_DIR and DATABASE_PATH.

    # Wait a moment for the main server to potentially start up and log its messages.
    time.sleep(5)

    with app_context: # Use the app context for config access
        storage_dir = app.config.get('STORAGE_DIR')
        db_path = app.config.get('DATABASE_PATH') # Get the configured DB path
        rescan_interval = app.config.get('RESCAN_INTERVAL')

        if not storage_dir or not db_path or rescan_interval <= 0:
            logging.error("Background scanner cannot start: storage_dir, db_path, or rescan_interval not configured properly.")
            return

        logging.info(f"Background scanner started. Rescan interval: {rescan_interval} seconds for dir: {storage_dir}, DB: {db_path}")
        while True:
            try:
                # The db_utils.get_db_connection() called by media_scanner will use thread_local
                # to get/create a connection for this background thread.
                logging.info("Background scanner performing rescan...")
                media_scanner.scan_directory(storage_dir, db_path, rescan=True)
                logging.info("Background rescan complete.")
            except Exception as e:
                logging.error(f"Error during background scan: {e}", exc_info=True)
            finally:
                # Ensure connection for this thread is closed after each scan cycle
                db_utils.close_db_connection()
            time.sleep(rescan_interval)


# --- Flask Routes ---
@app.route('/')
def root():
    """
    Serves the main `index.html` page.

    Returns:
        The `index.html` file from the static folder.
    """
    return app.send_static_file('index.html')

@app.route('/list', methods=['GET'])
def list_media():
    """
    Returns a list of all media files in the database.

    Returns:
        A JSON response containing a dictionary of all media files.
    """
    # get_db() will be called implicitly by db_utils if using flask_g,
    # or db_utils manages its own thread_local connection.
    # For request context, get_db() here ensures flask_g.sqlite_db is set.
    # db_conn_for_request = get_db() # Establishes flask_g.sqlite_db if not present

    # db_utils functions now use app.config['DATABASE_PATH'] via their own get_db_path if flask_g not set,
    # or directly use the connection from flask_g if set by get_db().
    # The crucial part is that db_utils.get_db_connection gets the correct db_path.
    all_media = db_utils.get_all_media_files(app.config['DATABASE_PATH'])
    logging.info(f"Served /list request, found {len(all_media)} items.")
    return jsonify(all_media)

@app.route('/list/date/<string:date_str>', methods=['GET'])
def list_media_by_date(date_str):
    """
    Lists media files for a specific date.
    Date format should be YYYY-MM-DD.
    """
    try:
        # Convert YYYY-MM-DD string to a datetime object, then to a timestamp
        dt_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        # To get a full day, we can find the start and end of the day.
        # However, the DB function get_media_files_by_date uses date() SQL function,
        # so passing the timestamp of the beginning of the day is sufficient.
        timestamp = dt_obj.timestamp()
        media_files = db_utils.get_media_files_by_date(app.config['DATABASE_PATH'], timestamp)
        logging.info(f"Served /list/date/{date_str} request, found {len(media_files)} items.")
        return jsonify(media_files)
    except ValueError:
        abort(400, description="Invalid date format. Please use YYYY-MM-DD.")

@app.route('/list/daterange/<string:start_date_str>/<string:end_date_str>', methods=['GET'])
def list_media_by_date_range(start_date_str, end_date_str):
    """
    Lists media files within a date range.
    Date format should be YYYY-MM-DD.
    """
    try:
        start_dt = datetime.datetime.strptime(start_date_str, '%Y-%m-%d')
        end_dt = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
        # To be inclusive of the end date, set time to end of day
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

        start_timestamp = start_dt.timestamp()
        end_timestamp = end_dt.timestamp()

        if start_timestamp > end_timestamp:
            abort(400, description="Start date must be before end date.")

        media_files = db_utils.get_media_files_by_date_range(app.config['DATABASE_PATH'], start_timestamp, end_timestamp)
        logging.info(f"Served /list/daterange/ request from {start_date_str} to {end_date_str}, found {len(media_files)} items.")
        return jsonify(media_files)
    except ValueError:
        abort(400, description="Invalid date format. Please use YYYY-MM-DD.")

@app.route('/list/location/<string:city>', methods=['GET'])
@app.route('/list/location/<string:city>/<string:country>', methods=['GET'])
def list_media_by_location(city, country=None):
    """
    Lists media files for a specific location (city and optional country).
    """
    media_files = db_utils.get_media_files_by_location(app.config['DATABASE_PATH'], city, country)
    location_str = f"{city}/{country}" if country else city
    logging.info(f"Served /list/location/{location_str} request, found {len(media_files)} items.")
    return jsonify(media_files)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'heic', 'heif', 'mp4', 'mov', 'avi'}

def allowed_file(filename):
    """
    Checks if a filename has an allowed extension.

    Args:
        filename: The name of the file to check.

    Returns:
        True if the filename has an allowed extension, False otherwise.
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/image/<path:filename>', methods=['PUT'])
def put_image(filename): # filename comes from the <path:filename> URL part
    """
    Handles image uploads via PUT request.

    This endpoint allows clients to upload new image files. The server saves
    the file, generates a thumbnail, and adds a corresponding entry to the
    database.

    Args:
        filename: The filename for the uploaded image, extracted from the URL.

    Returns:
        A JSON response with details of the uploaded image or an error message.
    """
    if 'file' not in request.files:
        abort(400, description="No file part in the request.")

    file_from_request = request.files['file']
    original_client_filename = file_from_request.filename # Original name from client

    if original_client_filename == '':
        abort(400, description="No selected file.")

    if not allowed_file(original_client_filename):
        abort(400, description=f"Invalid file type for '{original_client_filename}'. Allowed: {ALLOWED_EXTENSIONS}")

    # Sanitize the filename from URL, or use sanitized client filename if URL one is bad
    s_filename = secure_filename(filename) # Use the 'filename' arg from the route
    if not s_filename:
        s_filename = secure_filename(original_client_filename)
        if not s_filename: # If both are bad, create a default
             s_filename = "unnamed_upload" + os.path.splitext(original_client_filename)[1].lower()

    file_contents = file_from_request.read()
    sha256_hash = hashlib.sha256(file_contents).hexdigest()
    db_path = app.config['DATABASE_PATH']

    existing_entry = db_utils.get_media_file_by_sha(db_path, sha256_hash)
    if existing_entry:
        logging.info(f"Image with SHA256 {sha256_hash} (filename: {s_filename}) already exists in DB. Path: {existing_entry.get('file_path')}")
        return jsonify({
            "message": "Image content already exists in DB.",
            "sha256": sha256_hash,
            "filename": existing_entry.get('filename'),
            "file_path": existing_entry.get('file_path')
        }), 200 # OK, content already present

    # Determine save path
    today_str = datetime.datetime.now().strftime('%Y%m%d')
    upload_subdir_rel = os.path.join("uploads", today_str) # Relative to storage_dir
    upload_dir_abs = os.path.join(app.config['STORAGE_DIR'], upload_subdir_rel)
    os.makedirs(upload_dir_abs, exist_ok=True)

    base, ext = os.path.splitext(s_filename)
    ext = ext.lower()
    if not base and ext: base = "image" # Handle cases like ".jpg"

    final_filename_on_disk = f"{base}{ext}"
    prospective_path_on_disk_abs = os.path.join(upload_dir_abs, final_filename_on_disk)
    counter = 0
    while os.path.exists(prospective_path_on_disk_abs):
        counter += 1
        final_filename_on_disk = f"{base}_{counter}{ext}"
        prospective_path_on_disk_abs = os.path.join(upload_dir_abs, final_filename_on_disk)

    try:
        with open(prospective_path_on_disk_abs, "wb") as f_save:
            f_save.write(file_contents)
        logging.info(f"Saved new image: {final_filename_on_disk} to {upload_subdir_rel} (SHA256: {sha256_hash})")
    except IOError as e:
        logging.error(f"Failed to save file {final_filename_on_disk} to {upload_dir_abs}: {e}")
        abort(500, description="Failed to save image to disk.")

    # Process the newly saved file to add it to the database
    # This reuses parts of the scanner logic for a single file.
    # _process_single_file needs abs_storage_dir, abs_file_path, sha, db_path, thumbnail_dir_abs, disk_filename
    # We can call a simplified version or directly populate media_data

    thumbnail_dir_abs = app.config['THUMBNAIL_DIR']
    thumbnail_relative_path = None
    mime_type_upload, _ = mimetypes.guess_type(prospective_path_on_disk_abs)
    filesize = os.path.getsize(prospective_path_on_disk_abs)


    if mime_type_upload and mime_type_upload.startswith('image/'):
        thumbnail_relative_path = media_scanner.generate_thumbnail(
            prospective_path_on_disk_abs,
            thumbnail_dir_abs,
            sha256_hash
        )

    # Extract metadata (simplified from _process_single_file)
    last_modified = os.path.getmtime(prospective_path_on_disk_abs)
    original_creation_date = os.path.getctime(prospective_path_on_disk_abs) # Default
    image_width, image_height = None, None
    latitude, longitude = None, None

    if mime_type_upload and mime_type_upload.startswith('image/'):
        try:
            from PIL import Image as PILImage, ExifTags as PILExifTags # Local import for safety
            with PILImage.open(prospective_path_on_disk_abs) as img:
                image_width, image_height = img.size
                exif_data = img.getexif()
                if exif_data:
                    date_tag = 36867 # DateTimeOriginal
                    if date_tag in exif_data:
                        exif_date_str = exif_data[date_tag]
                        try:
                            dt_obj = datetime.datetime.strptime(exif_date_str, '%Y:%m:%d %H:%M:%S')
                            original_creation_date = dt_obj.timestamp()
                        except (ValueError, TypeError): pass # Ignore malformed
                    lat, lon = media_scanner._get_gps_coordinates_from_exif(exif_data)
                    if lat is not None: latitude = lat
                    if lon is not None: longitude = lon
        except Exception as e:
            logging.warning(f"Could not read full EXIF for uploaded {final_filename_on_disk}: {e}")

    relative_file_path_for_db = os.path.join(upload_subdir_rel, final_filename_on_disk)
    media_data = {
        'sha256_hex': sha256_hash,
        'filename': final_filename_on_disk, # Name on disk in its upload subfolder
        'original_filename': original_client_filename, # Original name from client
        'file_path': relative_file_path_for_db, # Relative to storage_dir
        'last_modified': last_modified,
        'original_creation_date': original_creation_date,
        'thumbnail_file': thumbnail_relative_path,
        'width': image_width,
        'height': image_height,
        'latitude': latitude,
        'longitude': longitude,
        'mime_type': mime_type_upload,
        'filesize': filesize
    }
    db_utils.add_or_update_media_file(db_path, media_data)
    logging.info(f"DB entry created for uploaded SHA256: {sha256_hash}, file {final_filename_on_disk}")

    return jsonify({
        "message": "Image uploaded and processed successfully.",
        "sha256": sha256_hash,
        "filename": final_filename_on_disk,
        "file_path": relative_file_path_for_db,
        "thumbnail_file": thumbnail_relative_path,
        "width": image_width,
        "height": image_height
    }), 201


@app.route('/image/<string:sha256_hex>', methods=['GET'])
@app.route('/image/sha256/<string:sha256_hex>', methods=['GET']) # Alias
def get_image(sha256_hex):
    """
    Serves an image file based on its SHA256 hash.

    Args:
        sha256_hex: The SHA256 hash of the image to retrieve.

    Returns:
        The image file as a response, or a 404 error if not found.
    """
    if not (len(sha256_hex) == 64 and all(c in '0123456789abcdefABCDEF' for c in sha256_hex)):
        abort(400, description="Invalid SHA256 format.")

    db_entry = db_utils.get_media_file_by_sha(app.config['DATABASE_PATH'], sha256_hex)
    if not db_entry:
        abort(404, description="Image not found (SHA unknown in DB).")

    file_path_relative = db_entry.get('file_path')
    if not file_path_relative:
        abort(500, description="Server error: Image metadata incomplete in DB (no file_path).")

    storage_dir_abs = app.config['STORAGE_DIR']
    # Security check (already in db_utils.get_media_file_by_sha, but defense in depth)
    full_file_path = os.path.normpath(os.path.join(storage_dir_abs, file_path_relative))
    if not full_file_path.startswith(os.path.normpath(storage_dir_abs) + os.sep) and \
       not full_file_path == os.path.normpath(storage_dir_abs):
        abort(400, description="Invalid file path generated.")

    try:
        return send_from_directory(storage_dir_abs, file_path_relative)
    except NotFound:
        abort(404, description="Image file not found on disk (DB out of sync?).")


settings_manager: settings_utils.SettingsManager = None

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """
    Returns the current application settings.
    """
    return jsonify(dataclasses.asdict(settings_manager.get()))

@app.route('/api/settings', methods=['PUT'])
def put_settings():
    """
    Updates the application settings.
    """
    if not request.json:
        abort(400, description="Request body must be a JSON object.")

    try:
        new_settings = settings_utils.Settings(**request.json)
        settings_manager.write_settings(new_settings)
        return jsonify(dataclasses.asdict(new_settings))
    except (TypeError, ValueError) as e:
        abort(400, description=f"Invalid settings format: {e}")


@app.route('/thumbnail/<string:sha256_hex>', methods=['GET'])
def get_thumbnail(sha256_hex):
    """
    Serves a thumbnail image for a given SHA256 hash.

    Args:
        sha256_hex: The SHA256 hash of the original image.

    Returns:
        The thumbnail image file as a response, or a 404 error if not found.
    """
    if not (len(sha256_hex) == 64 and all(c in '0123456789abcdefABCDEF' for c in sha256_hex)):
        abort(400, description="Invalid SHA256 format.")

    db_entry = db_utils.get_media_file_by_sha(app.config['DATABASE_PATH'], sha256_hex)
    if not db_entry:
        abort(404, description="Image SHA not found in DB, so no thumbnail.")

    thumbnail_relative_path = db_entry.get('thumbnail_file')
    if not thumbnail_relative_path:
        # This could be a non-image file, or thumbnail generation failed.
        # Check mime type from db_entry to return more specific error or placeholder
        mime_type = db_entry.get('mime_type')
        if mime_type and mime_type.startswith('video/'):
             # TODO: Could serve a generic video icon thumbnail later
            abort(404, description=f"Thumbnails not supported for video type {mime_type} yet, or this video has no thumbnail.")
        abort(404, description="Thumbnail not available for this item.")

    thumbnail_dir_abs = app.config['THUMBNAIL_DIR']
    if not os.path.isdir(thumbnail_dir_abs): # Should have been created by scanner
        abort(500, description="Thumbnail directory misconfigured or missing on server.")

    # Security check for thumbnail_relative_path (e.g. 'ab/hash.png')
    # Ensure it doesn't try to escape thumbnail_dir_abs
    full_thumb_path = os.path.normpath(os.path.join(thumbnail_dir_abs, thumbnail_relative_path))
    if not full_thumb_path.startswith(os.path.normpath(thumbnail_dir_abs) + os.sep):
        abort(400, description="Invalid thumbnail path.")

    try:
        return send_from_directory(thumbnail_dir_abs, thumbnail_relative_path, mimetype='image/png')
    except NotFound:
         # This implies DB has a thumbnail_file entry, but the file is missing.
        logging.warning(f"Thumbnail file {thumbnail_relative_path} for SHA {sha256_hex} not found on disk (DB out of sync?).")
        # Scanner should ideally clean this up or regenerate.
        abort(404, description="Thumbnail file missing on disk.")


def run_flask_app(argv):
    """
    Configures and starts the Flask web server.

    This function initializes the application, sets up the database, performs
    an initial media scan, and starts the Flask development server.

    Args:
        argv: Command-line arguments passed to the application.
    """
    del argv # Unused.

    logging.set_verbosity(logging.INFO)

    storage_dir = FLAGS.storage_dir
    if not storage_dir:
        logging.error("Storage directory not provided via --storage_dir flag.")
        sys.exit(1)

    # Make storage_dir absolute
    storage_dir = os.path.abspath(storage_dir)
    os.makedirs(storage_dir, exist_ok=True) # Ensure storage_dir exists

    app.config['STORAGE_DIR'] = storage_dir
    app.config['THUMBNAIL_DIR'] = os.path.join(storage_dir, media_scanner.THUMBNAIL_DIR_NAME)
    os.makedirs(app.config['THUMBNAIL_DIR'], exist_ok=True) # Ensure .thumbnails exists

    # Database path configuration
    # db_utils.get_db_path will use this name inside storage_dir
    app.config['DATABASE_PATH'] = db_utils.get_db_path(storage_dir) # FLAGS.db_name is just the filename
    app.config['RESCAN_INTERVAL'] = FLAGS.rescan_interval

    logging.info(f"Storage directory: {app.config['STORAGE_DIR']}")
    logging.info(f"Thumbnail directory: {app.config['THUMBNAIL_DIR']}")
    logging.info(f"Database path: {app.config['DATABASE_PATH']}")

    global settings_manager
    settings_manager = settings_utils.SettingsManager(os.path.join(storage_dir, 'settings.json'))


    # Initialize DB (create tables if not exist)
    # This init_db is for the main thread. It will use its own connection.
    try:
        db_utils.init_db(storage_dir) # Pass storage_dir so it can construct the correct db_path
    except Exception as e:
        logging.error(f"Failed to initialize database at {app.config['DATABASE_PATH']}: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db_utils.close_db_connection() # Close connection for main thread after init

    # Initial scan of the media directory (rescan=False)
    logging.info(f"Performing initial scan of storage directory: {app.config['STORAGE_DIR']}")
    try:
        media_scanner.scan_directory(app.config['STORAGE_DIR'], app.config['DATABASE_PATH'], rescan=False)
    except Exception as e:
        logging.error(f"Error during initial scan: {e}", exc_info=True)
        # Decide if server should start if initial scan fails. For now, it will.
    finally:
        db_utils.close_db_connection() # Close connection for main thread after scan

    num_items_in_db = len(db_utils.get_all_media_files(app.config['DATABASE_PATH']))
    logging.info(f"Initial scan complete. Database contains {num_items_in_db} items.")
    db_utils.close_db_connection() # Close again, just in case get_all_media_files opened one.

    if FLAGS.rescan_interval > 0:
        # Pass the current app's context to the thread if needed for config
        scanner_thread = threading.Thread(target=background_scanner_task, args=(app.app_context(),), daemon=True)
        scanner_thread.start()
    else:
        logging.info("Background rescanning disabled.")

    logging.info(f"Starting Flask HTTP server on port {FLAGS.port}...")
    app.run(host='0.0.0.0', port=FLAGS.port, debug=False, use_reloader=False)

def main_flask():
    absl_app.run(run_flask_app)

if __name__ == '__main__':
    main_flask()
