import datetime
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional
from absl import logging

DATABASE_NAME = "media_cache.sqlite3"
thread_local = threading.local()


def get_db_path(storage_dir: Optional[str] = None) -> str:
    """
    Constructs the absolute path to the SQLite database file.

    Args:
        storage_dir: The directory where the database file is stored.

    Returns:
        The absolute path to the database file.
    """
    if not storage_dir:
        if (
            hasattr(thread_local, "db_path_for_current_thread")
            and thread_local.db_path_for_current_thread
        ):
            return thread_local.db_path_for_current_thread
        return os.path.join(os.getcwd(), DATABASE_NAME)

    return os.path.join(storage_dir, DATABASE_NAME)


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """
    Establishes and returns a database connection for the current thread.

    Args:
        db_path: The absolute path to the database file.

    Returns:
        A sqlite3.Connection object for the current thread.
    """
    if (
        not hasattr(thread_local, "connection")
        or not hasattr(thread_local, "db_path_for_current_thread")
        or thread_local.db_path_for_current_thread != db_path
    ):
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        thread_local.connection = sqlite3.connect(db_path, check_same_thread=False)
        thread_local.connection.row_factory = sqlite3.Row
        thread_local.db_path_for_current_thread = db_path
        try:
            thread_local.connection.execute("PRAGMA journal_mode = WAL")
            thread_local.connection.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error:
            pass

    return thread_local.connection


def close_db_connection() -> None:
    """Closes the database connection for the current thread."""
    if hasattr(thread_local, "connection"):
        try:
            thread_local.connection.close()
        except sqlite3.Error:
            pass
        del thread_local.connection
        if hasattr(thread_local, "db_path_for_current_thread"):
            del thread_local.db_path_for_current_thread


def init_db(storage_dir: str) -> None:
    """
    Initializes the database by creating tables and performance indexes.

    Args:
        storage_dir: The directory where the database file will be created.
    """
    db_path = get_db_path(storage_dir)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
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
                    filesize INTEGER,
                    tags TEXT,
                    tagging_model TEXT
                )
            """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_path ON media_files (file_path)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_last_modified ON media_files (last_modified)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_creation_date ON media_files (original_creation_date)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_location ON media_files (city, country)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_mime_type ON media_files (mime_type)"
            )
            logging.info(f"Database schema and indexes ensured at {db_path}")
    except sqlite3.Error as e:
        logging.error(f"Error initializing database at {db_path}: {e}")
        raise
    finally:
        conn.close()


def add_or_update_media_file(db_path: str, media_data: Dict[str, Any]) -> None:
    """
    Adds a new media file record or updates an existing one.

    Args:
        db_path: The path to the database file.
        media_data: A dictionary containing the media file's metadata.
    """
    conn = get_db_connection(db_path)
    required_fields = ["sha256_hex", "filename", "file_path", "last_modified"]
    for field in required_fields:
        if field not in media_data or media_data[field] is None:
            raise ValueError(f"Required field {field} missing or None in media_data")

    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sha256_hex FROM media_files WHERE file_path = ? AND sha256_hex != ?",
                (media_data["file_path"], media_data["sha256_hex"]),
            )
            existing_sha_for_path = cursor.fetchone()
            if existing_sha_for_path:
                logging.warning(
                    f"File path {media_data['file_path']} associated with new SHA. Deleting old {existing_sha_for_path[0]}"
                )
                conn.execute(
                    "DELETE FROM media_files WHERE sha256_hex = ?",
                    (existing_sha_for_path[0],),
                )

            columns = [
                "sha256_hex",
                "filename",
                "original_filename",
                "file_path",
                "last_modified",
                "original_creation_date",
                "thumbnail_file",
                "width",
                "height",
                "latitude",
                "longitude",
                "city",
                "country",
                "mime_type",
                "filesize",
                "tags",
                "tagging_model",
            ]
            values = [media_data.get(col) for col in columns]
            sql = (
                f"INSERT OR REPLACE INTO media_files ({', '.join(columns)}) "
                f"VALUES ({', '.join(['?'] * len(columns))})"
            )
            conn.execute(sql, values)
    except sqlite3.Error as e:
        logging.error(
            f"Database error adding/updating media file {media_data.get('file_path')}: {e}"
        )
        raise


def get_media_file_by_sha(db_path: str, sha256_hex: str) -> Optional[Dict[str, Any]]:
    """Retrieves a media file record by SHA256 hash."""
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
    """Retrieves a media file record by relative path."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media_files WHERE file_path = ?", (file_path,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving media file by path {file_path}: {e}")
        return None


def get_all_media_files(
    db_path: str, limit: Optional[int] = None, offset: Optional[int] = None
) -> Dict[str, Dict[str, Any]]:
    """Retrieves media file records ordered by creation date descending."""
    conn = get_db_connection(db_path)
    media_dict = {}
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM media_files ORDER BY original_creation_date DESC, filename ASC"
        params: List[Any] = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
            if offset is not None:
                query += " OFFSET ?"
                params.append(offset)

        cursor.execute(query, tuple(params))
        for row in cursor.fetchall():
            media_dict[row["sha256_hex"]] = dict(row)
        return media_dict
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving all media files: {e}")
        return {}


def get_all_file_paths_and_last_modified(db_path: str) -> Dict[str, float]:
    """Retrieves all file paths and their last modified timestamps."""
    conn = get_db_connection(db_path)
    paths = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, last_modified FROM media_files")
        for row in cursor.fetchall():
            paths[row["file_path"]] = row["last_modified"]
        return paths
    except sqlite3.Error as e:
        logging.error(
            f"Database error retrieving file paths and last modified times: {e}"
        )
        return {}


def delete_media_file_by_sha(db_path: str, sha256_hex: str) -> bool:
    """Deletes a media file record by its SHA256 hash."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM media_files WHERE sha256_hex = ?", (sha256_hex,)
            )
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"Database error deleting media file by SHA {sha256_hex}: {e}")
        return False


def delete_media_file_by_path(db_path: str, file_path: str) -> bool:
    """Deletes a media file record by relative path."""
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
    """Retrieves the last modified timestamp for a specific file path."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_modified FROM media_files WHERE file_path = ?", (file_path,)
        )
        row = cursor.fetchone()
        return row["last_modified"] if row else None
    except sqlite3.Error as e:
        logging.error(
            f"Database error retrieving last_modified for path {file_path}: {e}"
        )
        return None


def get_all_db_file_paths(db_path: str) -> List[str]:
    """Retrieves all relative file paths in database."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM media_files")
        return [row["file_path"] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving all file paths: {e}")
        return []


def get_all_shas_and_thumbnails(db_path: str) -> Dict[str, Optional[str]]:
    """Retrieves all SHA256 hashes and their thumbnail paths."""
    conn = get_db_connection(db_path)
    shas_and_thumbnails = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT sha256_hex, thumbnail_file FROM media_files")
        for row in cursor.fetchall():
            shas_and_thumbnails[row["sha256_hex"]] = row["thumbnail_file"]
        return shas_and_thumbnails
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving SHAs and thumbnail paths: {e}")
        return {}


def update_media_file_fields(
    db_path: str, sha256_hex: str, fields_to_update: Dict[str, Any]
) -> bool:
    """Updates specific fields for a media record."""
    if not fields_to_update:
        return False
    conn = get_db_connection(db_path)
    valid_columns = [
        "filename",
        "original_filename",
        "file_path",
        "last_modified",
        "original_creation_date",
        "thumbnail_file",
        "width",
        "height",
        "latitude",
        "longitude",
        "city",
        "country",
        "mime_type",
        "filesize",
        "tags",
        "tagging_model",
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
            return cursor.rowcount > 0 or (
                cursor.execute(
                    "SELECT 1 FROM media_files WHERE sha256_hex = ?", (sha256_hex,)
                ).fetchone()
                is not None
            )
    except sqlite3.Error as e:
        logging.error(f"Database error updating fields for SHA {sha256_hex}: {e}")
        return False


def get_all_shas_in_db(db_path: str) -> List[str]:
    """Retrieves all SHA256 hashes in database."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT sha256_hex FROM media_files")
        return [row["sha256_hex"] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving all SHAs: {e}")
        return []


def get_media_files_by_date(db_path: str, date: float) -> Dict[str, Dict[str, Any]]:
    """Retrieves media files created on a specific date using indexed day ranges."""
    conn = get_db_connection(db_path)
    media_dict = {}
    try:
        dt = datetime.datetime.fromtimestamp(date, tz=datetime.timezone.utc)
        start_of_day = datetime.datetime(
            dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=datetime.timezone.utc
        ).timestamp()
        end_of_day = datetime.datetime(
            dt.year, dt.month, dt.day, 23, 59, 59, 999999, tzinfo=datetime.timezone.utc
        ).timestamp()

        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM media_files WHERE original_creation_date BETWEEN ? AND ? ORDER BY original_creation_date DESC",
            (start_of_day, end_of_day),
        )
        for row in cursor.fetchall():
            media_dict[row["sha256_hex"]] = dict(row)
        return media_dict
    except Exception as e:
        logging.error(f"Database error retrieving media files by date: {e}")
        return {}


def get_media_files_by_date_range(
    db_path: str, start_date: float, end_date: float
) -> Dict[str, Dict[str, Any]]:
    """Retrieves media files within a date range (inclusive)."""
    conn = get_db_connection(db_path)
    media_dict = {}
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM media_files WHERE original_creation_date BETWEEN ? AND ? ORDER BY original_creation_date DESC",
            (start_date, end_date),
        )
        for row in cursor.fetchall():
            media_dict[row["sha256_hex"]] = dict(row)
        return media_dict
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving media files by date range: {e}")
        return {}


def get_media_files_by_location(
    db_path: str, city: str, country: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """Retrieves media files matching city and optional country."""
    conn = get_db_connection(db_path)
    media_dict = {}
    try:
        cursor = conn.cursor()
        if country:
            cursor.execute(
                "SELECT * FROM media_files WHERE LOWER(city) = LOWER(?) AND LOWER(country) = LOWER(?) "
                "ORDER BY original_creation_date DESC",
                (city.strip(), country.strip()),
            )
        else:
            cursor.execute(
                "SELECT * FROM media_files WHERE LOWER(city) = LOWER(?) ORDER BY original_creation_date DESC",
                (city.strip(),),
            )
        for row in cursor.fetchall():
            media_dict[row["sha256_hex"]] = dict(row)
        return media_dict
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving media files by location: {e}")
        return {}


def search_media_files(
    db_path: str,
    query: str,
    media_type: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """Performs smart multi-field search across filename, city, country, and tags."""
    conn = get_db_connection(db_path)
    media_dict = {}
    query = query.strip()
    if not query and not media_type:
        return get_all_media_files(db_path, limit=limit, offset=offset)

    sql_conditions = []
    params: List[Any] = []

    if query:
        tokens = query.split()
        for token in tokens:
            pattern = f"%{token}%"
            sql_conditions.append(
                "(filename LIKE ? OR original_filename LIKE ? OR city LIKE ? OR country LIKE ? OR tags LIKE ?)"
            )
            params.extend([pattern, pattern, pattern, pattern, pattern])

    if media_type:
        if media_type == "image":
            sql_conditions.append("mime_type LIKE 'image/%'")
        elif media_type == "video":
            sql_conditions.append("mime_type LIKE 'video/%'")

    where_clause = " AND ".join(sql_conditions) if sql_conditions else "1=1"
    sql = f"SELECT * FROM media_files WHERE {where_clause} ORDER BY original_creation_date DESC"

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
        if offset is not None:
            sql += " OFFSET ?"
            params.append(offset)

    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        for row in cursor.fetchall():
            media_dict[row["sha256_hex"]] = dict(row)
        return media_dict
    except sqlite3.Error as e:
        logging.error(f"Database error searching media files: {e}")
        return {}


def get_database_stats(db_path: str) -> Dict[str, Any]:
    """Retrieves high-level library statistics."""
    conn = get_db_connection(db_path)
    stats: Dict[str, Any] = {
        "total_count": 0,
        "image_count": 0,
        "video_count": 0,
        "total_size_bytes": 0,
        "earliest_date": None,
        "latest_date": None,
        "cities_count": 0,
        "countries_count": 0,
    }
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                COUNT(*) as total_count,
                SUM(CASE WHEN mime_type LIKE 'image/%' THEN 1 ELSE 0 END) as image_count,
                SUM(CASE WHEN mime_type LIKE 'video/%' THEN 1 ELSE 0 END) as video_count,
                COALESCE(SUM(filesize), 0) as total_size,
                MIN(original_creation_date) as earliest_date,
                MAX(original_creation_date) as latest_date,
                COUNT(DISTINCT city) as cities_count,
                COUNT(DISTINCT country) as countries_count
            FROM media_files
        """
        )
        row = cursor.fetchone()
        if row:
            stats["total_count"] = row["total_count"] or 0
            stats["image_count"] = row["image_count"] or 0
            stats["video_count"] = row["video_count"] or 0
            stats["total_size_bytes"] = row["total_size"] or 0
            stats["earliest_date"] = row["earliest_date"]
            stats["latest_date"] = row["latest_date"]
            stats["cities_count"] = row["cities_count"] or 0
            stats["countries_count"] = row["countries_count"] or 0
    except sqlite3.Error as e:
        logging.error(f"Database error getting statistics: {e}")
    return stats
