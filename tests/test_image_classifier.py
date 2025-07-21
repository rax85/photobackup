import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from media_server.image_classifier import ImageClassifier
from media_server.settings import Settings

class TestImageClassifier(unittest.TestCase):

    def setUp(self):
        # Create a dummy settings object
        self.settings = Settings(tagging_model="Resnet")

    @patch('media_server.image_classifier.EfficientNetV2L')
    @patch('media_server.image_classifier.EfficientNetV2S')
    def test_init_efficientnetl(self, mock_efficientnets, mock_efficientnetl):
        # Test that the EfficientNetV2L model is loaded when specified in settings
        self.settings.tagging_model = "Resnet"
        classifier = ImageClassifier(self.settings)
        mock_efficientnetl.assert_called_once()
        mock_efficientnets.assert_not_called()
        self.assertIsNotNone(classifier.model)

    @patch('media_server.image_classifier.EfficientNetV2L')
    @patch('media_server.image_classifier.EfficientNetV2S')
    def test_init_efficientnets(self, mock_efficientnets, mock_efficientnetl):
        # Test that the EfficientNetV2S model is loaded when specified in settings
        self.settings.tagging_model = "Mobilenet"
        classifier = ImageClassifier(self.settings)
        mock_efficientnets.assert_called_once()
        mock_efficientnetl.assert_not_called()
        self.assertIsNotNone(classifier.model)

    @patch('media_server.image_classifier.EfficientNetV2L')
    @patch('media_server.image_classifier.EfficientNetV2S')
    def test_init_off(self, mock_efficientnets, mock_efficientnetl):
        # Test that no model is loaded when tagging is off
        self.settings.tagging_model = "Off"
        classifier = ImageClassifier(self.settings)
        mock_efficientnets.assert_not_called()
        mock_efficientnetl.assert_not_called()
        self.assertIsNone(classifier.model)

    @patch('media_server.image_classifier.image')
    @patch('media_server.image_classifier.EfficientNetV2L')
    @patch('media_server.image_classifier.decode_predictions')
    def test_classify_image(self, mock_decode, mock_efficientnet, mock_image):
        # Test the image classification process
        # Mock the model and its predictions
        mock_model_instance = mock_efficientnet.return_value
        mock_model_instance.predict.return_value = np.random.rand(1, 1000)

        # Mock the decode_predictions function
        mock_decode.return_value = [
            ('n02123045', 'tabby', 0.5),
            ('n02123159', 'tiger_cat', 0.3),
            ('n02123394', 'Persian_cat', 0.1),
            ('n02124075', 'Egyptian_cat', 0.05),
            ('n02125311', 'cougar', 0.05)
        ]

        # Mock image loading and preprocessing
        mock_img = MagicMock()
        mock_image.load_img.return_value = mock_img
        mock_image.img_to_array.return_value = np.random.rand(480, 480, 3)

        # Initialize the classifier and classify an image
        classifier = ImageClassifier(self.settings)
        predictions = classifier.classify_image('dummy_path.jpg')

        # Assert that the predictions are in the correct format
        self.assertEqual(len(predictions), 5)
        self.assertIsInstance(predictions[0], tuple)
        self.assertIsInstance(predictions[0][0], str)
        self.assertIsInstance(predictions[0][1], float)

if __name__ == '__main__':
    unittest.main()
