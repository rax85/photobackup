# PhotoBackup · Media Server & Photo Gallery

[![Python application](https://github.com/rax85/photobackup/actions/workflows/python-app.yml/badge.svg)](https://github.com/rax85/photobackup/actions/workflows/python-app.yml)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A high-performance self-hosted media server and modern photo gallery application. It scans a storage directory for photos and videos, extracts rich EXIF timestamps, reverse-geocodes GPS coordinates offline, classifies content with optional AI vision models, generates thumbnails, and serves an interactive Single Page Application (SPA) frontend with Dark & Light theme support.

---

## Features

* **High-Performance Scanning**: Fast directory traversal, SHA-256 deduplication, and parallel thumbnail generation using Pillow with HEIC/HEIF and video badge support.
* **Offline Reverse Geocoding**: Automatically maps photo GPS coordinates to the nearest city and country using an offline dataset and Haversine calculations.
* **Optional AI Vision Tagging**: Categorizes images with pre-trained vision models (ResNet50V2 / MobileNetV3) lazily loaded on demand.
* **Smart Omni-Search**: Instant search across filenames, cities, countries, tags, and dates without rigid syntax constraints.
* **Cloud Archival Support**: Modular cloud backup integration for AWS S3 and Google Cloud Storage.
* **State-of-the-Art SPA Frontend**:
  * Dark & Light theme modes with automatic system preference detection.
  * Responsive masonry/justified media gallery with zoom hover micro-interactions.
  * PhotoSwipe v5 lightbox with full-screen zoom and HTML5 video playback with Range streaming.
  * Sticky timeline sidebar with live Scrollspy highlighting active months.
  * Drag-and-drop batch upload dock with real-time file progress and toast notifications.

---

## Setup and Running

### Prerequisites
* Python 3.10+
* pip

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd photobackup
   ```

2. Install dependencies:
   ```bash
   pip install -e .
   ```
   *For optional AI vision tagging and cloud archival:*
   ```bash
   pip install -e ".[ml,cloud]"
   ```

### Running the Server

Start the server pointing to your media library:
```bash
python media_server/server.py --storage_dir=/path/to/your/media --port=8000
```

**Command-line arguments:**
* `--storage_dir`: (Required) Path to directory containing photos and videos.
* `--port`: (Optional) Port number for server (default `8000`).
* `--db_name`: (Optional) SQLite cache filename inside storage directory (default `media_cache.sqlite3`).

Open `http://localhost:8000` in your web browser.

---

## API Specification

### `GET /`
Serves the web application (`index.html`).

### `GET /list`
Retrieves all cached media items ordered by creation date descending.
* **Query Parameters**: `limit` (int, optional), `offset` (int, optional)
* **Response**: JSON dictionary mapping SHA-256 hashes to item metadata:
  ```json
  {
    "sha256_hash": {
      "filename": "photo.jpg",
      "original_filename": "IMG_0001.jpg",
      "file_path": "photos/photo.jpg",
      "last_modified": 1678886400.0,
      "original_creation_date": 1678880000.0,
      "thumbnail_file": "ab/sha256_hash.png",
      "width": 1920,
      "height": 1080,
      "latitude": 34.0522,
      "longitude": -118.2437,
      "city": "Los Angeles",
      "country": "United States",
      "mime_type": "image/jpeg",
      "filesize": 2048500,
      "tags": "[\"cat\", \"tabby\"]"
    }
  }
  ```

### `GET /api/search`
Smart multi-field search and faceted filtering.
* **Query Parameters**: `q` (string), `type` (`image` | `video` | `all`), `limit` (int), `offset` (int)
* **Response**: Filtered JSON media dictionary.

### `GET /api/stats`
Returns total items count, photo/video breakdown, storage size, date span, and location metrics.

### `POST /api/scan`
Triggers an immediate background rescan of the storage directory.

### `GET /list/date/<date_str>`
Retrieves media files for a specific date (`YYYY-MM-DD`).

### `GET /list/daterange/<start_date>/<end_date>`
Retrieves media files within a date range (`YYYY-MM-DD`).

### `GET /list/location/<city>[/<country>]`
Retrieves media files for a city and optional country.

### `PUT /image/<path:filename>`
Uploads a new media file (`multipart/form-data` with `file` part). Saves to `uploads/YYYYMMDD/<filename>`.

### `GET /image/<sha256_hex>`
Serves original media binary with HTTP `Range` streaming support (for videos and high-res images).

### `GET /thumbnail/<sha256_hex>`
Serves proportional 256x256 PNG thumbnail.

### `GET /api/settings` & `PUT /api/settings`
Retrieves or updates application settings (`rescan_interval`, `tagging_model`, `archival_backend`, `archival_bucket`).

### `POST /api/archival/test`
Tests connectivity to configured cloud archival bucket.

---

## Running Tests

Run the full automated test suite with pytest:
```bash
pytest -v
```

Run code style and lint checks:
```bash
flake8 media_server tests
```
