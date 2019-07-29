import asyncio
import random
import functools
import os

from lipnet.core.decoders import Decoder
from lipnet.lipreading.helpers import labels_to_text
from lipnet.utils.spell import Spell
from lipnet.model2 import LipNet
from keras.optimizers import Adam
from keras import backend as K
import numpy as np

CURRENT_PATH = os.path.dirname(os.path.abspath(__file__))

PREDICT_GREEDY      = False
PREDICT_BEAM_WIDTH  = 200
PREDICT_DICTIONARY  = os.path.join(CURRENT_PATH,'..','..','LipNet','common','dictionaries','grid.txt')
WEIGHT_PATH = os.path.join(CURRENT_PATH,'..','..','LipNet','evaluation','models', 'overlapped-weights368.h5')

class LipReadingTask:
    def __init__(self, q):
        self._q = q

    @functools.lru_cache(maxsize=1)
    def decoder(self):
        return Decoder(greedy=PREDICT_GREEDY, beam_width=PREDICT_BEAM_WIDTH,
                       postprocessors=[labels_to_text, Spell(path=PREDICT_DICTIONARY).sentence])

    @functools.lru_cache(maxsize=1)
    def lipnet(self, c, w, h, n, absolute_max_string_len=32, output_size=28):
        lipnet = LipNet(img_c=c, img_w=w, img_h=h, frames_n=n,
                        absolute_max_string_len=absolute_max_string_len, output_size=output_size)

        adam = Adam(lr=0.0001, beta_1=0.9, beta_2=0.999, epsilon=1e-08)

        lipnet.model.compile(loss={'ctc': lambda y_true, y_pred: y_pred}, optimizer=adam)
        lipnet.model.load_weights(WEIGHT_PATH)
        return lipnet

    async def do(self):
        while True:
            video = await asyncio.get_event_loop().run_in_executor(None, self._q.get)
            if video is not None:
                if K.image_data_format() == 'channels_first':
                    img_c, frames_n, img_w, img_h = video.data.shape
                else:
                    frames_n, img_w, img_h, img_c = video.data.shape

                X_data       = np.array([video.data]).astype(np.float32) / 255
                input_length = np.array([len(video.data)])

                y_pred         = self.lipnet(c=img_c, w=img_w, h=img_h, n=frames_n).predict(X_data)
                result         = self.decoder().decode(y_pred, input_length)[0]

                print("{}: {}".format('Speaker 0', result))
            else:
                break