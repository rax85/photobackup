# Media Server

[![Python application](https://github.com/rax85/photobackup/actions/workflows/python-app.yml/badge.svg)](https://github.com/rax85/photobackup/actions/workflows/python-app.yml)

A simple HTTP server that scans a specified directory for media files (images and videos)
and provides a JSON list of these files along with their SHA256 hash and last modified time.

## Installation

```bash
pip install .
# or for development
pip install -e .
pip install -r requirements-dev.txt # If you have dev specific requirements
```

## Usage

Run the server using the following command:

```bash
media-server --storage_dir /path/to/your/media --port 8080 --rescan_interval 300
```

-   `--storage_dir`: (Required) The directory containing media files to scan.
-   `--port`: (Optional) The port number for the server to listen on. Defaults to 8000.
-   `--rescan_interval`: (Optional) Interval in seconds for automatically rescanning the storage directory in the background. If 0 or not provided, background rescanning is disabled. For example, `--rescan_interval 300` will rescan every 5 minutes.

### API Endpoints

-   **GET /list**: Returns a JSON object mapping the SHA256 hash of each media file
    to its filename and last modified timestamp.

Example response:
```json
{
  "sha256_hash_1": {
    "filename": "image.jpg",
    "last_modified": 1678886400.0,
    "file_path": "/path/to/your/media/image.jpg"
  },
  "sha256_hash_2": {
    "filename": "video.mp4",
    "last_modified": 1678886401.0,
    "file_path": "/path/to/your/media/subdir/video.mp4"
  }
}
```
**Note:** The `"file_path"` field was added to the response objects.
