import csv
from dataclasses import dataclass
from math import radians, sin, cos, sqrt, atan2
from threading import Lock

@dataclass
class City:
    name: str
    country: str
    latitude: float
    longitude: float

class GeoLocator:
    """
    A singleton class for finding the nearest city to a given GPS coordinate.

    This class loads a list of cities from a CSV file and provides a method
    to find the closest city to a given latitude and longitude. It uses the
        Haversine formula to calculate distances.
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
        """
        Initializes the GeoLocator instance.

        This method is called only once when the singleton instance is created.
        It initializes the list of cities and a flag to track if the city
        data has been loaded.
        """
        self.cities = []
        self.loaded = False

    def load_cities(self, csv_file):
        """
        Loads city data from a CSV file into memory.

        This method is thread-safe and ensures that the city data is loaded
        only once. The CSV file should have columns for city name, latitude,
        longitude, and country.

        Args:
            csv_file: The path to the CSV file containing city data.
        """
        if self.loaded:
            return
        with self._lock:
            if self.loaded:
                return
            with open(csv_file, 'r') as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                for row in reader:
                    self.cities.append(
                        City(
                            name=row[0],
                            latitude=float(row[1]),
                            longitude=float(row[2]),
                            country=row[3],
                        )
                    )
            self.loaded = True

    def nearest_city(self, latitude, longitude):
        """
        Finds the nearest city to the given latitude and longitude.

        Args:
            latitude: The latitude of the location.
            longitude: The longitude of the location.

        Returns:
            A `City` object representing the nearest city, or None if no cities
            are loaded.
        """
        if not self.cities:
            return None

        min_distance = float('inf')
        closest_city = None

        for city in self.cities:
            distance = self._haversine_distance(latitude, longitude, city.latitude, city.longitude)
            if distance < min_distance:
                min_distance = distance
                closest_city = city

        return closest_city

    def _haversine_distance(self, lat1, lon1, lat2, lon2):
        # Convert latitude and longitude from degrees to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        distance = 6371 * c  # Radius of earth in kilometers
        return distance
