import unittest
import os
from media_server.geolocator import GeoLocator, City


class TestGeoLocator(unittest.TestCase):
    def setUp(self):
        self.geolocator = GeoLocator()
        # Create a dummy csv file for testing
        self.test_csv_file = 'test_cities.csv'
        with open(self.test_csv_file, 'w') as f:
            f.write('city,lat,lng,country\n')
            f.write('London,51.5074,-0.1278,United Kingdom\n')
            f.write('Paris,48.8566,2.3522,France\n')
            f.write('New York,40.7128,-74.0060,United States\n')
            f.write('Tokyo,35.6895,139.6917,Japan\n')
            f.write('Sydney,-33.8688,151.2093,Australia\n')

        self.geolocator.load_cities(self.test_csv_file)

    def tearDown(self):
        os.remove(self.test_csv_file)

    def test_load_cities(self):
        self.assertEqual(len(self.geolocator.cities), 5)
        self.assertIsInstance(self.geolocator.cities[0], City)

    def test_nearest_city(self):
        # Test with coordinates close to London
        closest_city = self.geolocator.nearest_city(51.5, -0.1)
        self.assertEqual(closest_city.name, 'London')

        # Test with coordinates close to Paris
        closest_city = self.geolocator.nearest_city(48.8, 2.3)
        self.assertEqual(closest_city.name, 'Paris')

        # Test with coordinates close to New York
        closest_city = self.geolocator.nearest_city(40.7, -74.0)
        self.assertEqual(closest_city.name, 'New York')

        # Test with coordinates close to Tokyo
        closest_city = self.geolocator.nearest_city(35.7, 139.7)
        self.assertEqual(closest_city.name, 'Tokyo')

        # Test with coordinates close to Sydney
        closest_city = self.geolocator.nearest_city(-33.8, 151.2)
        self.assertEqual(closest_city.name, 'Sydney')

    def test_nearest_city_no_cities(self):
        geolocator = GeoLocator()
        closest_city = geolocator.nearest_city(0, 0)
        self.assertIsNone(closest_city)


if __name__ == '__main__':
    unittest.main()
