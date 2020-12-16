import logging
from pathlib import Path


import struct

import  numpy as np
import multiprocessing as mp

from devices.Camera import CameraAbstract
from devices.Camera.Thermapp.UsbIO import UsbIO
from utils.logger import make_logging_handlers, make_device_logging_handler, make_logger
from utils.tools import show_image, SyncFlag

TIMEOUT_IN_NSEC = 1e9  # 1 seconds
MAGIC_IMAGE_ENDING = 0x0ff0


def make_header(endian:str):
    return struct.pack(endian + 32 * 'H',
    0xa5a5,
    0xa5a5,
    0xa5a5,
    0xa5d5,
    0x0002,
   0x0000,
   0x0000,
   0x0000,
   0x0000,
    0x0120,
    0x0180,
    0x0120,
    0x0180,
    0x0019,
    0x0000,
    0x0000,
     0x075c,
    0x0b85,
    0x05f4,
    0x0800,
    0x0b85,
    0x0b85,
     0x0000,
    0x0570,
    0x0b85,
    0x0040,
    0x0000,
    0x0000,
    0x0050,
    0x0003,
    0x0000,
    0x0fff    )
    # return struct.pack(endian + 26 * 'H',
    # 0xa5a5,
    # 0xa5a5,
    # 0xa5a5,
    # 0xa5d5,
    # 0x0002,
    # 0x0120,
    # 0x0180,
    # 0x0120,
    # 0x0180,
    # 0x0019,
    # 0x0000,
    #  0x075c,
    # 0x0b85,
    # 0x05f4,
    # 0x0800,
    # 0x0b85,
    # 0x0b85,
    #  0x0000,
    # 0x0570,
    # 0x0b85,
    # 0x0040,
    # 0x0000,
    # 0x0050,
    # 0x0003,
    # 0x0000,
    # 0x0fff    )


class ThermappGrabber(CameraAbstract):
    def __init__(self, vid=0x1772, pid=0x0002,
                 logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        logging_handlers = make_device_logging_handler('Thermapp', logging_handlers)
        logger = make_logger('Thermapp', logging_handlers, logging_level)
        super().__init__(logger=logger)

        self._flag_run = SyncFlag(True)
        self._lock_cmd_send = mp.Lock()

        cmd_ftdi_recv, self._cmd_send = mp.Pipe(duplex=False)
        self._cmd_recv, cmd_teax_send = mp.Pipe(duplex=False)
        image_ftdi_recv, self._image_send = mp.Pipe(duplex=False)
        self._image_recv, image_teax_send = mp.Pipe(duplex=False)

        try:
            self._io = UsbIO(vid, pid, cmd_ftdi_recv, cmd_teax_send, image_ftdi_recv, image_teax_send,
                             self._flag_run, logging_handlers, logging_level)
        except RuntimeError:
            self._log.info('Could not connect to Thermapp.')
            raise RuntimeError
        self._io.daemon = False
        self._io.start()
        self.ffc()


        header = make_header('<')
        device.write(endpoint=ENDPOINT_OUT | 2, data=header)
        in_val = struct.unpack(32 * 'H', header)
        f_string = ''
        for i in in_val:
            f_string += f'{i:5d} '
        print(f_string)



        # cup = np.load('with_cup.npy').astype('float32')
        # no_cup = np.load('without_cup.npy').astype('float32')
        #
        #
        # exit()



        while True:
            device.write(endpoint=ENDPOINT_OUT | 2, data=header)
            preabmle_bytes = struct.pack('HHHH', 0xa5a5, 0xa5a5, 0xa5a5, 0xa5d5)
            val = b''
            while (idx:=val.rfind(preabmle_bytes)) < 0:
                val += device.read(endpoint.bEndpointAddress, endpoint.wMaxPacketSize)

            val = val[idx:]
            while len(val) <= 64:
                val += device.read(endpoint.bEndpointAddress, endpoint.wMaxPacketSize)
            res = struct.unpack('<' + len(val) // 2 * 'H', val)
            serial_number  = np.array(res[5]).astype('uint32') | np.array(res[6] << 16).astype('uint32')
            height = res[11]
            width = res[12]
            image_id  = np.array(res[26]).astype('uint32') | np.array(res[27] << 16).astype('uint32')
            temperature = int(res[16])    # ????????
            # while (idx:=val.find(b'\xff\xff'))<0:
            while len(val) < 2 * width * height:
                val += device.read(endpoint.bEndpointAddress, endpoint.wMaxPacketSize*16)
            val = val[64:2 * width * height+64]
            raw_image_8bit = np.frombuffer(val, dtype='uint8').reshape(-1, 2 * width)
            image = 0x3FFF & raw_image_8bit.view('uint16')
            show_image(image)

        # np.save('without_cup.npy', image)
        # np.save('with_cup.npy', image)
        exit()


        val_out = np.array(struct.unpack('<' + len(val)//2 * 'H', val))
        val_out.reshape(-1, width)
        image = val_out[:height * width].reshape(height, width)

        f_string = ''
        for i in val:
            f_string += f'{i:5d} '
        print(f_string)
        a=1


    def set_params_by_dict(self, yaml_or_dict: (Path, dict)):
        pass

    @property
    def is_dummy(self) -> bool:
        return False

    def grab(self) -> ndarray:
        pass

    def __del__(self):
        pass

    def ffc(self):
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
# # Thermo Filter Low Emasivity 0.95 Scale turnocation 0.25
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
# # Thermo Filter Low Emasivity 0.95 Scale turnocation 0.25 NoiseClean
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
# # Thermo Filter Disabled Emasivity 0.95 Scale turnocation 0.25 NoiseCleanOff ReflectedTemp5
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
# # Thermo Filter Off Emasivity 0.95 Scale turnocation 0.25
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
# # Thermo Filter Off Emasivity 0.6 Scale turnocation 0.25
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
# # Thermo Filter Off Emasivity 0.95 Scale turnocation 0.3
# 0040   a5 a5 a5 a5 a5 a5 d5 a5 02 00 33 dd a3 0e 04 00
# 0050   78 00 20 01 80 01 20 01 80 01 19 00 af f4 de 4b
# 0060   5c 07 85 0b f8 05 00 08 85 0b 85 0b 00 00 70 05
# 0070   85 0b 40 00 cb 04 00 00 7c 00 02 00 00 00 00 00
# "\xa5\xa5\xa5\xa5\xa5\xa5\xd5\xa5\x02\x00\x33\xdd\xa3\x0e\x04\x00" \
# "\x78\x00\x20\x01\x80\x01\x20\x01\x80\x01\x19\x00\xaf\xf4\xde\x4b" \
# "\x5c\x07\x85\x0b\xf8\x05\x00\x08\x85\x0b\x85\x0b\x00\x00\x70\x05" \
# "\x85\x0b\x40\x00\xcb\x04\x00\x00\x7c\x00\x02\x00\x00\x00\x00\x00"
#
