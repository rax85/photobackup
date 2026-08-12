import dataclasses
import json
import os
import threading
from typing import Any, Dict, Literal


@dataclasses.dataclass
class Settings:
    """A data class representing the application settings."""

    rescan_interval: int = 600
    tagging_model: Literal["Resnet", "Mobilenet", "Off"] = "Off"
    archival_backend: Literal["Google Cloud", "AWS", "Off"] = "Off"
    archival_bucket: str = ""

    def validate(self) -> None:
        """Validates settings values."""
        if not isinstance(self.rescan_interval, int) or self.rescan_interval < 0:
            raise ValueError("rescan_interval must be a non-negative integer")
        if self.tagging_model not in ("Resnet", "Mobilenet", "Off"):
            raise ValueError(
                f"Invalid tagging_model: {self.tagging_model}. Allowed: 'Resnet', 'Mobilenet', 'Off'"
            )
        if self.archival_backend not in ("Google Cloud", "AWS", "Off"):
            raise ValueError(
                f"Invalid archival_backend: {self.archival_backend}. Allowed: 'Google Cloud', 'AWS', 'Off'"
            )
        if not isinstance(self.archival_bucket, str):
            raise ValueError("archival_bucket must be a string")

    def to_dict(self) -> Dict[str, Any]:
        """Converts settings to dictionary."""
        return dataclasses.asdict(self)


class SettingsManager:
    """A thread-safe manager for application settings persistence."""

    def __init__(self, path: str):
        """
        Initializes the SettingsManager.

        Args:
            path: The path to the settings file.
        """
        self.path = path
        self._lock = threading.Lock()
        self.settings = self._read_settings()

    def _read_settings(self) -> Settings:
        """
        Reads the settings from the settings file.
        If the file does not exist or has invalid content, returns default settings.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Filter known fields to avoid errors with future/extraneous keys
            known_fields = {f.name for f in dataclasses.fields(Settings)}
            filtered_data = {k: v for k, v in data.items() if k in known_fields}
            settings = Settings(**filtered_data)
            settings.validate()
            return settings
        except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
            return Settings()

    def get(self) -> Settings:
        """Returns the current settings."""
        with self._lock:
            return self.settings

    def write_settings(self, settings: Settings) -> None:
        """
        Validates and writes the settings to the settings file.

        Args:
            settings: A Settings object.
        """
        settings.validate()
        with self._lock:
            self.settings = settings
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(settings.to_dict(), f, indent=4)
