import os
import hashlib
import mimetypes
from absl import logging
from typing import Dict, Optional

# Initialize mimetypes database
mimetypes.init()

def get_file_sha256(file_path: str) -> Optional[str]:
    """Computes the SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except IOError:
        logging.error(f"Could not read file for hashing: {file_path}")
        return None

def is_media_file(file_path: str) -> bool:
    """Checks if a file is an image or video based on its MIME type."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type.startswith('image/') or mime_type.startswith('video/')
    return False

def scan_directory(storage_dir: str,
                   existing_data: Optional[Dict[str, dict]] = None,
                   rescan: bool = False) -> Dict[str, dict]:
    """
    Scans a directory for media files and returns a dictionary with their
    SHA256 hash, filename, and last modified time.

    Args:
        storage_dir: The path to the directory to scan.
        existing_data: Optional. A dictionary of existing media file data to update.
                       If None, a full scan is performed.
        rescan: Optional. If True and existing_data is provided, performs a rescan
                checking for modifications and deletions.

    Returns:
        A dictionary where keys are SHA256 hashes and values are dicts
        containing 'filename', 'last_modified' timestamp, and 'file_path'.
    """
    if not os.path.isdir(storage_dir):
        logging.error(f"Storage directory not found: {storage_dir}")
        return {}

    current_media_data = {}
    if existing_data and rescan:
        logging.info(f"Rescanning directory: {storage_dir}")
        current_media_data = existing_data.copy() # Start with a copy of existing data

        # Check for modifications and deletions
        shas_to_remove = []
        for sha256_hex, data in current_media_data.items():
            file_path = data.get('file_path') # Assumes file_path is stored
            if not file_path or not os.path.isfile(file_path):
                logging.info(f"File {data.get('filename', 'unknown')} (SHA: {sha256_hex}) no longer exists or path is missing. Removing.")
                shas_to_remove.append(sha256_hex)
                continue

            try:
                current_last_modified = os.path.getmtime(file_path)
                if current_last_modified != data['last_modified']:
                    logging.info(f"File {data['filename']} has been modified. Re-hashing.")
                    new_sha256_hex = get_file_sha256(file_path)
                    if new_sha256_hex and new_sha256_hex != sha256_hex:
                        # SHA changed, means content changed. Remove old, new one will be added.
                        shas_to_remove.append(sha256_hex)
                        logging.debug(f"SHA changed for {data['filename']}. Old SHA: {sha256_hex}, New SHA: {new_sha256_hex}")
                        # The new entry will be added during the walk phase
                    elif new_sha256_hex == sha256_hex:
                        # Content is same (SHA same) but mtime changed. Just update mtime.
                        current_media_data[sha256_hex]['last_modified'] = current_last_modified
                        logging.debug(f"Timestamp updated for {data['filename']} (SHA: {sha256_hex})")
                    elif not new_sha256_hex: # Error hashing
                        shas_to_remove.append(sha256_hex) # Remove if hashing failed
            except OSError as e:
                logging.error(f"Could not get metadata for file {file_path} during rescan: {e}")
                shas_to_remove.append(sha256_hex) # Remove if metadata access fails

        for sha in shas_to_remove:
            del current_media_data[sha]

        # Create a set of known file paths for quick lookup
        known_file_paths = {data['file_path'] for data in current_media_data.values() if 'file_path' in data}

    else: # Full scan or initial scan
        logging.info(f"Performing full scan of directory: {storage_dir}")
        known_file_paths = set() # No known files yet

    # Walk the directory for new files or files not in existing_data (if rescanning)
    for root, _, files in os.walk(storage_dir):
        for filename in files:
            file_path = os.path.join(root, filename)

            if not os.path.isfile(file_path):
                logging.debug(f"Skipping non-file item: {file_path}")
                continue

            if file_path in known_file_paths and rescan: # Already processed and checked if rescanning
                continue

            if is_media_file(file_path):
                logging.debug(f"Processing media file: {file_path}")
                sha256_hex = get_file_sha256(file_path)
                if sha256_hex:
                    # If rescan=True, this will add new files.
                    # If rescan=False (initial scan), this adds all files.
                    # If a file was modified and its SHA changed, the old entry was removed,
                    # and this block will add the new entry.
                    if sha256_hex not in current_media_data or \
                       current_media_data[sha256_hex].get('file_path') != file_path: # Handle hash collisions or different paths
                        try:
                            last_modified = os.path.getmtime(file_path)
                            current_media_data[sha256_hex] = {
                                'filename': filename,
                                'last_modified': last_modified,
                                'file_path': file_path  # Store full path
                            }
                            logging.debug(f"Added/Updated map for: {filename} (SHA256: {sha256_hex}) at path {file_path}")
                        except OSError as e:
                            logging.error(f"Could not get metadata for new/updated file {file_path}: {e}")
            else:
                logging.debug(f"Skipping non-media file: {file_path}")

    if rescan:
        logging.info(f"Rescan complete. Found {len(current_media_data)} media files.")
    else:
        logging.info(f"Initial scan complete. Found {len(current_media_data)} media files.")
    return current_media_data

if __name__ == '__main__':
    # Example Usage (for testing purposes)
    # Create a dummy directory and files
    if not os.path.exists("dummy_storage"):
        os.makedirs("dummy_storage/subdir")

    with open("dummy_storage/image.jpg", "w") as f: f.write("dummy image content")
    with open("dummy_storage/video.mp4", "w") as f: f.write("dummy video content")
    with open("dummy_storage/text.txt", "w") as f: f.write("dummy text content")
    with open("dummy_storage/subdir/another_image.png", "w") as f: f.write("another dummy image")

    # Configure absl logging for standalone script execution
    from absl import app
    from absl import flags
    FLAGS = flags.FLAGS
    # Define a dummy flag to satisfy absl.app.run
    try:
        flags.DEFINE_string('script_runner_flag', '', 'A dummy flag.')
    except flags.FlagsError:
        pass # Flag already defined

    def main(argv):
        del argv # Unused.
        logging.set_verbosity(logging.DEBUG)
        scanned_data = scan_directory("dummy_storage")
        print("Scanned Media Files:")
        for sha, data in scanned_data.items():
            print(f"  SHA256: {sha}, Filename: {data['filename']}, Last Modified: {data['last_modified']}")

        # Clean up dummy files and directory
        os.remove("dummy_storage/image.jpg")
        os.remove("dummy_storage/video.mp4")
        os.remove("dummy_storage/text.txt")
        os.remove("dummy_storage/subdir/another_image.png")
        os.rmdir("dummy_storage/subdir")
        os.rmdir("dummy_storage")

    app.run(main)
