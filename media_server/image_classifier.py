import os
from threading import Lock
from typing import List, Tuple
from absl import logging
from media_server.settings import Settings

# Module-level placeholders for lazy loading and unit-test patching
ResNet50V2 = None
MobileNetV3Small = None
image = None
resnet_preprocess = None
resnet_decode = None
mobilenet_preprocess = None
mobilenet_decode = None
np = None


def _load_ml_modules():
    """Lazily loads ML dependencies on demand."""
    global ResNet50V2, MobileNetV3Small, image
    global resnet_preprocess, resnet_decode, mobilenet_preprocess, mobilenet_decode
    global np

    if np is None:
        import numpy as _np

        np = _np

    if ResNet50V2 is None or MobileNetV3Small is None:
        try:
            if "KERAS_BACKEND" not in os.environ:
                os.environ["KERAS_BACKEND"] = "torch"
            import keras  # noqa: F401
            from keras.applications import (
                ResNet50V2 as _ResNet50V2,
                MobileNetV3Small as _MobileNetV3Small,
            )
            from keras.preprocessing import image as _image
            from keras.applications.resnet_v2 import (
                preprocess_input as _resnet_preprocess,
                decode_predictions as _resnet_decode,
            )
            from keras.applications.mobilenet_v3 import (
                preprocess_input as _mobilenet_preprocess,
                decode_predictions as _mobilenet_decode,
            )

            ResNet50V2 = _ResNet50V2
            MobileNetV3Small = _MobileNetV3Small
            image = _image
            resnet_preprocess = _resnet_preprocess
            resnet_decode = _resnet_decode
            mobilenet_preprocess = _mobilenet_preprocess
            mobilenet_decode = _mobilenet_decode
        except ImportError as e:
            logging.warning(
                f"Optional ML dependencies (keras/torch) not available: {e}. "
                "Image classification will be disabled."
            )
            return False
    return True


class ImageClassifier:
    """Classifies images using pre-trained deep learning vision models."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.preprocess_input = None
        self.decode_predictions = None
        self._lock = Lock()

        if self.settings.tagging_model in ("Resnet", "Mobilenet"):
            self._initialize_model()

    def _initialize_model(self) -> None:
        """Initializes the requested model if ML libraries are present."""
        if not _load_ml_modules() and ResNet50V2 is None:
            return

        try:
            if self.settings.tagging_model == "Resnet":
                if ResNet50V2:
                    self.model = ResNet50V2(weights="imagenet")
                    self.preprocess_input = resnet_preprocess
                    self.decode_predictions = resnet_decode
            elif self.settings.tagging_model == "Mobilenet":
                if MobileNetV3Small:
                    self.model = MobileNetV3Small(weights="imagenet")
                    self.preprocess_input = mobilenet_preprocess
                    self.decode_predictions = mobilenet_decode
        except Exception as e:
            logging.warning(
                f"Failed to load vision model '{self.settings.tagging_model}': {e}"
            )
            self.model = None

    def unload(self) -> None:
        """Unloads the model from memory and releases references."""
        with self._lock:
            self.model = None
            self.preprocess_input = None
            self.decode_predictions = None

    def classify_image(self, image_path: str) -> List[Tuple[str, float]]:
        """
        Classifies an image at the given path. Thread-safe inference.

        Args:
            image_path: Path to the image file on disk.

        Returns:
            List of (label, confidence_score) tuples for top predictions.
        """
        if not self.model or not image:
            return []

        try:
            img = image.load_img(image_path, target_size=(224, 224))
            x = image.img_to_array(img)
            x = np.expand_dims(x, axis=0) if np else [x]
            x = self.preprocess_input(x) if self.preprocess_input else x

            with self._lock:
                if not self.model:
                    return []
                preds = self.model.predict(x)

            decoded_preds = (
                self.decode_predictions(preds, top=5) if self.decode_predictions else []
            )

            predictions = []
            if decoded_preds and len(decoded_preds) > 0:
                for item in decoded_preds[0]:
                    if len(item) == 3:
                        _, label, score = item
                        predictions.append((str(label), float(score)))
            return predictions
        except Exception as e:
            logging.warning(f"Error classifying image {image_path}: {e}")
            return []
