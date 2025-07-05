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
    to its details. These details include:
    -   `filename`: The name of the file.
    -   `last_modified`: The last modification timestamp of the file (from the filesystem).
    -   `file_path`: The full path to the file.
    -   `original_creation_date`: The original creation timestamp of the media. For images, this is extracted from the EXIF 'DateTimeOriginal' tag if available. If EXIF data is not present or for other media types, this defaults to the file's creation time on the filesystem (ctime).

Example response:
```json
{
  "sha256_hash_1": {
    "filename": "image.jpg",
    "last_modified": 1678886400.0,
    "file_path": "/path/to/your/media/image.jpg",
    "original_creation_date": 1678880000.0
  },
  "sha256_hash_2": {
    "filename": "video.mp4",
    "last_modified": 1678886401.0,
    "file_path": "/path/to/your/media/subdir/video.mp4",
    "original_creation_date": 1678885000.0
  }
}
```
**Note:** The `"file_path"` and `"original_creation_date"` fields are included in the response objects. The `original_creation_date` will be derived from EXIF for images where possible.

-   **GET /thumbnail/<sha256_hex>**: Returns the thumbnail image (PNG) for the
    given SHA256 hash if it exists.
    -   `<sha256_hex>`: The SHA256 hash of the original media file. Must be 64 hexadecimal characters.
    -   **Success (200 OK)**: Returns the thumbnail image with `Content-Type: image/png`.
    -   **Not Found (404 Not Found)**: Returned if the SHA256 hash is unknown, if the corresponding media file does not have a thumbnail (e.g., it's a video or thumbnail generation failed), or if the thumbnail directory is missing.
    -   **Bad Request (400 Bad Request)**: Returned if the provided `<sha256_hex>` is not a valid SHA256 hash format.
