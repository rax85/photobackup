import csv
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
import os
from threading import Lock
from typing import List, Optional
from absl import logging


@dataclass
class City:
    name: str
    country: str
    latitude: float
    longitude: float
    lat_rad: float = 0.0
    lon_rad: float = 0.0

    def __post_init__(self):
        if self.lat_rad == 0.0 and self.lon_rad == 0.0:
            self.lat_rad = radians(self.latitude)
            self.lon_rad = radians(self.longitude)


class GeoLocator:
    """
    A thread-safe singleton for finding the nearest city to a given GPS coordinate
    using the Haversine distance formula against an offline city database.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initializes the GeoLocator instance."""
        if not hasattr(self, "initialized"):
            self.cities: List[City] = []
            self.loaded = False
            self.initialized = True

    def load_cities(self, csv_file: str) -> None:
        """
        Loads city data from a CSV file into memory with precomputed radians.

        Args:
            csv_file: The path to the CSV file containing city data.
        """
        if not os.path.exists(csv_file):
            logging.warning(f"GeoLocator CSV file not found: {csv_file}")
            return

        with self._lock:
            # Re-read if empty or reloading from another file in tests
            cities_list = []
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Skip header
                    for row in reader:
                        if len(row) >= 4:
                            try:
                                lat = float(row[1])
                                lon = float(row[2])
                                cities_list.append(
                                    City(
                                        name=row[0],
                                        latitude=lat,
                                        longitude=lon,
                                        country=row[3],
                                        lat_rad=radians(lat),
                                        lon_rad=radians(lon),
                                    )
                                )
                            except (ValueError, TypeError):
                                continue
                self.cities = cities_list
                self.loaded = True
                logging.info(
                    f"Loaded {len(self.cities)} cities for offline geolocator."
                )
            except Exception as e:
                logging.error(f"Failed to load cities from {csv_file}: {e}")

    def nearest_city(self, latitude: float, longitude: float) -> Optional[City]:
        """
        Finds the nearest city to the given latitude and longitude.

        Args:
            latitude: The latitude in decimal degrees.
            longitude: The longitude in decimal degrees.

        Returns:
            A City object representing the closest city, or None if no cities loaded.
        """
        if not self.cities:
            return None

        lat1 = radians(latitude)
        lon1 = radians(longitude)

        min_distance = float("inf")
        closest_city = None

        for city in self.cities:
            dlon = city.lon_rad - lon1
            dlat = city.lat_rad - lat1
            a = (
                sin(dlat / 2.0) ** 2
                + cos(lat1) * cos(city.lat_rad) * sin(dlon / 2.0) ** 2
            )
            c = 2.0 * atan2(sqrt(a), sqrt(max(0.0, 1.0 - a)))
            distance = 6371.0 * c

            if distance < min_distance:
                min_distance = distance
                closest_city = city

        return closest_city
