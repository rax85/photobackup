# REST File Server

A simple HTTP REST server that scans a specified storage directory, computes SHA256 hashes for all files, and provides an API endpoint to list these hashes along with the corresponding file paths.

## Features

-   Scans a directory recursively.
-   Calculates SHA256 hash for each file.
-   Groups files by their content hash (useful for identifying duplicates).
-   Provides a `/list` API endpoint to return the mapping as JSON.
-   Configurable storage directory and port via command-line flags.
-   Built with `absl-py` for application startup and flag management.
-   Packagable as a pip module.

## Prerequisites

-   Python 3.7+
-   pip

## Installation

1.  **Clone the repository (if applicable):**
    ```bash
    # git clone <repository_url>
    # cd <repository_directory>
    ```

2.  **Install the package:**

    For development (editable install):
    ```bash
    pip install -e .
    ```

    For a standard install:
    ```bash
    pip install .
    ```
    This will also install dependencies like `absl-py`.

## Usage

Once installed, the server can be run using the `rest-file-server` command.

```bash
rest-file-server --storage_dir=/path/to/your/files --port=8080
```

**Command-line Flags:**

-   `--storage_dir`: (Required) The directory that the server should scan for files.
    -   Default: `/tmp/storage`
-   `--port`: The port on which the server should listen.
    -   Default: `8080`
-   `--help`: Show help message.

**Example:**

To serve files from a directory named `my_documents` on port `8888`:
```bash
mkdir -p /tmp/my_documents
echo "file1 content" > /tmp/my_documents/fileA.txt
echo "file2 content" > /tmp/my_documents/fileB.txt

rest-file-server --storage_dir=/tmp/my_documents --port=8888
```

The server will start, scan the directory, and log that it's serving on the specified port.

## API Endpoints

### `/list`

-   **Method:** `GET`
-   **Description:** Returns a JSON object mapping content SHA256 hashes to a list of file paths that have that hash.
-   **Example Response:**
    ```json
    {
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855": [
        "/tmp/my_documents/empty_file.txt"
      ],
      "a14a1fd212205059063870757c276127386efa4857fc713f3000696f7ed9b817": [
        "/tmp/my_documents/fileA.txt"
      ],
      "06a2017352d74c599906a023381a1885594154b1555509710389502842483402": [
        "/tmp/my_documents/fileB.txt
      ]
    }
    ```

**Accessing the API:**

If the server is running on `localhost:8888`, you can access the list API at `http://localhost:8888/list` using a web browser or a tool like `curl`:
```bash
curl http://localhost:8888/list
```

## Development

### Running Tests

To run the unit tests:

1.  Ensure you have the development dependencies installed (e.g., `requests` for server tests, though `pip install .[test]` or similar isn't configured in `setup.py` yet, `pip install -e .` should get `requests` if it's in `install_requires`).
2.  Navigate to the root project directory.
3.  Run the tests:
    ```bash
    python -m unittest discover -s tests
    ```

### Project Structure

```
.
├── rest_server/
│   ├── __init__.py
│   ├── main.py         # Main application, HTTP server, flags
│   └── lib/
│       ├── __init__.py
│       └── file_scanner.py # Core file scanning and hashing logic
├── tests/
│   ├── __init__.py
│   ├── test_file_scanner.py
│   └── test_server.py
├── setup.py            # Packaging script
└── README.md           # This file
```

## License

This project is licensed under the MIT License - see the `LICENSE` file for details (though a `LICENSE` file hasn't been added yet). You should add one if distributing.
