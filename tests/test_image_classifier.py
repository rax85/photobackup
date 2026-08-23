import unittest
from unittest.mock import patch, MagicMock

try:
    import numpy as np
except ImportError:
    np = None

from media_server.image_classifier import ImageClassifier
from media_server.settings import Settings


class TestImageClassifier(unittest.TestCase):

    def setUp(self):
        # Create a dummy settings object
        self.settings = Settings(tagging_model="Resnet")

    @patch("media_server.image_classifier.ResNet50V2")
    @patch("media_server.image_classifier.MobileNetV3Small")
    def test_init_resnet(self, mock_mobilenet, mock_resnet):
        # Test that the ResNet50V2 model is loaded when specified in settings
        self.settings.tagging_model = "Resnet"
        classifier = ImageClassifier(self.settings)
        mock_resnet.assert_called_once()
        mock_mobilenet.assert_not_called()
        self.assertIsNotNone(classifier.model)

    @patch("media_server.image_classifier.ResNet50V2")
    @patch("media_server.image_classifier.MobileNetV3Small")
    def test_init_mobilenet(self, mock_mobilenet, mock_resnet):
        # Test that the MobileNetV3 model is loaded when specified in settings
        self.settings.tagging_model = "Mobilenet"
        classifier = ImageClassifier(self.settings)
        mock_mobilenet.assert_called_once()
        mock_resnet.assert_not_called()
        self.assertIsNotNone(classifier.model)

    @patch("media_server.image_classifier.ResNet50V2")
    @patch("media_server.image_classifier.MobileNetV3Small")
    def test_init_off(self, mock_mobilenet, mock_resnet):
        # Test that no model is loaded when tagging is off
        self.settings.tagging_model = "Off"
        classifier = ImageClassifier(self.settings)
        mock_mobilenet.assert_not_called()
        mock_resnet.assert_not_called()
        self.assertIsNone(classifier.model)

    @patch("media_server.image_classifier.image")
    @patch("media_server.image_classifier.ResNet50V2")
    def test_classify_image(self, mock_resnet, mock_image):
        # Test the image classification process
        mock_model_instance = mock_resnet.return_value
        dummy_preds = np.random.rand(1, 1000) if np else [[0.1] * 1000]
        mock_model_instance.predict.return_value = dummy_preds

        # Mock the decode_predictions function
        with patch("media_server.image_classifier.resnet_decode") as mock_decode:
            mock_decode.return_value = [
                [
                    ("n02123045", "tabby", 0.5),
                    ("n02123159", "tiger_cat", 0.3),
                    ("n02123394", "Persian_cat", 0.1),
                    ("n02124075", "Egyptian_cat", 0.05),
                    ("n02125311", "cougar", 0.05),
                ]
            ]

            # Mock image loading and preprocessing
            mock_img = MagicMock()
            mock_image.load_img.return_value = mock_img
            dummy_array = (
                np.random.rand(224, 224, 3)
                if np
                else [[[0.1, 0.1, 0.1]] * 224] * 224
            )
            mock_image.img_to_array.return_value = dummy_array

            # Initialize the classifier and classify an image
            classifier = ImageClassifier(self.settings)
            predictions = classifier.classify_image("dummy_path.jpg")

            # Assert that the predictions are in the correct format
            self.assertEqual(len(predictions), 5)
            self.assertIsInstance(predictions[0], tuple)
            self.assertIsInstance(predictions[0][0], str)
            self.assertIsInstance(predictions[0][1], float)

    @patch("media_server.image_classifier.image")
    @patch("media_server.image_classifier.ResNet50V2")
    def test_corrupt_image_returns_empty_predictions(self, mock_resnet, mock_image):
        mock_image.load_img.side_effect = Exception("UnidentifiedImageError: image is corrupted")
        classifier = ImageClassifier(self.settings)
        preds = classifier.classify_image("corrupted.jpg")
        self.assertEqual(preds, [])

    @patch("media_server.image_classifier.ResNet50V2")
    def test_unload_lifecycle(self, mock_resnet):
        classifier = ImageClassifier(self.settings)
        self.assertIsNotNone(classifier.model)
        classifier.unload()
        self.assertIsNone(classifier.model)
        self.assertIsNone(classifier.preprocess_input)
        self.assertIsNone(classifier.decode_predictions)
        # classify_image returns [] after unload
        self.assertEqual(classifier.classify_image("dummy.jpg"), [])


if __name__ == "__main__":
    unittest.main()

