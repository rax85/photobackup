import os
import hashlib
import mimetypes
from absl import logging

# Initialize mimetypes database
mimetypes.init()

def get_file_sha256(file_path):
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

def is_media_file(file_path):
    """Checks if a file is an image or video based on its MIME type."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type.startswith('image/') or mime_type.startswith('video/')
    return False

def scan_directory(storage_dir: str) -> dict:
    """
    Scans a directory for media files and returns a dictionary with their
    SHA256 hash, filename, and last modified time.

    Args:
        storage_dir: The path to the directory to scan.

    Returns:
        A dictionary where keys are SHA256 hashes and values are dicts
        containing 'filename' and 'last_modified' timestamp.
    """
    if not os.path.isdir(storage_dir):
        logging.error(f"Storage directory not found: {storage_dir}")
        return {}

    media_files_data = {}
    logging.info(f"Scanning directory: {storage_dir}")

    for root, _, files in os.walk(storage_dir):
        for filename in files:
            file_path = os.path.join(root, filename)

            if not os.path.isfile(file_path): # Skip if not a file (e.g. broken symlink)
                logging.debug(f"Skipping non-file item: {file_path}")
                continue

            if is_media_file(file_path):
                logging.debug(f"Processing media file: {file_path}")
                sha256_hex = get_file_sha256(file_path)
                if sha256_hex:
                    try:
                        last_modified = os.path.getmtime(file_path)
                        media_files_data[sha256_hex] = {
                            'filename': filename,
                            'last_modified': last_modified
                        }
                        logging.debug(f"Added to map: {filename} (SHA256: {sha256_hex})")
                    except OSError as e:
                        logging.error(f"Could not get metadata for file {file_path}: {e}")
            else:
                logging.debug(f"Skipping non-media file: {file_path}")

    logging.info(f"Scan complete. Found {len(media_files_data)} media files.")
    return media_files_data

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
