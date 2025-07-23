import dataclasses
import json
from typing import Literal, Optional


@dataclasses.dataclass
class Settings:
    """A data class representing the application settings."""

    rescan_interval: int = 600
    tagging_model: Literal["Resnet", "Mobilenet", "Off"] = "Off"
    archival_backend: Literal["Google Cloud", "AWS", "Off"] = "Off"
    archival_bucket: str = ""


class SettingsManager:
    """A class to manage the application settings."""

    def __init__(self, path: str):
        """
        Initializes the SettingsManager.

        Args:
            path: The path to the settings file.
        """
        self.path = path
        self.settings = self._read_settings()

    def _read_settings(self) -> Settings:
        """
        Reads the settings from the settings file.

        If the file does not exist, it returns the default settings.

        Returns:
            A Settings object.
        """
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            return Settings(**data)
        except FileNotFoundError:
            return Settings()

    def get(self) -> Settings:
        """
        Returns the current settings.

        Returns:
            A Settings object.
        """
        return self.settings

    def write_settings(self, settings: Settings):
        """
        Writes the settings to the settings file.

        Args:
            settings: A Settings object.
        """
        self.settings = settings
        with open(self.path, "w") as f:
            json.dump(dataclasses.asdict(settings), f, indent=4)
