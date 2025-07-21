import os
os.environ['KERAS_BACKEND'] = 'torch'

import keras
from keras.applications import EfficientNetV2L, EfficientNetV2S
from keras.preprocessing import image
from keras.applications.efficientnet_v2 import preprocess_input, decode_predictions
import numpy as np

from media_server.settings import Settings

class ImageClassifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.target_size = None

        if self.settings.tagging_model == "Resnet":
            self.model = EfficientNetV2L(weights='imagenet')
            self.target_size = (480, 480)
        elif self.settings.tagging_model == "Mobilenet":
            self.model = EfficientNetV2S(weights='imagenet')
            self.target_size = (384, 384)

    def classify_image(self, image_path: str):
        if not self.model:
            return []

        img = image.load_img(image_path, target_size=self.target_size)
        x = image.img_to_array(img)
        x = np.expand_dims(x, axis=0)
        x = preprocess_input(x)

        preds = self.model.predict(x)
        decoded_preds = decode_predictions(preds, top=5)[0]

        return [(label, float(score)) for _, label, score in decoded_preds]
