from __future__ import annotations
import abc
from dataclasses import dataclass
import os
import time
from typing import Any, Dict
from absl import logging
from media_server.settings import Settings


@dataclass
class ArchivalResult:
    """Represents the result of an archival operation or connection test."""
    success: bool
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {"success": self.success, "message": self.message}


# Backwards compatibility alias
Tuple_Result = ArchivalResult


class BaseArchivalProvider(abc.ABC):
    """Abstract base class for cloud archival providers."""

    @abc.abstractmethod
    def upload_file(self, local_path: str, remote_key: str) -> bool:
        """Uploads a local file to the remote archive."""
        pass

    @abc.abstractmethod
    def test_connection(self) -> ArchivalResult:
        """Tests connectivity to the remote bucket."""
        pass


class NullArchivalProvider(BaseArchivalProvider):
    """Null provider when archival is disabled ('Off')."""

    def upload_file(self, local_path: str, remote_key: str) -> bool:
        return False

    def test_connection(self) -> ArchivalResult:
        return ArchivalResult(True, "Archival backend is disabled.")


class S3ArchivalProvider(BaseArchivalProvider):
    """AWS S3 Archival Provider using boto3."""

    def __init__(self, bucket_name: str, max_retries: int = 3):
        self.bucket_name = bucket_name
        self.max_retries = max_retries
        self.client = None
        self._init_client()

    def _init_client(self):
        try:
            import boto3

            self.client = boto3.client("s3")
        except ImportError:
            logging.warning("boto3 is not installed; S3 archival is unavailable.")
            self.client = None

    def upload_file(self, local_path: str, remote_key: str) -> bool:
        if not self.client or not self.bucket_name:
            return False
        for attempt in range(self.max_retries):
            try:
                self.client.upload_file(local_path, self.bucket_name, remote_key)
                return True
            except Exception as e:
                logging.warning(
                    f"S3 upload attempt {attempt + 1}/{self.max_retries} failed for {local_path} -> {remote_key}: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                else:
                    logging.error(f"S3 upload permanently failed for {local_path} -> {remote_key}: {e}")
        return False

    def test_connection(self) -> ArchivalResult:
        if not self.bucket_name:
            return ArchivalResult(False, "S3 bucket name is not configured.")
        if not self.client:
            return ArchivalResult(False, "boto3 library is not installed.")
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            return ArchivalResult(
                True, f"Successfully connected to S3 bucket '{self.bucket_name}'."
            )
        except Exception as e:
            return ArchivalResult(False, f"S3 connection failed: {e}")


class GCSArchivalProvider(BaseArchivalProvider):
    """Google Cloud Storage Archival Provider."""

    def __init__(self, bucket_name: str, max_retries: int = 3):
        self.bucket_name = bucket_name
        self.max_retries = max_retries
        self.client = None
        self._init_client()

    def _init_client(self):
        try:
            from google.cloud import storage

            self.client = storage.Client()
        except ImportError:
            logging.warning(
                "google-cloud-storage not installed; GCS archival unavailable."
            )
            self.client = None

    def upload_file(self, local_path: str, remote_key: str) -> bool:
        if not self.client or not self.bucket_name:
            return False
        for attempt in range(self.max_retries):
            try:
                bucket = self.client.bucket(self.bucket_name)
                blob = bucket.blob(remote_key)
                blob.upload_from_filename(local_path)
                return True
            except Exception as e:
                logging.warning(
                    f"GCS upload attempt {attempt + 1}/{self.max_retries} failed for {local_path} -> {remote_key}: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                else:
                    logging.error(f"GCS upload permanently failed for {local_path} -> {remote_key}: {e}")
        return False

    def test_connection(self) -> ArchivalResult:
        if not self.bucket_name:
            return ArchivalResult(False, "GCS bucket name is not configured.")
        if not self.client:
            return ArchivalResult(False, "google-cloud-storage library is not installed.")
        try:
            bucket = self.client.get_bucket(self.bucket_name)
            return ArchivalResult(
                True, f"Successfully connected to GCS bucket '{bucket.name}'."
            )
        except Exception as e:
            return ArchivalResult(False, f"GCS connection failed: {e}")


class MockArchivalProvider(BaseArchivalProvider):
    """Mock provider for unit tests and offline testing."""

    def __init__(self, bucket_name: str = "mock-bucket"):
        self.bucket_name = bucket_name
        self.uploaded_files: Dict[str, str] = {}

    def upload_file(self, local_path: str, remote_key: str) -> bool:
        if os.path.exists(local_path):
            self.uploaded_files[remote_key] = local_path
            return True
        return False

    def test_connection(self) -> ArchivalResult:
        return ArchivalResult(True, f"Mock archival connected to '{self.bucket_name}'.")


class ArchivalManager:
    """Manages cloud archival configuration and uploads."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = self._create_provider()

    def _create_provider(self) -> BaseArchivalProvider:
        backend = self.settings.archival_backend
        bucket = self.settings.archival_bucket
        if backend == "AWS":
            return S3ArchivalProvider(bucket)
        elif backend == "Google Cloud":
            return GCSArchivalProvider(bucket)
        return NullArchivalProvider()

    def update_settings(self, settings: Settings) -> None:
        """Updates the provider when settings change."""
        self.settings = settings
        self.provider = self._create_provider()

    def archive_media_file(self, local_abs_path: str, sha256_hex: str) -> bool:
        """Archives a media file by its SHA256 key."""
        ext = os.path.splitext(local_abs_path)[1].lower()
        remote_key = f"media/{sha256_hex[:2]}/{sha256_hex}{ext}"
        return self.provider.upload_file(local_abs_path, remote_key)

    def test_status(self) -> Dict[str, Any]:
        """Returns connection test results and configuration summary."""
        test_res = self.provider.test_connection()
        return {
            "backend": self.settings.archival_backend,
            "bucket": self.settings.archival_bucket,
            "connected": test_res.success,
            "message": test_res.message,
        }
