import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from absl import app, flags, logging
import sys # Required for sys.exit in main if flags are not parsed
import threading
import time

# Correctly import from the same package
try:
    from . import media_scanner # Relative import for when run as part of the package
except ImportError:
    # Fallback for direct script execution (e.g. `python media_server/server.py`)
    # This assumes media_scanner.py is in the same directory.
    import media_scanner


FLAGS = flags.FLAGS

flags.DEFINE_string('storage_dir', None, 'Directory to scan for media files.')
flags.DEFINE_integer('port', 8000, 'Port for the HTTP server.')
flags.DEFINE_integer('rescan_interval', 0, 'Interval in seconds for background rescanning. 0 to disable.')
flags.mark_flag_as_required('storage_dir')

# Global variable to store media data and a lock for thread-safe access
MEDIA_DATA_CACHE = {}
MEDIA_DATA_LOCK = threading.Lock()

class MediaRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for the media server."""

    def do_GET(self):
        """Handles GET requests."""
        if self.path == '/list':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            with MEDIA_DATA_LOCK:
                # Create a deep copy to avoid issues if the cache is updated while serializing/sending
                data_to_send = {k: v.copy() for k, v in MEDIA_DATA_CACHE.items()}
            self.wfile.write(json.dumps(data_to_send).encode('utf-8'))
            logging.info(f"Served /list request from {self.client_address[0]}")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Error 404: Not Found. Use /list endpoint.')
            logging.warning(f"Invalid path requested: {self.path} from {self.client_address[0]}")

def background_scanner():
    """Periodically rescans the storage directory and updates the cache."""
    global MEDIA_DATA_CACHE
    logging.info(f"Background scanner started. Rescan interval: {FLAGS.rescan_interval} seconds.")
    while True:
        time.sleep(FLAGS.rescan_interval)
        logging.info("Background scanner performing rescan...")
        try:
            with MEDIA_DATA_LOCK: # Acquire lock before modifying cache
                # Pass the current cache to scan_directory for an update
                updated_data = media_scanner.scan_directory(
                    FLAGS.storage_dir,
                    existing_data=MEDIA_DATA_CACHE,
                    rescan=True
                )
                MEDIA_DATA_CACHE = updated_data
            logging.info("Background rescan complete. Cache updated.")
        except Exception as e:
            logging.error(f"Error during background scan: {e}", exc_info=True)


def run_server(argv):
    """Starts the HTTP server after scanning the media directory."""
    # argv is parsed by absl.app.run automatically.
    global MEDIA_DATA_CACHE

    logging.set_verbosity(logging.INFO) # Set logging level

    if not FLAGS.storage_dir: # Should be caught by mark_flag_as_required
        logging.error("Storage directory not provided.")
        sys.exit(1) # Exit if flag parsing somehow fails to catch this.

    logging.info(f"Initial scan of storage directory: {FLAGS.storage_dir}")
    # Initial scan populates the cache directly, no lock needed yet as no other threads access it.
    MEDIA_DATA_CACHE = media_scanner.scan_directory(FLAGS.storage_dir, rescan=False)
    if not MEDIA_DATA_CACHE:
        logging.warning("Initial media scan resulted in no data. Server will start with an empty list.")

    if FLAGS.rescan_interval > 0:
        scanner_thread = threading.Thread(target=background_scanner, daemon=True)
        scanner_thread.start()
    else:
        logging.info("Background rescanning disabled (rescan_interval <= 0).")

    server_address = ('', FLAGS.port)
    httpd = HTTPServer(server_address, MediaRequestHandler)

    logging.info(f"Starting HTTP server on port {FLAGS.port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Server is shutting down.")
        httpd.server_close()

def main():
    # absl.app.run will parse flags and then call run_server
    # It expects a function that takes one argument (sys.argv)
    app.run(run_server)

if __name__ == '__main__':
    main()
