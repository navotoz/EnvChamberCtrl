import logging
import random
from time import sleep

import numpy as np

from utils.constants import WIDTH_IMAGE, HEIGHT_IMAGE
from utils.logger import make_logger


class TeaxGrabber:
    def __init__(self, logging_handlers: tuple = (logging.StreamHandler(),),
                 logging_level: int = logging.INFO):
        # raise RuntimeError
        self.__log = make_logger('DummyCamera', logging_handlers, logging_level)
        self.__log.info('Ready.')
        self.__resolution = 500
        self.__inner_temperatures_list = np.linspace(25, 60, num=self.__resolution, dtype='float')
        self.__inner_temperatures_idx = -1

    def __repr__(self):
        return 'DummyTeaxGrabber'

    def grab(self):
        sleep(random.uniform(0.1, 0.2))
        return np.random.rand(HEIGHT_IMAGE, WIDTH_IMAGE), bytes(1)

    @property
    def is_dummy(self):
        return True

    def get_inner_temperature(self, temperature_type: str):
        self.__inner_temperatures_idx += 1
        self.__inner_temperatures_idx %= self.__resolution
        return float(self.__inner_temperatures_list[self.__inner_temperatures_idx])

    def ffc_mode_select(self, mode=None)->bool:
        return True

    def ffc(self, length=None):
        pass

    @property
    def gain(self):
        return 0x0002

    @gain.setter
    def gain(self, mode: int):
        pass
