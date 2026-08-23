import json
import os
import unittest
from media_server.settings import Settings, SettingsManager


class TestSettingsManager(unittest.TestCase):
    def setUp(self):
        self.test_file = "test_settings.json"

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_read_default_settings(self):
        manager = SettingsManager(self.test_file)
        settings = manager.get()
        self.assertEqual(settings, Settings())

    def test_write_and_read_settings(self):
        manager = SettingsManager(self.test_file)
        new_settings = Settings(
            rescan_interval=1200,
            tagging_model="Resnet",
            archival_backend="AWS",
            archival_bucket="my-bucket",
        )
        manager.write_settings(new_settings)

        # Verify in-memory copy is updated
        self.assertEqual(manager.get(), new_settings)

        # Verify file is updated
        with open(self.test_file, "r") as f:
            data = json.load(f)
        self.assertEqual(
            data,
            {
                "rescan_interval": 1200,
                "tagging_model": "Resnet",
                "archival_backend": "AWS",
                "archival_bucket": "my-bucket",
            },
        )

        # Verify reading from file works correctly
        new_manager = SettingsManager(self.test_file)
        self.assertEqual(new_manager.get(), new_settings)

    def test_create_file_if_not_exists(self):
        self.assertFalse(os.path.exists(self.test_file))
        manager = SettingsManager(self.test_file)
        manager.write_settings(Settings())
        self.assertTrue(os.path.exists(self.test_file))

    # --- Settings.validate() Validation Checks ---
    def test_validate_negative_rescan_interval_raises(self):
        with self.assertRaises(ValueError):
            Settings(rescan_interval=-1).validate()

    def test_validate_invalid_tagging_model_raises(self):
        with self.assertRaises(ValueError):
            Settings(tagging_model="YOLO").validate()

    def test_validate_invalid_archival_backend_raises(self):
        with self.assertRaises(ValueError):
            Settings(archival_backend="Azure").validate()

    def test_validate_invalid_types_raises(self):
        with self.assertRaises(ValueError):
            Settings(rescan_interval="600").validate()
        with self.assertRaises(ValueError):
            Settings(archival_bucket=12345).validate()

    # --- Corrupted / Malformed Settings Recovery ---
    def test_read_corrupted_json_returns_default_settings(self):
        with open(self.test_file, "w") as f:
            f.write("{invalid_json: true, missing_quotes")
        
        manager = SettingsManager(self.test_file)
        self.assertEqual(manager.get(), Settings())

    def test_read_invalid_values_json_returns_default_settings(self):
        with open(self.test_file, "w") as f:
            json.dump({"rescan_interval": -50, "tagging_model": "InvalidModel"}, f)
        
        manager = SettingsManager(self.test_file)
        self.assertEqual(manager.get(), Settings())

    def test_read_settings_filters_unknown_future_fields(self):
        with open(self.test_file, "w") as f:
            json.dump({
                "rescan_interval": 300,
                "tagging_model": "Mobilenet",
                "unknown_future_flag": True
            }, f)
        
        manager = SettingsManager(self.test_file)
        settings = manager.get()
        self.assertEqual(settings.rescan_interval, 300)
        self.assertEqual(settings.tagging_model, "Mobilenet")
        self.assertFalse(hasattr(settings, "unknown_future_flag"))


if __name__ == "__main__":
    unittest.main()

