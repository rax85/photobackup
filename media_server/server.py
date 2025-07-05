import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from absl import app, flags, logging
import sys # Required for sys.exit in main if flags are not parsed

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
flags.mark_flag_as_required('storage_dir')

# Global variable to store media data so it's scanned only once on startup
MEDIA_DATA_CACHE = {}

class MediaRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for the media server."""

    def do_GET(self):
        """Handles GET requests."""
        if self.path == '/list':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            # MEDIA_DATA_CACHE is populated at server startup
            self.wfile.write(json.dumps(MEDIA_DATA_CACHE).encode('utf-8'))
            logging.info(f"Served /list request from {self.client_address[0]}")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Error 404: Not Found. Use /list endpoint.')
            logging.warning(f"Invalid path requested: {self.path} from {self.client_address[0]}")

def run_server(argv):
    """Starts the HTTP server after scanning the media directory."""
    # argv is parsed by absl.app.run automatically.
    # FLAGS.storage_dir and FLAGS.port are available here.

    logging.set_verbosity(logging.INFO) # Set logging level

    if not FLAGS.storage_dir: # Should be caught by mark_flag_as_required
        logging.error("Storage directory not provided.")
        sys.exit(1) # Exit if flag parsing somehow fails to catch this.

    logging.info(f"Initial scan of storage directory: {FLAGS.storage_dir}")
    global MEDIA_DATA_CACHE
    MEDIA_DATA_CACHE = media_scanner.scan_directory(FLAGS.storage_dir)
    if not MEDIA_DATA_CACHE:
        logging.warning("Media scan resulted in no data. Server will start with an empty list.")

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
