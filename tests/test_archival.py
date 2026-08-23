import os
import tempfile
import unittest
from unittest import mock
from media_server import archival
from media_server.settings import Settings


class TestArchival(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="archival_test_")
        self.sample_file = os.path.join(self.test_dir, "sample.jpg")
        with open(self.sample_file, "wb") as f:
            f.write(b"sample image bytes")

    def tearDown(self):
        if os.path.exists(self.sample_file):
            os.remove(self.sample_file)
        if os.path.exists(self.test_dir):
            os.rmdir(self.test_dir)

    def test_null_archival_provider(self):
        settings = Settings(archival_backend="Off")
        manager = archival.ArchivalManager(settings)
        self.assertFalse(manager.archive_media_file(self.sample_file, "hash123"))
        status = manager.test_status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["backend"], "Off")

    def test_mock_archival_provider(self):
        mock_provider = archival.MockArchivalProvider("my-test-bucket")
        self.assertTrue(
            mock_provider.upload_file(self.sample_file, "media/ha/hash123.jpg")
        )
        self.assertIn("media/ha/hash123.jpg", mock_provider.uploaded_files)
        res = mock_provider.test_connection()
        self.assertTrue(res.success)

    # --- S3 Provider Tests ---
    @mock.patch("time.sleep")
    def test_s3_upload_retry_and_success(self, mock_sleep):
        provider = archival.S3ArchivalProvider("test-bucket", max_retries=3)
        mock_client = mock.MagicMock()
        # Fail once, then succeed on second attempt
        mock_client.upload_file.side_effect = [Exception("Transient S3 error"), None]
        provider.client = mock_client

        result = provider.upload_file(self.sample_file, "media/ab/hash.jpg")
        self.assertTrue(result)
        self.assertEqual(mock_client.upload_file.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @mock.patch("time.sleep")
    def test_s3_upload_permanent_failure(self, mock_sleep):
        provider = archival.S3ArchivalProvider("test-bucket", max_retries=3)
        mock_client = mock.MagicMock()
        mock_client.upload_file.side_effect = Exception("Permanent connection error")
        provider.client = mock_client

        result = provider.upload_file(self.sample_file, "media/ab/hash.jpg")
        self.assertFalse(result)
        self.assertEqual(mock_client.upload_file.call_count, 3)

    def test_s3_test_connection_validation(self):
        # Empty bucket
        provider = archival.S3ArchivalProvider("")
        self.assertFalse(provider.test_connection().success)

        # Missing client
        provider_no_client = archival.S3ArchivalProvider("valid-bucket")
        provider_no_client.client = None
        self.assertFalse(provider_no_client.test_connection().success)

        # Successful connection
        provider = archival.S3ArchivalProvider("valid-bucket")
        mock_client = mock.MagicMock()
        provider.client = mock_client
        self.assertTrue(provider.test_connection().success)

        # Connection error
        mock_client.head_bucket.side_effect = Exception("403 Forbidden")
        res = provider.test_connection()
        self.assertFalse(res.success)
        self.assertIn("403 Forbidden", res.message)

    # --- GCS Provider Tests ---
    @mock.patch("time.sleep")
    def test_gcs_upload_retry_and_success(self, mock_sleep):
        provider = archival.GCSArchivalProvider("gcs-bucket", max_retries=3)
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.upload_from_filename.side_effect = [Exception("503 Service Unavailable"), None]
        mock_client.bucket.return_value.blob.return_value = mock_blob
        provider.client = mock_client

        result = provider.upload_file(self.sample_file, "media/ab/hash.jpg")
        self.assertTrue(result)
        self.assertEqual(mock_blob.upload_from_filename.call_count, 2)

    @mock.patch("time.sleep")
    def test_gcs_upload_permanent_failure(self, mock_sleep):
        provider = archival.GCSArchivalProvider("gcs-bucket", max_retries=3)
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.upload_from_filename.side_effect = Exception("Permanent GCS error")
        mock_client.bucket.return_value.blob.return_value = mock_blob
        provider.client = mock_client

        result = provider.upload_file(self.sample_file, "media/ab/hash.jpg")
        self.assertFalse(result)
        self.assertEqual(mock_blob.upload_from_filename.call_count, 3)

    def test_gcs_test_connection_validation(self):
        # Empty bucket
        provider = archival.GCSArchivalProvider("")
        self.assertFalse(provider.test_connection().success)

        # Missing client
        provider_no_client = archival.GCSArchivalProvider("gcs-bucket")
        provider_no_client.client = None
        self.assertFalse(provider_no_client.test_connection().success)

        # Successful connection
        provider = archival.GCSArchivalProvider("gcs-bucket")
        mock_client = mock.MagicMock()
        mock_client.get_bucket.return_value = mock.MagicMock(name="gcs-bucket")
        provider.client = mock_client
        self.assertTrue(provider.test_connection().success)

        # Connection error
        mock_client.get_bucket.side_effect = Exception("GCS Bucket not found")
        res = provider.test_connection()
        self.assertFalse(res.success)
        self.assertIn("GCS connection failed", res.message)

    # --- ArchivalManager Tests ---
    def test_archival_manager_key_generation_and_updates(self):
        settings = Settings(archival_backend="AWS", archival_bucket="test-bucket")
        mgr = archival.ArchivalManager(settings)
        mock_provider = mock.MagicMock()
        mgr.provider = mock_provider

        sha = "a1b2c3d4e5f6" + "0" * 52
        mgr.archive_media_file(self.sample_file, sha)
        mock_provider.upload_file.assert_called_once_with(
            self.sample_file,
            f"media/a1/{sha}.jpg"
        )

        # Switch settings dynamically
        new_settings = Settings(archival_backend="Google Cloud", archival_bucket="gcs-bucket")
        mgr.update_settings(new_settings)
        self.assertIsInstance(mgr.provider, archival.GCSArchivalProvider)


if __name__ == "__main__":
    unittest.main()

