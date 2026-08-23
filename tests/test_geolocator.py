import os
import unittest
from media_server.geolocator import City, GeoLocator


class TestGeoLocator(unittest.TestCase):
    def setUp(self):
        self.geolocator = GeoLocator()
        # Create a dummy csv file for testing
        self.test_csv_file = "test_cities.csv"
        with open(self.test_csv_file, "w", encoding="utf-8") as f:
            f.write("city,lat,lng,country\n")
            f.write("London,51.5074,-0.1278,United Kingdom\n")
            f.write("Paris,48.8566,2.3522,France\n")
            f.write("New York,40.7128,-74.0060,United States\n")
            f.write("Tokyo,35.6895,139.6917,Japan\n")
            f.write("Sydney,-33.8688,151.2093,Australia\n")

        self.geolocator.load_cities(self.test_csv_file)

    def tearDown(self):
        if os.path.exists(self.test_csv_file):
            os.remove(self.test_csv_file)

    def test_load_cities(self):
        self.assertEqual(len(self.geolocator.cities), 5)
        self.assertIsInstance(self.geolocator.cities[0], City)

    def test_nearest_city(self):
        # Test with coordinates close to London
        closest_city = self.geolocator.nearest_city(51.5, -0.1)
        self.assertIsNotNone(closest_city)
        self.assertEqual(closest_city.name, "London")

        # Test with coordinates close to Paris
        closest_city = self.geolocator.nearest_city(48.8, 2.3)
        self.assertIsNotNone(closest_city)
        self.assertEqual(closest_city.name, "Paris")

        # Test with coordinates close to New York
        closest_city = self.geolocator.nearest_city(40.7, -74.0)
        self.assertIsNotNone(closest_city)
        self.assertEqual(closest_city.name, "New York")

        # Test with coordinates close to Tokyo
        closest_city = self.geolocator.nearest_city(35.7, 139.7)
        self.assertIsNotNone(closest_city)
        self.assertEqual(closest_city.name, "Tokyo")

        # Test with coordinates close to Sydney
        closest_city = self.geolocator.nearest_city(-33.8, 151.2)
        self.assertIsNotNone(closest_city)
        self.assertEqual(closest_city.name, "Sydney")

    def test_nearest_city_no_cities(self):
        geolocator = GeoLocator()
        old_cities = geolocator.cities
        geolocator.cities = []
        try:
            closest_city = geolocator.nearest_city(0, 0)
            self.assertIsNone(closest_city)
        finally:
            geolocator.cities = old_cities

    def test_spatial_grid_ring_expansion_with_many_cities(self):
        """Test with > 20 cities to force GeoLocator spatial grid ring search execution."""
        geolocator = GeoLocator()
        grid_csv = "test_grid_cities.csv"
        try:
            with open(grid_csv, "w", encoding="utf-8") as f:
                f.write("city,lat,lng,country\n")
                # Generate 30 cities across different grid cells
                for i in range(30):
                    f.write(f"City_{i},{10.0 + i * 0.5},{20.0 + i * 0.5},Country_{i}\n")

            geolocator.load_cities(grid_csv, force=True)
            self.assertGreater(len(geolocator.cities), 20)
            self.assertTrue(bool(geolocator.grid))

            # Query near City_5 (lat=12.5, lng=22.5)
            match = geolocator.nearest_city(12.51, 22.51)
            self.assertIsNotNone(match)
            self.assertEqual(match.name, "City_5")

            # Boundary coordinates: North Pole, South Pole, Prime Meridian, Antimeridian
            self.assertIsNotNone(geolocator.nearest_city(90.0, 0.0))
            self.assertIsNotNone(geolocator.nearest_city(-90.0, 0.0))
            self.assertIsNotNone(geolocator.nearest_city(0.0, 180.0))
            self.assertIsNotNone(geolocator.nearest_city(0.0, -180.0))
        finally:
            if os.path.exists(grid_csv):
                os.remove(grid_csv)


if __name__ == "__main__":
    unittest.main()

