# Media Server

[![Python application](https://github.com/rax85/photobackup/actions/workflows/python-app.yml/badge.svg)](https://github.com/rax85/photobackup/actions/workflows/python-app.yml)

A simple web-based media server application that scans a directory for images,
provides an API to list and view them, and allows new image uploads. It features
a responsive web interface for browsing and viewing media.

## Features

*   Scans a specified directory for media files (images).
*   Generates thumbnails for images.
*   Provides an HTTP API to list media and serve image files and thumbnails.
*   Allows image uploads via the API.
*   Responsive web frontend for browsing the media gallery.
*   Background rescanning of the media directory (optional).

## Setup and Running

### Prerequisites
*   Python 3.x
*   pip

### Installation

1.  Clone the repository:
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```
2.  Install dependencies:
    ```bash
    pip install .
    ```
    For development, you might prefer:
    ```bash
    pip install -e .
    # If you have development-specific requirements:
    # pip install -r requirements-dev.txt
    ```

### Running the Server

Execute the server script from the root of the project:

```bash
python media_server/server.py --storage_dir=/path/to/your/media --port=8000 [--rescan_interval=300]
```

**Command-line arguments:**

*   `--storage_dir`: (Required) The directory containing media files to scan.
*   `--port`: (Optional) The port number for the server to listen on. Defaults to `8000`.
*   `--rescan_interval`: (Optional) Interval in seconds for automatically rescanning the storage directory in the background. If `0` or not provided, background rescanning is disabled. For example, `--rescan_interval 300` will rescan every 5 minutes.

Once the server is running, you can access the web interface by navigating to `http://localhost:<port>` in your web browser (e.g., `http://localhost:8000`).

## API Specification

The server exposes the following HTTP API endpoints:

### `GET /`
*   **Description:** Serves the main web application (`index.html`).
*   **Request:** None.
*   **Success Response:**
    *   `200 OK`
    *   Body: HTML content of the web application.

### `GET /list`
*   **Description:** Retrieves metadata for all media items currently in the server's cache.
*   **Request:** None.
*   **Success Response:**
    *   `200 OK`
    *   Body (JSON): An object where keys are SHA256 hashes of media items, and values are objects containing their metadata:
        *   `filename`: (string) Current filename on disk.
        *   `original_filename`: (string) Original filename at the time of first scan or upload.
        *   `file_path`: (string) Relative path to the media file from the `storage_dir`.
        *   `last_modified`: (float) Unix timestamp of the file's last modification time.
        *   `original_creation_date`: (float) Unix timestamp of the media's original creation (from EXIF if available, otherwise file system creation time).
        *   `thumbnail_file`: (string, optional) Relative path to the thumbnail within the thumbnail directory (e.g., `.thumbnails/ab/hash.png`). Null if no thumbnail (e.g., for videos or if generation failed).
        *   `width`: (integer, optional) Width of the image in pixels. Null for non-image types or if not determined.
        *   `height`: (integer, optional) Height of the image in pixels. Null for non-image types or if not determined.
        *   `latitude`: (float, optional) GPS latitude in decimal degrees, if available from EXIF. Null otherwise.
        *   `longitude`: (float, optional) GPS longitude in decimal degrees (negative for West/South), if available from EXIF. Null otherwise.
        *   `city`: (string, optional) City name derived from GPS coordinates. Null if not available.
        *   `country`: (string, optional) Country name derived from GPS coordinates. Null if not available.
        ```json
        {
          "sha256_hash_1": {
            "filename": "image.jpg",
            "original_filename": "original_image_name.jpg",
            "file_path": "relative/path/to/image.jpg",
            "last_modified": 1678886400.0,
            "original_creation_date": 1678880000.0,
            "thumbnail_file": "ab/abcdef123.png",
            "width": 1920,
            "height": 1080,
            "latitude": 34.0522,
            "longitude": -118.2437,
            "city": "Los Angeles",
            "country": "United States"
          },
          "another_sha_hash": {
            "filename": "photo_without_gps.png",
            "original_filename": "photo_without_gps.png",
            "file_path": "subdir/photo_without_gps.png",
            "last_modified": 1678890000.0,
            "original_creation_date": 1678881000.0,
            "thumbnail_file": "cd/anotherhash.png",
            "width": 800,
            "height": 600,
            "latitude": null,
            "longitude": null,
            "city": null,
            "country": null
          }
          // ... more items
        }
        ```

### `GET /list/date/<date_str>`
*   **Description:** Retrieves media items for a specific date.
*   **Request:**
    *   Path Parameter: `<date_str>` in `YYYY-MM-DD` format.
*   **Success Response:**
    *   `200 OK`
    *   Body (JSON): Same format as `GET /list`.
*   **Error Responses:**
    *   `400 Bad Request`: "Invalid date format. Please use YYYY-MM-DD."

### `GET /list/daterange/<start_date_str>/<end_date_str>`
*   **Description:** Retrieves media items within a date range.
*   **Request:**
    *   Path Parameters: `<start_date_str>` and `<end_date_str>` in `YYYY-MM-DD` format.
*   **Success Response:**
    *   `200 OK`
    *   Body (JSON): Same format as `GET /list`.
*   **Error Responses:**
    *   `400 Bad Request`: "Invalid date format. Please use YYYY-MM-DD." or "Start date must be before end date."

### `GET /list/location/<city>` and `GET /list/location/<city>/<country>`
*   **Description:** Retrieves media items for a specific location.
*   **Request:**
    *   Path Parameters: `<city>` and optional `<country>`.
*   **Success Response:**
    *   `200 OK`
    *   Body (JSON): Same format as `GET /list`.

### `PUT /image/<path:filename>`
*   **Description:** Uploads a new image file. The `<filename>` in the URL path is a suggestion for the stored filename (it will be sanitized).
*   **Request:**
    *   Method: `PUT`
    *   Path Parameter: `<filename>` (e.g., `my_photo.jpg`)
    *   Body: `multipart/form-data` with a single file part named `file`.
        *   Example using `curl`: `curl -X PUT -F "file=@/path/to/local/image.jpg" http://localhost:8000/image/my_photo.jpg`
*   **Success Response (201 Created - New image uploaded):**
    *   `201 Created`
    *   Body (JSON): Metadata of the successfully uploaded image.
        ```json
        {
          "message": "Image uploaded successfully.",
          "sha256": "sha256_hash_of_uploaded_image",
          "filename": "stored_filename.jpg", // Actual filename on disk after sanitization/deduplication
          "file_path": "uploads/YYYYMMDD/stored_filename.jpg", // Relative to storage_dir
          "thumbnail_file": "ab/sha256_hash.png", // Relative path within thumbnail_dir
          "width": 1920, // Width of the uploaded image
          "height": 1080 // Height of the uploaded image
        }
        ```
*   **Success Response (200 OK - Image content already exists):**
    *   `200 OK`
    *   Body (JSON): Metadata of the existing image if the uploaded content matches a known SHA256 hash.
        ```json
        {
          "message": "Image content already exists.",
          "sha256": "sha256_hash_of_existing_image",
          "filename": "existing_filename.jpg",
          "file_path": "path/to/existing_filename.jpg"
          // May also include width, height, thumbnail_file if available in cache for existing item
        }
        ```
*   **Error Responses:**
    *   `400 Bad Request`: If no `file` part in request, no file selected, invalid file type (allowed: 'png', 'jpg', 'jpeg', 'gif'), or invalid file path. Response body is JSON: `{"error": "Error description"}`.
    *   `500 Internal Server Error`: If there's an issue saving the file or a server configuration error. Response body is JSON: `{"error": "Error description"}`.

### `GET /image/<string:sha256_hex>`
*   **Description:** Serves the original image file based on its SHA256 hash.
*   **Request:**
    *   Path Parameter: `<sha256_hex>` (64-character hexadecimal string).
*   **Success Response:**
    *   `200 OK`
    *   Body: Binary image data with appropriate `Content-Type` (e.g., `image/jpeg`, `image/png`).
*   **Error Responses:**
    *   `400 Bad Request`: "Invalid SHA256 format." (JSON body with `{"error": "description"}`)
    *   `404 Not Found`: If image SHA or corresponding file not found. (JSON body with `{"error": "description"}`)
    *   `500 Internal Server Error`: Server configuration or metadata issues. (JSON body with `{"error": "description"}`)

### `GET /image/sha256/<string:sha256_hex>`
*   **Description:** Alias for `GET /image/<string:sha256_hex>`. Serves an image based on its SHA256 hash.
*   **Details:** Same request, success, and error responses as `GET /image/<string:sha256_hex>`.

### `GET /thumbnail/<string:sha256_hex>`
*   **Description:** Serves a generated thumbnail (PNG format) for the image specified by its SHA256 hash.
*   **Request:**
    *   Path Parameter: `<sha256_hex>` (64-character hexadecimal string).
*   **Success Response:**
    *   `200 OK`
    *   Body: PNG image data (`Content-Type: image/png`).
*   **Error Responses:**
    *   `400 Bad Request`: "Invalid SHA256 format." (JSON body with `{"error": "description"}`)
    *   `404 Not Found`: If thumbnail not found (e.g., SHA unknown, original is not an image, or thumbnail generation failed). (JSON body with `{"error": "description"}`)
    *   `500 Internal Server Error`: Server configuration issues (e.g., thumbnail directory not configured). (JSON body with `{"error": "description"}`)

## Web Frontend

The application includes a responsive web frontend for browsing and interacting with the media. It is served from the `web/` directory relative to the project root.

**Key Files:**
*   `web/index.html`: The main HTML file that structures the single-page application.
*   `web/css/style.css`: Contains all custom styles for the application's appearance and layout.
*   `web/js/main.js`: Core client-side JavaScript that handles API interactions, dynamic content rendering, and user interface logic.
*   `web/photoswipe.css`, `web/js/photoswipe-lightbox.esm.js`, `web/js/photoswipe.esm.js`: Files for the PhotoSwipeJs image lightbox library.

**Features:**

*   **Gallery View:**
    *   Displays media items as thumbnails in a responsive grid that adjusts to screen size.
    *   Images are grouped chronologically by month and year of their original creation date, with clear visual dividers.
    *   Thumbnail images are lazy-loaded to improve initial page load performance.
*   **Image Lightbox:**
    *   Utilizes PhotoSwipeJs to provide a rich, full-screen image viewing experience.
    *   Supports touch gestures for navigation on mobile devices, keyboard controls on desktop, and pinch/scroll zooming.
*   **Date Navigation:**
    *   A dedicated navigation panel allows users to quickly jump to specific months/years within the gallery.
    *   On desktop views, this panel is a sticky sidebar.
    *   On mobile views, it transforms into a collapsible off-canvas drawer, accessible via a toggle button in the header. The drawer also includes its own close button.
*   **Responsive Design:**
    *   The entire interface is designed to be responsive, providing an optimal viewing experience on desktops, tablets, and mobile phones.
*   **Image Upload:**
    *   A Floating Action Button (FAB) is persistently displayed in the bottom-right corner, allowing users to easily initiate image uploads.
    *   A modal dialog shows the progress of file uploads.
    *   The gallery view automatically refreshes to include newly uploaded images upon successful completion.
*   **Search:**
    *   A search box in the header allows filtering the gallery.
    *   Supported queries: `date: YYYY-MM-DD`, `between: YYYY-MM-DD, YYYY-MM-DD`, and `location: city`.
    *   A reset button clears the search and restores the full gallery view.

**Technologies Used (Frontend):**
*   HTML5
*   CSS3 (including Flexbox and Grid for layout)
*   JavaScript (ES Modules)
*   PhotoSwipeJs (for image lightbox)

(Any other existing sections like License, Contributing, etc., would ideally be preserved if they were below the API section in the old README or if they are standard project sections)
