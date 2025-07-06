import json
import os
import sys
import threading
import time
import datetime
import hashlib
from werkzeug.utils import secure_filename
from flask import request # Added for file upload handling

from absl import app as absl_app
from absl import flags, logging
from flask import Flask, jsonify, abort, send_from_directory

# Correctly import from the same package
try:
    from . import media_scanner
except ImportError:
    import media_scanner # Fallback for direct execution

FLAGS = flags.FLAGS

# Define flags if not already defined (e.g., when running tests that don't invoke main())
# This is a bit of a workaround for absl's flag system.
try:
    flags.DEFINE_string('storage_dir', None, 'Directory to scan for media files.')
    flags.DEFINE_integer('port', 8000, 'Port for the HTTP server.')
    flags.DEFINE_integer('rescan_interval', 0, 'Interval in seconds for background rescanning. 0 to disable.')
    # Mark as required only if this script is the entry point,
    # otherwise, tests or other modules might define/use them differently.
    if __name__ == "__main__":
        flags.mark_flag_as_required('storage_dir')
except flags.Error:
    pass # Flags are already defined

# Global variable to store media data and a lock for thread-safe access
MEDIA_DATA_CACHE = {}
MEDIA_DATA_LOCK = threading.Lock()

# Determine the absolute path to the project's root directory
# Assuming server.py is in media_server/ and web/ is in the parent of media_server/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WEB_DIR_ABSOLUTE = os.path.join(PROJECT_ROOT, 'web')


# Create Flask app instance, explicitly setting the static folder to our 'web' directory
# and static_url_path to ensure files are served from the root (e.g. /css/style.css)
app = Flask(__name__, static_folder=WEB_DIR_ABSOLUTE, static_url_path='')


def reset_media_data_cache():
    """Clears the global MEDIA_DATA_CACHE in a thread-safe manner."""
    with MEDIA_DATA_LOCK:
        MEDIA_DATA_CACHE.clear()
        logging.debug("MEDIA_DATA_CACHE has been reset.")

def background_scanner_task():
    """Periodically rescans the storage directory and updates the cache."""
    global MEDIA_DATA_CACHE
    # Ensure app context is available if needed for config, though here we use FLAGS directly
    # as it's initialized before this thread starts.
    if not FLAGS.storage_dir or FLAGS.rescan_interval <= 0:
        logging.error("Background scanner cannot start: storage_dir or rescan_interval not configured properly.")
        return

    logging.info(f"Background scanner started. Rescan interval: {FLAGS.rescan_interval} seconds for dir: {FLAGS.storage_dir}")
    while True:
        time.sleep(FLAGS.rescan_interval)
        logging.info("Background scanner performing rescan...")
        try:
            with MEDIA_DATA_LOCK: # Acquire lock before modifying cache
                updated_data = media_scanner.scan_directory(
                    FLAGS.storage_dir, # Use FLAGS.storage_dir as app.config might not be set in this thread
                    existing_data=MEDIA_DATA_CACHE,
                    rescan=True
                )
                MEDIA_DATA_CACHE = updated_data
            logging.info("Background rescan complete. Cache updated.")
        except Exception as e:
            logging.error(f"Error during background scan: {e}", exc_info=True)

@app.route('/')
def root():
    """Serves the main index.html page from the static folder."""
    # Flask, when static_folder is set, can serve files using send_static_file.
    # However, if static_url_path is '', it automatically tries to serve 'index.html'
    # from the static_folder when '/' is requested.
    # If not, or to be explicit:
    # return app.send_static_file('index.html')
    # For this setup, simply defining static_folder and static_url_path=''
    # and having an index.html in that folder is usually enough.
    # Let's be explicit to ensure it works as intended.
    return app.send_static_file('index.html')

@app.route('/list', methods=['GET'])
def list_media():
    """Handles GET requests for /list endpoint."""
    with MEDIA_DATA_LOCK:
        # Create a deep copy to avoid issues if the cache is updated while serializing/sending
        data_to_send = {k: v.copy() for k, v in MEDIA_DATA_CACHE.items()}
    logging.info(f"Served /list request")
    return jsonify(data_to_send)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/image/<path:filename>', methods=['PUT'])
def put_image(filename):
    """Handles PUT requests for /image/<filename> endpoint for image uploads."""
    if 'file' not in request.files:
        abort(400, description="No file part in the request.")

    file_from_request = request.files['file'] # Renamed to avoid conflict with 'file' module
    original_filename_unsafe = file_from_request.filename

    if original_filename_unsafe == '':
        abort(400, description="No selected file.")

    if not file_from_request or not allowed_file(original_filename_unsafe):
        abort(400, description=f"Invalid file type. Allowed types: {ALLOWED_EXTENSIONS}")

    # Use the filename from the URL path, but sanitize it.
    s_filename = secure_filename(filename)
    if not s_filename:
        s_filename = secure_filename(original_filename_unsafe)
        if not s_filename:
             s_filename = "unnamed_image" + os.path.splitext(original_filename_unsafe)[1].lower()


    file_contents = file_from_request.read()
    # file_from_request.seek(0) # Not strictly necessary if we don't read it again from the stream

    sha256_hash = hashlib.sha256(file_contents).hexdigest()

    with MEDIA_DATA_LOCK:
        if sha256_hash in MEDIA_DATA_CACHE:
            logging.info(f"Image with SHA256 {sha256_hash} (filename: {s_filename}) already exists. No-op.")
            cached_entry = MEDIA_DATA_CACHE[sha256_hash]
            return jsonify({
                "message": "Image content already exists.",
                "sha256": sha256_hash,
                "filename": cached_entry.get('filename'),
                "file_path": cached_entry.get('file_path')
            }), 200

        today_str = datetime.datetime.now().strftime('%Y%m%d')
        upload_subdir_rel = os.path.join("uploads", today_str) # e.g. uploads/20231027
        upload_dir_abs = os.path.join(app.config['STORAGE_DIR'], upload_subdir_rel)
        os.makedirs(upload_dir_abs, exist_ok=True)

        base, ext = os.path.splitext(s_filename)
        ext = ext.lower() # Ensure consistent extension casing
        if not ext: # if no extension from sanitized filename, try from original
            ext = os.path.splitext(original_filename_unsafe)[1].lower()

        counter = 0
        # Ensure base is not empty after splitext if s_filename was like ".jpg"
        if not base and ext:
            base = "image"

        final_filename_on_disk = f"{base}{ext}"
        prospective_path_on_disk = os.path.join(upload_dir_abs, final_filename_on_disk)

        while os.path.exists(prospective_path_on_disk):
            counter += 1
            final_filename_on_disk = f"{base}_{counter}{ext}"
            prospective_path_on_disk = os.path.join(upload_dir_abs, final_filename_on_disk)

        try:
            with open(prospective_path_on_disk, "wb") as f_save:
                f_save.write(file_contents)
            logging.info(f"Saved new image: {final_filename_on_disk} to {upload_subdir_rel} (SHA256: {sha256_hash})")
        except IOError as e:
            logging.error(f"Failed to save file {final_filename_on_disk} to {upload_dir_abs}: {e}")
            abort(500, description="Failed to save image.")

        thumbnail_file_name_only = None # Initialize
        thumbnail_dir_abs_path = app.config.get('THUMBNAIL_DIR')
        if not thumbnail_dir_abs_path:
            logging.error("Thumbnail directory not configured. Cannot generate thumbnail.")
        else:
            # Ensure thumbnail dir exists (media_scanner.scan_directory usually does this, but good practice here too)
            os.makedirs(thumbnail_dir_abs_path, exist_ok=True)

            thumbnail_path_generated = media_scanner.generate_thumbnail(
                prospective_path_on_disk, # Full path to the newly saved source image
                thumbnail_dir_abs_path,
                sha256_hash
            )
            if thumbnail_path_generated:
                 thumbnail_file_name_only = os.path.basename(thumbnail_path_generated)
            else:
                 logging.warning(f"Thumbnail generation failed for {prospective_path_on_disk}")

        relative_file_path_for_cache = os.path.join(upload_subdir_rel, final_filename_on_disk)

        creation_time = time.time()
        try:
            from PIL import Image as PILImage # Local import to avoid circular deps if moved
            from PIL import ExifTags

            img_pil = PILImage.open(prospective_path_on_disk)
            exif_data = img_pil.getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag == 'DateTimeOriginal':
                        dt_obj = datetime.datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
                        creation_time = dt_obj.timestamp()
                        break
        except Exception as e:
            logging.debug(f"Could not read EXIF data for {final_filename_on_disk}: {e}. Using current time as creation_date.")

        MEDIA_DATA_CACHE[sha256_hash] = {
            'filename': final_filename_on_disk,
            'original_filename': filename,
            'file_path': relative_file_path_for_cache,
            'last_modified': time.time(),
            'original_creation_date': creation_time,
            'thumbnail_file': thumbnail_file_name_only
        }
        logging.info(f"Cache updated for SHA256: {sha256_hash} with file {final_filename_on_disk}")

        return jsonify({
            "message": "Image uploaded successfully.",
            "sha256": sha256_hash,
            "filename": final_filename_on_disk,
            "file_path": relative_file_path_for_cache,
            "thumbnail_file": thumbnail_file_name_only
        }), 201

@app.route('/image/<string:sha256_hex>', methods=['GET'])
def get_image(sha256_hex):
    """Serves an image based on its SHA256 hash."""
    if not (len(sha256_hex) == 64 and all(c in '0123456789abcdefABCDEF' for c in sha256_hex)):
        logging.warning(f"Invalid SHA256 format requested for image: {sha256_hex}")
        abort(400, description="Invalid SHA256 format.")

    with MEDIA_DATA_LOCK:
        cached_data = MEDIA_DATA_CACHE.get(sha256_hex)

    if not cached_data:
        logging.info(f"Image SHA256 not found in cache: {sha256_hex}")
        abort(404, description="Image not found (SHA unknown).")

    file_path_relative = cached_data.get('file_path')
    if not file_path_relative:
        logging.error(f"Cache entry for SHA {sha256_hex} is missing 'file_path'. Cache data: {cached_data}")
        abort(500, description="Server error: Image metadata incomplete.")

    storage_dir_abs_path = app.config.get('STORAGE_DIR')
    if not storage_dir_abs_path:
        logging.error("STORAGE_DIR not configured in the application.")
        abort(500, description="Server configuration error.")

    # send_from_directory expects the directory and then the path *within* that directory.
    # file_path_relative is already like "uploads/YYYYMMDD/filename.jpg"
    # So, we pass STORAGE_DIR as the directory and file_path_relative as the filename to send.

    # For added security, ensure the resolved path is still within the storage directory
    # This check helps prevent potential directory traversal if file_path_relative was crafted maliciously
    # (though secure_filename and os.path.join should generally be safe).
    full_file_path = os.path.join(storage_dir_abs_path, file_path_relative)
    if not os.path.normpath(full_file_path).startswith(os.path.normpath(storage_dir_abs_path) + os.sep) and \
       not os.path.normpath(full_file_path) == os.path.normpath(storage_dir_abs_path): # check if it's the storage_dir itself
        logging.error(f"Potential directory traversal attempt for SHA {sha256_hex}. Path: {file_path_relative}")
        abort(400, description="Invalid file path.")

    from werkzeug.exceptions import NotFound # Import for specific exception handling
    try:
        logging.info(f"Attempting to serve image: {file_path_relative} from {storage_dir_abs_path} for SHA {sha256_hex}")
        return send_from_directory(storage_dir_abs_path, file_path_relative) # mimetype will be inferred
    except NotFound:
        logging.warning(f"Image file not found via send_from_directory: {file_path_relative} in {storage_dir_abs_path} (SHA: {sha256_hex})")
        # This could happen if cache is out of sync with filesystem
        abort(404, description="Image file not found on disk.")
    except Exception as e:
        logging.error(f"Unexpected error serving image {file_path_relative} (SHA: {sha256_hex}): {e}", exc_info=True)
        abort(500, description="Internal server error while serving image.")

@app.route('/image/sha256/<string:sha256_hex>', methods=['GET']) # New route
def get_image_by_sha256(sha256_hex):
    """Serves an image based on its SHA256 hash. Alias for /image/<sha256_hex> for clarity."""
    # This function will be very similar to get_image
    if not (len(sha256_hex) == 64 and all(c in '0123456789abcdefABCDEF' for c in sha256_hex)):
        logging.warning(f"Invalid SHA256 format requested for image: {sha256_hex}")
        abort(400, description="Invalid SHA256 format.")

    with MEDIA_DATA_LOCK:
        cached_data = MEDIA_DATA_CACHE.get(sha256_hex)

    if not cached_data:
        logging.info(f"Image SHA256 not found in cache: {sha256_hex}")
        abort(404, description="Image not found (SHA unknown).")

    file_path_relative = cached_data.get('file_path')
    if not file_path_relative:
        logging.error(f"Cache entry for SHA {sha256_hex} is missing 'file_path'. Cache data: {cached_data}")
        abort(500, description="Server error: Image metadata incomplete.")

    storage_dir_abs_path = app.config.get('STORAGE_DIR')
    if not storage_dir_abs_path:
        logging.error("STORAGE_DIR not configured in the application.")
        abort(500, description="Server configuration error.")

    full_file_path = os.path.join(storage_dir_abs_path, file_path_relative)
    # Security check: Ensure the path is within the storage directory
    if not os.path.normpath(full_file_path).startswith(os.path.normpath(storage_dir_abs_path) + os.sep) and \
       not os.path.normpath(full_file_path) == os.path.normpath(storage_dir_abs_path):
        logging.error(f"Potential directory traversal attempt for SHA {sha256_hex}. Path: {file_path_relative}")
        abort(400, description="Invalid file path.")

    from werkzeug.exceptions import NotFound # Import for specific exception handling
    try:
        logging.info(f"Attempting to serve image: {file_path_relative} from {storage_dir_abs_path} for SHA {sha256_hex} via /image/sha256/ endpoint")
        return send_from_directory(storage_dir_abs_path, file_path_relative)
    except NotFound:
        logging.warning(f"Image file not found via send_from_directory: {file_path_relative} in {storage_dir_abs_path} (SHA: {sha256_hex})")
        abort(404, description="Image file not found on disk.")
    except Exception as e:
        logging.error(f"Unexpected error serving image {file_path_relative} (SHA: {sha256_hex}): {e}", exc_info=True)
        abort(500, description="Internal server error while serving image.")

@app.route('/thumbnail/<string:sha256_hex>', methods=['GET'])
def get_thumbnail(sha256_hex):
    """Serves a thumbnail image if it exists."""
    # Validate sha256_hex format (64 hex characters)
    if not (len(sha256_hex) == 64 and all(c in '0123456789abcdefABCDEF' for c in sha256_hex)):
        logging.warning(f"Invalid SHA256 format requested: {sha256_hex}")
        abort(400, description="Invalid SHA256 format.")

    thumbnail_filename = f"{sha256_hex}{media_scanner.THUMBNAIL_EXTENSION}"
    thumbnail_dir_abs_path = app.config.get('THUMBNAIL_DIR')

    if not thumbnail_dir_abs_path:
        logging.error("Thumbnail directory not configured in the application.")
        abort(500, description="Server configuration error.")

    # Ensure the thumbnail directory itself exists, though send_from_directory handles file not found.
    # This check is more for sanity during development or if the dir should always exist.
    if not os.path.isdir(thumbnail_dir_abs_path):
        logging.warning(f"Thumbnail directory does not exist: {thumbnail_dir_abs_path}")
        # If the .thumbnails directory itself doesn't exist, no thumbnails can exist.
        abort(404, description="Thumbnail not found (directory missing).")

    # Import Werkzeug's NotFound exception
    from werkzeug.exceptions import NotFound

    try:
        logging.info(f"Attempting to serve thumbnail: {thumbnail_filename} from {thumbnail_dir_abs_path}")
        return send_from_directory(thumbnail_dir_abs_path, thumbnail_filename, mimetype='image/png')
    except NotFound: # Specifically catch Werkzeug's NotFound
        logging.info(f"Thumbnail not found via send_from_directory: {thumbnail_filename} in {thumbnail_dir_abs_path}")
        abort(404, description="Thumbnail not found.")
    except Exception as e: # Catch any other unexpected errors
        logging.error(f"Unexpected error serving thumbnail {thumbnail_filename}: {e}", exc_info=True)
        abort(500, description="Internal server error while serving thumbnail.")


def run_flask_app(argv):
    """Starts the Flask server after scanning the media directory."""
    # argv is parsed by absl.app.run automatically.
    global MEDIA_DATA_CACHE

    logging.set_verbosity(logging.INFO)

    if not FLAGS.storage_dir:
        logging.error("Storage directory not provided via --storage_dir flag.")
        sys.exit(1)

    app.config['STORAGE_DIR'] = FLAGS.storage_dir
    app.config['THUMBNAIL_DIR'] = os.path.join(FLAGS.storage_dir, media_scanner.THUMBNAIL_DIR_NAME)


    logging.info(f"Initial scan of storage directory: {app.config['STORAGE_DIR']}")
    # Initial scan populates the cache
    with MEDIA_DATA_LOCK:
        MEDIA_DATA_CACHE = media_scanner.scan_directory(app.config['STORAGE_DIR'], rescan=False)

    if not MEDIA_DATA_CACHE:
        logging.warning("Initial media scan resulted in no data. Server will start with an empty list.")

    if FLAGS.rescan_interval > 0:
        scanner_thread = threading.Thread(target=background_scanner_task, daemon=True)
        scanner_thread.start()
    else:
        logging.info("Background rescanning disabled (rescan_interval <= 0).")

    logging.info(f"Starting Flask HTTP server on port {FLAGS.port}...")
    # Setting use_reloader=False because it can cause issues with absl flags and background threads
    # For development, reloader is useful, but for this setup, it's safer to disable.
    # Debug mode should also be False for this setup unless specifically needed for Flask debugging.
    app.run(host='0.0.0.0', port=FLAGS.port, debug=False, use_reloader=False)

def main_flask():
    # absl.app.run will parse flags and then call run_flask_app
    absl_app.run(run_flask_app)

if __name__ == '__main__':
    main_flask()
