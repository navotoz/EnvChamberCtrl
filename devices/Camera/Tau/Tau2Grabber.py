from time import sleep

import numpy as np
import logging
from pathlib import Path

import yaml

import devices.Camera.Tau.tau2_config as ptc
from devices.Camera.Tau.FtdiThread import FtdiIO

from devices.Camera.Tau.TauCameraCtrl import Tau, _make_packet
from utils.logger import make_logger, make_logging_handlers, make_device_logging_handler
from threading import Thread


class Tau2Grabber(Tau):
    def __init__(self, vid=0x0403, pid=0x6010,
                 logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        logging_handlers_ = make_device_logging_handler('TeaxGrabber', logging_handlers)
        logger = make_logger('TeaxGrabber', logging_handlers_, logging_level)
        super().__init__(logger=logger)
        self._n_retry = 3

        self._frame_size = 2 * self.height * self.width + 10 + 4 * self.height  # 10 byte header, 4 bytes pad per row
        self._width = self.width
        self._height = self.height
        try:
            self._io = FtdiIO(vid=vid, pid=pid, frame_size=self._frame_size,
                              width=self._width, height=self._height,
                              logging_handlers=logging_handlers, logging_level=logging_level)
        except RuntimeError:
            self._log.info('Could not connect to TeaxGrabber.')
            raise RuntimeError
        self._io.setDaemon(True)
        self._io.start()
        self.reset()
        sleep(0.5)
        self.ffc_mode = ptc.FFC_MODE_CODE_DICT['external']

    def __del__(self) -> None:
        if hasattr(self, '_io') and isinstance(self._io, Thread):
            self._io.join()
        if hasattr(self, '_log') and isinstance(self._log, logging.Logger):
            self._log.critical('Exit.')

    def _send_and_recv_threaded(self, command: ptc.Code, argument: (bytes, None), n_retry: int = 3) -> (bytes, None):
        data = _make_packet(command, argument)
        return self._io.parse(data=data, command=command, n_retry=n_retry if n_retry != self.n_retry else self.n_retry)

    def grab(self, to_temperature: bool = False, n_retries: int = 3) -> (np.ndarray, None):
        # Note that in TeAx's official driver, they use a threaded loop
        # to read data as it streams from the camera and they simply
        # process images/commands as they come back. There isn't the same
        # sort of query/response structure that you'd normally see with
        # a serial device as the camera basically vomits data as soon as
        # the port opens.
        #
        # The current approach here aims to allow a more structured way of
        # interacting with the camera by synchronising with the stream whenever
        # some particular data is requested. However in the future it may be better
        # if this is moved to a threaded function that continually services the
        # serial stream and we have some kind of helper function which responds
        # to commands and waits to see the answer from the camera.
        for _ in range(max(1, n_retries)):
            if (raw_image_8bit := self._io.grab()) is not None:
                raw_image_16bit = 0x3FFF & np.array(raw_image_8bit).view('uint16')[:, 1:-1]

                if to_temperature:
                    raw_image_16bit = 0.04 * raw_image_16bit - 273
                return raw_image_16bit
        return None

    def set_params_by_dict(self, yaml_or_dict: (Path, dict)):
        if isinstance(yaml_or_dict, Path):
            params = yaml.safe_load(yaml_or_dict)
        else:
            params = yaml_or_dict.copy()
        default_n_retries = self.n_retry
        self.n_retry = 10
        self.ffc_mode = params.get('ffc_mode', 'external')
        self.isotherm = params.get('isotherm', 0)
        self.dde = params.get('dde', 0)
        self.tlinear = params.get('tlinear', 0)
        self.gain = params.get('gain', 'high')
        self.agc = params.get('agc', 'manual')
        self.sso = params.get('sso', 0)
        self.contrast = params.get('contrast', 0)
        self.brightness = params.get('brightness', 0)
        self.brightness_bias = params.get('brightness_bias', 0)
        self.cmos_depth = params.get('cmos_depth', 0)  # 14bit pre AGC
        self.fps = params.get('fps', 4)  # 60Hz NTSC
        # self.correction_mask = params.get('corr_mask', 0)  # off
        self.n_retry = default_n_retries

    @property
    def n_retry(self) -> int:
        return self._n_retry

    @n_retry.setter
    def n_retry(self, n_retry: int):
        self._n_retry = n_retry
