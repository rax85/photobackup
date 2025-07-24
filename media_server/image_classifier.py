import os

os.environ["KERAS_BACKEND"] = "torch"

import keras
import keras_hub
from keras.applications import ResNet50V2, MobileNetV3Small
from keras.preprocessing import image
from keras.applications.resnet_v2 import (
    preprocess_input as resnet_preprocess,
    decode_predictions as resnet_decode,
)
from keras.applications.mobilenet_v3 import (
    preprocess_input as mobilenet_preprocess,
    decode_predictions as mobilenet_decode,
)
import numpy as np

from media_server.settings import Settings


class ImageClassifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.preprocess_input = None
        self.decode_predictions = None

        if self.settings.tagging_model == "Resnet":
            self.model = ResNet50V2(weights="imagenet")
            self.preprocess_input = resnet_preprocess
            self.decode_predictions = resnet_decode
        elif self.settings.tagging_model == "Mobilenet":
            self.model = MobileNetV3Small(weights="imagenet")
            self.preprocess_input = mobilenet_preprocess
            self.decode_predictions = mobilenet_decode
        elif self.settings.tagging_model == "gemma":
            self.model = keras_hub.KerasLayer.from_file("gemma3_instruct_4b")

    def generate_tags(self, image_path: str):
        if not self.model:
            return []

        img = image.load_img(image_path)

        # Gemma is a multimodal model, so we can pass the image and text to the model
        results = self.model.generate(
            ["generate a list of tags for this image", img],
        )

        # The result is a list of strings, so we'll split the string into a list of tags
        tags = results[0].split(",")
        return [(tag.strip(), 1.0) for tag in tags]

    def classify_image(self, image_path: str):
        if not self.model:
            return []

        if self.settings.tagging_model == "gemma":
            return self.generate_tags(image_path)

        img = image.load_img(image_path, target_size=(224, 224))
        x = image.img_to_array(img)
        x = np.expand_dims(x, axis=0)
        x = self.preprocess_input(x)

        preds = self.model.predict(x)
        decoded_preds = self.decode_predictions(preds, top=5)

        # The result is a list of lists of predictions, one for each image in the batch
        predictions = []
        for _, label, score in decoded_preds[0]:
            predictions.append((label, float(score)))
        return predictions
