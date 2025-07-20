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
            archival_bucket="my-bucket"
        )
        manager.write_settings(new_settings)

        # Verify in-memory copy is updated
        self.assertEqual(manager.get(), new_settings)

        # Verify file is updated
        with open(self.test_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data, {
            "rescan_interval": 1200,
            "tagging_model": "Resnet",
            "archival_backend": "AWS",
            "archival_bucket": "my-bucket"
        })

        # Verify reading from file works correctly
        new_manager = SettingsManager(self.test_file)
        self.assertEqual(new_manager.get(), new_settings)

    def test_create_file_if_not_exists(self):
        self.assertFalse(os.path.exists(self.test_file))
        manager = SettingsManager(self.test_file)
        manager.write_settings(Settings())
        self.assertTrue(os.path.exists(self.test_file))

if __name__ == "__main__":
    unittest.main()
