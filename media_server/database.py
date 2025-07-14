import sqlite3
import os
import threading
from typing import Dict, Optional, List, Any, Tuple
from absl import logging

DATABASE_NAME = "media_cache.sqlite3"
# Use a thread-local storage for database connections
thread_local = threading.local()

def get_db_path(storage_dir: Optional[str] = None) -> str:
    """Gets the absolute path to the database file."""
    if not storage_dir:
        # This is a fallback, ideally storage_dir is always provided
        # from the application's configuration.
        # Trying to infer from a common location if not provided.
        # This might need adjustment based on how server.py sets it up.
        if hasattr(thread_local, 'db_path_for_current_thread') and thread_local.db_path_for_current_thread: # Check specific attribute
            return thread_local.db_path_for_current_thread
        logging.warning("storage_dir not provided to get_db_path, trying to use current dir for DB.")
        # Fallback to a generic name if no storage_dir and no thread-local path available
        # This situation should be rare in a configured application
        return os.path.join(os.getcwd(), DATABASE_NAME)

    # If storage_dir is provided, always use it to construct the path
    return os.path.join(storage_dir, DATABASE_NAME)


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Gets a database connection for the current thread."""
    # Check if the current thread already has a connection, and if it's for the same db_path
    if not hasattr(thread_local, 'connection') or \
       not hasattr(thread_local, 'db_path_for_current_thread') or \
       thread_local.db_path_for_current_thread != db_path:

        logging.info(f"Creating new SQLite connection for thread {threading.get_ident()} to {db_path}")
        # Ensure the directory for the database exists before connecting
        db_dir = os.path.dirname(db_path)
        if db_dir: # Check if db_dir is not empty (i.e., not just a filename in current dir)
             os.makedirs(db_dir, exist_ok=True)

        # Using check_same_thread=False can be risky if connections are shared across threads
        # without external serialization. However, thread_local aims to give each thread its own connection.
        # If using a true connection pool, check_same_thread might be False, but pool handles safety.
        # For direct thread_local usage, check_same_thread=True is safer if each thread strictly owns its conn.
        # Let's assume for now that db_utils is the sole manager of these thread-local conns.
        # If a conn object from thread_local is passed to another thread, issues can occur.
        # Sticking to `check_same_thread=False` as per original plan, but with caution.
        thread_local.connection = sqlite3.connect(db_path, check_same_thread=False)
        thread_local.connection.row_factory = sqlite3.Row # Access columns by name
        thread_local.db_path_for_current_thread = db_path # Store the path for which this connection was made
    return thread_local.connection

def close_db_connection() -> None:
    """Closes the database connection for the current thread, if it exists."""
    if hasattr(thread_local, 'connection'):
        logging.info(f"Closing SQLite connection for thread {threading.get_ident()} from {getattr(thread_local, 'db_path_for_current_thread', 'N/A')}")
        thread_local.connection.close()
        del thread_local.connection
        if hasattr(thread_local, 'db_path_for_current_thread'):
            del thread_local.db_path_for_current_thread

def init_db(storage_dir: str) -> None:
    """Initializes the database and creates the media table if it doesn't exist."""
    # This function will be called by the main thread typically at startup.
    # It should establish its own connection, perform setup, and close it.
    # It should not rely on a pre-existing flask_g or shared thread_local connection from elsewhere
    # for its setup task, as it might run before any requests or other threads have started.

    db_path = get_db_path(storage_dir) # Use storage_dir to get the correct path

    # Ensure the directory for the database exists
    db_dir = os.path.dirname(db_path)
    if db_dir: # If db_path includes a directory part
        os.makedirs(db_dir, exist_ok=True)

    # Use a temporary connection for init, not necessarily the thread_local one,
    # or ensure thread_local is correctly setup for the main thread here.
    # For simplicity, let's use a direct connection for this setup task.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS media_files (
                    sha256_hex TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    original_filename TEXT,
                    file_path TEXT NOT NULL UNIQUE,
                    last_modified REAL NOT NULL,
                    original_creation_date REAL,
                    thumbnail_file TEXT,
                    width INTEGER,
                    height INTEGER,
                    latitude REAL,
                    longitude REAL,
                    city TEXT,
                    country TEXT,
                    mime_type TEXT,
                    filesize INTEGER
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON media_files (file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_last_modified ON media_files (last_modified)")
            logging.info(f"Database initialized and media_files table ensured at {db_path}")
    except sqlite3.Error as e:
        logging.error(f"Error initializing database at {db_path}: {e}")
        raise
    finally:
        conn.close()


def add_or_update_media_file(db_path: str, media_data: Dict[str, Any]) -> None:
    conn = get_db_connection(db_path)
    required_fields = ['sha256_hex', 'filename', 'file_path', 'last_modified']
    for field in required_fields:
        if field not in media_data or media_data[field] is None:
            logging.error(f"Required field {field} missing or None in media_data for add_or_update. Data: {media_data}")
            raise ValueError(f"Required field {field} missing or None in media_data")
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sha256_hex FROM media_files WHERE file_path = ? AND sha256_hex != ?",
                           (media_data['file_path'], media_data['sha256_hex']))
            existing_sha_for_path = cursor.fetchone()
            if existing_sha_for_path:
                logging.warning(f"File path {media_data['file_path']} was previously associated with SHA {existing_sha_for_path[0]}. Deleting old entry.")
                conn.execute("DELETE FROM media_files WHERE sha256_hex = ?", (existing_sha_for_path[0],))
            columns = [
                'sha256_hex', 'filename', 'original_filename', 'file_path',
                'last_modified', 'original_creation_date', 'thumbnail_file',
                'width', 'height', 'latitude', 'longitude', 'city', 'country',
                'mime_type', 'filesize'
            ]
            values = [media_data.get(col) for col in columns]
            sql = f"INSERT OR REPLACE INTO media_files ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"
            conn.execute(sql, values)
    except sqlite3.IntegrityError as e:
        logging.error(f"Integrity error adding/updating media file {media_data.get('file_path')} (SHA: {media_data.get('sha256_hex')}): {e}")
        raise
    except sqlite3.Error as e:
        logging.error(f"Database error adding/updating media file {media_data.get('file_path')}: {e}")
        raise

def get_media_file_by_sha(db_path: str, sha256_hex: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media_files WHERE sha256_hex = ?", (sha256_hex,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving media file by SHA {sha256_hex}: {e}")
        return None

def get_media_file_by_path(db_path: str, file_path: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media_files WHERE file_path = ?", (file_path,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving media file by path {file_path}: {e}")
        return None

def get_all_media_files(db_path: str) -> Dict[str, Dict[str, Any]]:
    conn = get_db_connection(db_path)
    media_dict = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media_files ORDER BY original_creation_date DESC, filename ASC")
        for row in cursor.fetchall():
            media_dict[row['sha256_hex']] = dict(row)
        return media_dict
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving all media files: {e}")
        return {}

def get_all_file_paths_and_last_modified(db_path: str) -> Dict[str, float]:
    conn = get_db_connection(db_path)
    paths = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, last_modified FROM media_files")
        for row in cursor.fetchall():
            paths[row['file_path']] = row['last_modified']
        return paths
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving file paths and last modified times: {e}")
        return {}

def delete_media_file_by_sha(db_path: str, sha256_hex: str) -> bool:
    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM media_files WHERE sha256_hex = ?", (sha256_hex,))
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"Database error deleting media file by SHA {sha256_hex}: {e}")
        return False

def delete_media_file_by_path(db_path: str, file_path: str) -> bool:
    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM media_files WHERE file_path = ?", (file_path,))
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"Database error deleting media file by path {file_path}: {e}")
        return False

def get_file_last_modified(db_path: str, file_path: str) -> Optional[float]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT last_modified FROM media_files WHERE file_path = ?", (file_path,))
        row = cursor.fetchone()
        return row['last_modified'] if row else None
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving last_modified for path {file_path}: {e}")
        return None

def get_all_db_file_paths(db_path: str) -> List[str]:
    conn = get_db_connection(db_path)
    paths = []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM media_files")
        for row in cursor.fetchall():
            paths.append(row['file_path'])
        return paths
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving all file paths: {e}")
        return []

def get_all_shas_and_thumbnails(db_path: str) -> Dict[str, Optional[str]]:
    conn = get_db_connection(db_path)
    shas_and_thumbnails = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT sha256_hex, thumbnail_file FROM media_files")
        for row in cursor.fetchall():
            shas_and_thumbnails[row['sha256_hex']] = row['thumbnail_file']
        return shas_and_thumbnails
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving SHAs and thumbnail paths: {e}")
        return {}

def update_media_file_fields(db_path: str, sha256_hex: str, fields_to_update: Dict[str, Any]) -> bool:
    if not fields_to_update:
        return False
    conn = get_db_connection(db_path)
    valid_columns = [
        'filename', 'original_filename', 'file_path', 'last_modified',
        'original_creation_date', 'thumbnail_file', 'width', 'height',
        'latitude', 'longitude', 'city', 'country', 'mime_type', 'filesize'
    ]
    update_clauses = []
    update_values = []
    for col, val in fields_to_update.items():
        if col in valid_columns:
            update_clauses.append(f"{col} = ?")
            update_values.append(val)
    if not update_clauses:
        return False
    update_values.append(sha256_hex)
    sql = f"UPDATE media_files SET {', '.join(update_clauses)} WHERE sha256_hex = ?"
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(update_values))
            return cursor.rowcount > 0 or (cursor.execute("SELECT 1 FROM media_files WHERE sha256_hex = ?", (sha256_hex,)).fetchone() is not None)
    except sqlite3.Error as e:
        logging.error(f"Database error updating fields for SHA {sha256_hex}: {e}")
        return False

def get_all_shas_in_db(db_path: str) -> List[str]:
    conn = get_db_connection(db_path)
    shas = []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT sha256_hex FROM media_files")
        for row in cursor.fetchall():
            shas.append(row['sha256_hex'])
        return shas
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving all SHAs: {e}")
        return []
