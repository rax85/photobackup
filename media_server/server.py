import json
import os
import sys
import threading
import time

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
except flags.FlagsError:
    pass # Flags are already defined

# Global variable to store media data and a lock for thread-safe access
MEDIA_DATA_CACHE = {}
MEDIA_DATA_LOCK = threading.Lock()

# Create Flask app instance
app = Flask(__name__)

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

@app.route('/list', methods=['GET'])
def list_media():
    """Handles GET requests for /list endpoint."""
    with MEDIA_DATA_LOCK:
        # Create a deep copy to avoid issues if the cache is updated while serializing/sending
        data_to_send = {k: v.copy() for k, v in MEDIA_DATA_CACHE.items()}
    logging.info(f"Served /list request")
    return jsonify(data_to_send)

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


@app.route('/image/<string:sha256_hex>', methods=['GET'])
def get_image(sha256_hex):
    """Serves an original image file if it exists."""
    # Validate sha256_hex format (64 hex characters)
    if not (len(sha256_hex) == 64 and all(c in '0123456789abcdefABCDEF' for c in sha256_hex)):
        logging.warning(f"Invalid SHA256 format requested for full image: {sha256_hex}")
        abort(400, description="Invalid SHA256 format.")

    storage_dir_abs_path = app.config.get('STORAGE_DIR')
    if not storage_dir_abs_path:
        logging.error("Storage directory not configured in the application.")
        abort(500, description="Server configuration error: Storage directory not set.")

    with MEDIA_DATA_LOCK:
        # Make a copy to prevent issues if the cache is updated while we are reading
        media_item = MEDIA_DATA_CACHE.get(sha256_hex, {}).copy()

    if not media_item or 'file_path' not in media_item:
        logging.info(f"Image SHA not found in cache: {sha256_hex}")
        abort(404, description="Image not found.")

    # file_path from cache is relative to storage_dir
    relative_file_path = media_item['file_path']

    # Basic path sanitization check: ensure the relative path doesn't try to escape.
    # os.path.normpath will collapse ".." and "." components.
    # If after normalization, the path starts with "..", it's an attempt to go above storage_dir.
    # This is an additional check, as send_from_directory should also prevent traversal.
    normalized_relative_path = os.path.normpath(relative_file_path)
    if normalized_relative_path.startswith("..") or os.path.isabs(normalized_relative_path):
        logging.error(f"Invalid file path detected for SHA {sha256_hex}: {relative_file_path} (normalized: {normalized_relative_path})")
        abort(400, description="Invalid file path.")

    # Import Werkzeug's NotFound exception
    from werkzeug.exceptions import NotFound

    try:
        # `send_from_directory` expects the directory and the filename separately.
        # The `relative_file_path` is relative to `storage_dir_abs_path`.
        # `send_from_directory` will join `storage_dir_abs_path` and `relative_file_path`.
        logging.info(f"Attempting to serve image: {relative_file_path} from {storage_dir_abs_path}")
        return send_from_directory(storage_dir_abs_path, normalized_relative_path)
    except NotFound:
        logging.info(f"Image file not found via send_from_directory: {normalized_relative_path} in {storage_dir_abs_path}")
        abort(404, description="Image file not found on disk.")
    except Exception as e:
        logging.error(f"Unexpected error serving image {normalized_relative_path}: {e}", exc_info=True)
        abort(500, description="Internal server error while serving image.")

def main_flask():
    # absl.app.run will parse flags and then call run_flask_app
    absl_app.run(run_flask_app)

if __name__ == '__main__':
    main_flask()
