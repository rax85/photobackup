import http.server
import socketserver
import json
from absl import app, flags, logging
from rest_server.lib import file_scanner

FLAGS = flags.FLAGS
flags.DEFINE_string("storage_dir", "/tmp/storage", "Directory to scan for files.")
flags.DEFINE_integer("port", 8080, "Port to run the HTTP server on.")

file_map = {}

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/list':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(file_map).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

def run_server(port, storage_dir):
    global file_map
    logging.info(f"Scanning directory: {storage_dir}")
    file_map = file_scanner.scan_directory(storage_dir)
    logging.info(f"Found {sum(len(files) for files in file_map.values())} files.")

    with socketserver.TCPServer(("", port), Handler) as httpd:
        logging.info(f"Serving at port {port}")
        httpd.serve_forever()

def main(argv):
    del argv  # Unused.
    run_server(FLAGS.port, FLAGS.storage_dir)

def main_wrapper():
    """Wrapper for setuptools entry point."""
    app.run(main)

if __name__ == '__main__':
    main_wrapper()
