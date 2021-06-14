import logging
import random
from time import sleep

import numpy as np

from devices.Camera import CameraAbstract
from utils.constants import WIDTH_IMAGE_TAU2, HEIGHT_IMAGE_TAU2, CAMERA_TAU
from utils.logger import make_logger


class TeaxGrabber(CameraAbstract):
    @property
    def type(self) -> int:
        return CAMERA_TAU

    def __del__(self):
        pass

    def __init__(self, logging_handlers: tuple = (logging.StreamHandler(),),
                 logging_level: int = logging.INFO):
        logger = make_logger('DummyCamera', logging_handlers, logging_level)
        super().__init__(logger)
        self._log.info('Ready.')
        self.__resolution = 500
        self.__inner_temperatures_list = np.linspace(25, 60, num=self.__resolution, dtype='float')
        self.__inner_temperatures_idx = -1

    def __repr__(self):
        return 'DummyTeaxGrabber'

    def grab(self):
        sleep(random.uniform(0.1, 0.2))
        return np.random.rand(HEIGHT_IMAGE_TAU2, WIDTH_IMAGE_TAU2)

    @property
    def is_dummy(self):
        return True

    def get_inner_temperature(self, *kwargs):
        self.__inner_temperatures_idx += 1
        self.__inner_temperatures_idx %= self.__resolution
        return float(self.__inner_temperatures_list[self.__inner_temperatures_idx])

    def ffc(self, length=None) -> bool:
        return True

    @property
    def ffc_mode(self):
        return 0x0000

    @ffc_mode.setter
    def ffc_mode(self, mode: str):
        pass

    @property
    def gain(self):
        return 0x0000

    @gain.setter
    def gain(self, mode: str):
        pass

    @property
    def agc(self):
        return 0x0000

    @agc.setter
    def agc(self, mode: str):
        pass

    @property
    def sso(self) -> int:
        return 0

    @sso.setter
    def sso(self, percentage: int):
        pass

    @property
    def contrast(self) -> int:
        return 0

    @contrast.setter
    def contrast(self, value: int):
        pass

    @property
    def brightness(self) -> int:
        return 0

    @brightness.setter
    def brightness(self, value: int):
        pass

    @property
    def brightness_bias(self) -> int:
        return 0

    @brightness_bias.setter
    def brightness_bias(self, value: int):
        pass

    @property
    def isotherm(self) -> int:
        return 0

    @isotherm.setter
    def isotherm(self, value: int):
        pass

    @property
    def dde(self) -> int:
        return 0

    @dde.setter
    def dde(self, value: int):
        pass

    @property
    def tlinear(self):
        return 0

    @tlinear.setter
    def tlinear(self, value: int):
        pass

    @property
    def lvds(self):
        return 0

    @lvds.setter
    def lvds(self, mode: int):
        pass

    @property
    def lvds_depth(self):
        return 0

    @lvds_depth.setter
    def lvds_depth(self, mode: int):
        pass

    @property
    def xp(self):
        return 0

    @xp.setter
    def xp(self, mode: int):
        pass

    @property
    def cmos_depth(self):
        return 0

    @cmos_depth.setter
    def cmos_depth(self, mode: int):
        pass

    def set_params_by_dict(self, args):
        pass
