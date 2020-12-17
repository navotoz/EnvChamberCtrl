import logging
from pathlib import Path

import numpy as np
import multiprocessing as mp

from devices.Camera import CameraAbstract
from devices.Camera.Thermapp.UsbIO import UsbIO
from devices.Camera.utils import DuplexPipe
from utils.constants import CAMERA_THERMAPP
from utils.logger import make_logging_handlers, make_device_logging_handler, make_logger
from utils.tools import SyncFlag

TIMEOUT_IN_NSEC = 1e9  # 1 seconds
MAGIC_IMAGE_ENDING = 0x0ff0


def header_thermography() -> bytes:
    return b"\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5" \
           b"\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
           b"\x78\x00\x20\x01\x80\x01\x20\x01" \
           b"\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
           b"\x5c\x07\x85\x0b\xf8\x05\x00\x08" \
           b"\x85\x0b\x85\x0b\x00\x00\x70\x05" \
           b"\x85\x0b\x40\x00\xcb\x04\x00\x00" \
           b"\x7c\x00\x02\x00\x00\x00\x00\x00"


def header_nightvision() -> bytes:
    return b"\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5" \
           b"\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
           b"\x78\x00\x20\x01\x80\x01\x20\x01" \
           b"\x80\x01\x19\x00\x66\x41\xa2\x38" \
           b"\x5c\x07\x85\x0b\xfa\x05\x00\x08" \
           b"\x85\x0b\x85\x0b\x00\x00\x70\x05" \
           b"\x85\x0b\x40\x00\xfb\x04\x00\x00" \
           b"\x7c\x00\x02\x00\x00\x00\x00\x00"


class ThermappGrabber(CameraAbstract):
    def get_inner_temperature(self, temperature_type: str) -> float:
        return -float('inf')  # todo: fix the inner temperatures

    @property
    def type(self) -> int:
        return CAMERA_THERMAPP

    def __init__(self, vid=0x1772, pid=0x0002,
                 logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        logging_handlers = make_device_logging_handler('Thermapp', logging_handlers)
        logger = make_logger('Thermapp', logging_handlers, logging_level)
        super().__init__(logger=logger)

        self._flag_run = SyncFlag(True)
        self._lock_cmd_send = mp.Lock()

        image_usb_recv, _image_send = mp.Pipe(duplex=False)
        _image_recv, image_usb_send = mp.Pipe(duplex=False)
        self._image_pipe = DuplexPipe(_image_send, _image_recv, self._flag_run)
        self._image_pipe.send(header_thermography())

        try:
            self._io = UsbIO(vid, pid, image_usb_recv, image_usb_send,
                             self._flag_run, logging_handlers, logging_level)
        except RuntimeError:
            self._log.info('Could not connect to Thermapp.')
            raise RuntimeError
        self._io.daemon = True
        self._io.start()
        self._width, self._height = self._image_pipe.recv()
        self.ffc()

    def set_params_by_dict(self, yaml_or_dict: (Path, dict)):
        pass

    @property
    def is_dummy(self) -> bool:
        return False

    def grab(self, nightvision: bool = False) -> np.ndarray:
        self._image_pipe.send(header_thermography() if not nightvision else header_nightvision())
        return self._image_pipe.recv()

    def __del__(self):
        if hasattr(self, '_flag_run'):
            self._flag_run.set(False)
        try:
            self._image_pipe.send(None)
        except (BrokenPipeError, AttributeError):
            pass
        if hasattr(self, '_io') and self._io:
            self._io.join()

    def ffc(self) -> None:
        pass

# # NightVision
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 66 41 a2 38
# 0060   5c 07 85 0b fa 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 fb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\x66\x41\xa2\x38" \
# "\x5c\x07\x85\x0b\xfa\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xfb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
#
# # Thermo Filter Low Emissivity 0.95 Scale truncation 0.25
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
#
# # Thermo Filter Low Emissivity 0.95 Scale truncation 0.25 NoiseClean
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
#
# # Thermo Filter Disabled Emissivity 0.95 Scale truncation 0.25 NoiseCleanOff ReflectedTemp5
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
#
#
# # Thermo Filter Off Emissivity 0.95 Scale truncation 0.25
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
# # Thermo Filter Off Emissivity 0.6 Scale truncation 0.25
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
# # Thermo Filter Off Emissivity 0.95 Scale truncation 0.3
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
