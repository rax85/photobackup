import csv
from dataclasses import dataclass
from math import radians, sin, cos, sqrt, atan2


@dataclass
class City:
    name: str
    country: str
    latitude: float
    longitude: float


class GeoLocator:
    def __init__(self):
        self.cities = []

    def load_cities(self, csv_file):
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

    def nearest_city(self, latitude, longitude):
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
