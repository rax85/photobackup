## Agent Instructions for `rest-file-server`

This document provides guidance for AI agents working on the `rest-file-server` codebase.

### Project Overview

The project is a Python-based HTTP REST server that:
1.  Scans a specified directory (via the `--storage_dir` flag).
2.  Identifies file types using `python-magic` (which relies on `libmagic`).
3.  Calculates the SHA256 hash for each **media file (image/* or video/* MIME types)** found.
4.  Exposes a `/list` API endpoint that returns a JSON mapping of SHA256 hashes to lists of media file paths that share that hash.
5.  Uses `absl-py` for command-line flags, application entry point, and logging.
6.  Uses the standard library `http.server` for the web server component.

### Key Components

-   **`setup.py`**: Standard Python packaging script.
    -   Lists `python-magic` as a dependency.
    -   The entry point `rest-file-server` is defined here, pointing to `rest_server.main:main_wrapper`.
-   **`rest_server/main.py`**:
    -   Contains the `absl` flag definitions (`FLAGS.storage_dir`, `FLAGS.port`).
    -   Implements the `Handler` class (subclass of `http.server.SimpleHTTPRequestHandler`) to serve the `/list` API.
    -   `run_server()` function: Initializes the file scan and starts the HTTP server.
    -   `main()`: The main application logic called by `app.run()`.
    -   `main_wrapper()`: The wrapper function used by the `setuptools` console script.
    -   A global variable `file_map` stores the results of the directory scan. This is populated when `run_server` starts.
-   **`rest_server/lib/file_scanner.py`**:
    -   `get_mime_type(filepath)`: Uses `python-magic` to determine and return the MIME type of a file.
    -   `scan_directory(directory)`: Recursively scans the given directory. For each file, it determines the MIME type. If the type is `image/*` or `video/*`, it calculates its SHA256 hash and adds it to the result dictionary.
    -   `calculate_sha256(filepath)`: Calculates and returns the hex digest of a file's SHA256 hash.
-   **`tests/`**:
    -   `test_file_scanner.py`: Unit tests for `file_scanner.py`.
        -   Uses `tempfile` module to create temporary files.
        -   Includes tests with various file types (actual images like PNG/GIF, text files, binary data) to ensure correct filtering based on MIME types.
        -   Verifies that `get_mime_type` works as expected.
    -   `test_server.py`: Unit tests for the HTTP server.
        -   Starts the server in a separate thread for testing.
        -   Uses the `requests` library to make HTTP calls to the test server.
        -   **Important for `absl` flags in tests**: `FLAGS([sys.argv[0]])` is used in `setUpClass` to initialize `absl` flags correctly.

### Development Workflow

1.  **Making Changes**:
    -   If modifying core hashing, file scanning, or MIME type logic, update `rest_server/lib/file_scanner.py` and its tests in `tests/test_file_scanner.py`.
    -   If modifying server behavior, API endpoints, or flag handling, update `rest_server/main.py` and its tests in `tests/test_server.py`.
2.  **Running Tests**:
    -   Always run tests after making changes:
        ```bash
        python -m unittest discover -s tests
        ```
    -   Ensure all tests pass.
3.  **Dependencies**:
    -   Core dependencies: `absl-py`, `python-magic`.
    -   System dependencies: `libmagic` (usually installed via system package manager, e.g., `apt-get install libmagic1` on Debian/Ubuntu).
    -   Test dependencies: `requests`.
    -   These are listed in `setup.py`. If adding new dependencies, update `setup.py`.

### Coding Conventions & Best Practices

-   Follow PEP 8 Python style guidelines.
-   Use `absl.logging` for any log messages.
-   Ensure new functionality is covered by unit tests. Specifically, test MIME type detection and filtering.
-   When creating test files for MIME type detection, ensure they have the correct magic bytes for `libmagic` to identify them. Small, valid file headers are preferred over empty files with extensions.

### Potential Pitfalls

-   **`libmagic` Availability**: `python-magic` is a wrapper around the `libmagic` C library. If `libmagic` is not installed or not found by `python-magic`, MIME type detection will fail. Ensure `libmagic1` (or equivalent) is installed in the environment.
-   **MIME Type Variations**: `libmagic`'s MIME type strings can sometimes vary slightly (e.g., `image/png` vs `image/x-png`). Tests should account for common variations if necessary.
-   **Flag Parsing in Tests**: `absl` flags need `FLAGS([sys.argv[0]])` in `test_server.py`'s `setUpClass`.

By following these guidelines, you can contribute effectively to the `rest-file-server` project.
