import unittest
import os
import shutil
import tempfile
import json
import time
from unittest import mock
import io
import hashlib
from datetime import datetime
import threading

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from media_server.server import app as flask_app
from media_server import media_scanner
from media_server import database as db_utils
from media_server import server as media_server_module
from media_server import settings as settings_utils
from PIL import Image
from tests.test_server import TestServerFlaskWithDB

class TestServerBackgroundScan(TestServerFlaskWithDB):
    def setUp(self):
        super().setUp()
        self.settings_manager = media_server_module.settings_manager

    @mock.patch('media_server.server.scanner_wakeup_event.wait')
    def test_scanner_wakes_up_on_interval_change(self, mock_event_wait):
        self.settings_manager.write_settings(settings_utils.Settings(rescan_interval=0))

        # Event to signal that the scanner has started and is waiting
        scanner_waiting_event = threading.Event()
        def wait_side_effect(timeout=None):
            scanner_waiting_event.set()
            # We need to return here to avoid an infinite loop
            # in the actual background scanner task.
            return
        mock_event_wait.side_effect = wait_side_effect

        scanner_thread = threading.Thread(
            target=media_server_module.background_scanner_task,
            args=(flask_app.app_context(),),
            daemon=True
        )
        scanner_thread.start()

        # Wait for the scanner to be in the waiting state
        self.assertTrue(scanner_waiting_event.wait(timeout=5))

        # Now, update the settings, which should trigger the event
        new_settings = {
            "rescan_interval": 120,
            "tagging_model": "Off",
            "archival_backend": "Off",
            "archival_bucket": ""
        }
        response = self.client.put('/api/settings', json=new_settings)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(media_server_module.scanner_wakeup_event.is_set())

        # Clean up
        self.settings_manager.write_settings(settings_utils.Settings(rescan_interval=0))
        media_server_module.scanner_wakeup_event.set() # Wake up the thread to allow it to exit
        scanner_thread.join(timeout=1)
