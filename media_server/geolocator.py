import csv
from dataclasses import dataclass
from math import atan2, cos, floor, radians, sin, sqrt
import os
from threading import Lock
from typing import Dict, List, Optional, Tuple
from absl import logging


@dataclass
class City:
    name: str
    country: str
    latitude: float
    longitude: float
    lat_rad: Optional[float] = None
    lon_rad: Optional[float] = None

    def __post_init__(self):
        if self.lat_rad is None:
            self.lat_rad = radians(self.latitude)
        if self.lon_rad is None:
            self.lon_rad = radians(self.longitude)


def haversine_distance(
    lat1_rad: float, lon1_rad: float, lat2_rad: float, lon2_rad: float
) -> float:
    """Calculates Haversine distance in kilometers between two points in radians."""
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = (
        sin(dlat / 2.0) ** 2
        + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2.0) ** 2
    )
    c = 2.0 * atan2(sqrt(a), sqrt(max(0.0, 1.0 - a)))
    return 6371.0 * c


class GeoLocator:
    """
    A thread-safe singleton for finding the nearest city to a given GPS coordinate
    using the Haversine distance formula against an offline city database with
    spatial grid indexing for high performance.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    instance = super().__new__(cls)
                    instance.cities: List[City] = []
                    instance.grid: Dict[Tuple[int, int], List[City]] = {}
                    instance.loaded = False
                    instance._loaded_csv = ""
                    cls._instance = instance
        return cls._instance

    def __init__(self):
        # Initialization is handled safely in __new__ under _lock
        pass

    def load_cities(self, csv_file: str, force: bool = False) -> None:
        """
        Loads city data from a CSV file into memory with precomputed radians
        and builds a spatial index.

        Args:
            csv_file: The path to the CSV file containing city data.
            force: If True, forces reloading even if the CSV was already loaded.
        """
        if not os.path.exists(csv_file):
            logging.warning(f"GeoLocator CSV file not found: {csv_file}")
            return

        with self._lock:
            if self.loaded and not force and self._loaded_csv == csv_file:
                return

            cities_list = []
            grid: Dict[Tuple[int, int], List[City]] = {}
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Skip header
                    for row in reader:
                        if len(row) >= 4:
                            try:
                                lat = float(row[1])
                                lon = float(row[2])
                                city = City(
                                    name=row[0],
                                    latitude=lat,
                                    longitude=lon,
                                    country=row[3],
                                    lat_rad=radians(lat),
                                    lon_rad=radians(lon),
                                )
                                cities_list.append(city)
                                cell = (floor(lat), floor(lon))
                                grid.setdefault(cell, []).append(city)
                            except (ValueError, TypeError):
                                continue
                self.cities = cities_list
                self.grid = grid
                self.loaded = True
                self._loaded_csv = csv_file
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

        # If small number of cities or grid not constructed, fallback to direct linear scan
        if len(self.cities) <= 20 or not self.grid:
            lat1 = radians(latitude)
            lon1 = radians(longitude)
            min_dist = float("inf")
            best_city = None
            for city in self.cities:
                d = haversine_distance(lat1, lon1, city.lat_rad, city.lon_rad)
                if d < min_dist:
                    min_dist = d
                    best_city = city
            return best_city

        lat1 = radians(latitude)
        lon1 = radians(longitude)
        center_lat_bin = floor(latitude)
        center_lon_bin = floor(longitude)

        min_distance = float("inf")
        closest_city = None

        # Search expanding rings of cells around the target coordinate
        max_ring = 180
        for ring in range(max_ring + 1):
            ring_candidates = []
            for dlat in range(-ring, ring + 1):
                for dlon in range(-ring, ring + 1):
                    if max(abs(dlat), abs(dlon)) == ring:
                        cell = (center_lat_bin + dlat, center_lon_bin + dlon)
                        if cell in self.grid:
                            ring_candidates.extend(self.grid[cell])

            for city in ring_candidates:
                dist = haversine_distance(lat1, lon1, city.lat_rad, city.lon_rad)
                if dist < min_distance:
                    min_distance = dist
                    closest_city = city

            if closest_city is not None:
                # 1 degree of latitude is ~111 km. Once the ring boundary is farther
                # than the closest city found so far, no unexamined cell can be closer.
                if (ring * 110.0) >= min_distance:
                    break

        if closest_city is None:
            for city in self.cities:
                dist = haversine_distance(lat1, lon1, city.lat_rad, city.lon_rad)
                if dist < min_distance:
                    min_distance = dist
                    closest_city = city

        return closest_city
