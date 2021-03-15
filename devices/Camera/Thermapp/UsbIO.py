import csv
import multiprocessing as mp
import struct
import threading as th
from multiprocessing.connection import Connection

import numpy as np

from devices.Camera import _make_device_from_vid_pid
from devices.Camera.utils import BytesBuffer, DuplexPipe
from utils.logger import make_logger
from utils.tools import SyncFlag
import usb.core
import usb.util
from usb.util import ENDPOINT_IN, ENDPOINT_OUT

HEADER_SIZE_BYTES = 64
PACKET_SIZE_BYTES = 512 * 16


def initial_header():
    return struct.pack('<' + 32 * 'H',
                       0xa5a5,
                       0xa5a5,
                       0xa5a5,
                       0xa5d5,
                       0x0002,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       # 0x0019,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       # 0x075c,
                       # 0x0b85,
                       # 0x05f4,
                       # 0x0800,
                       # 0x0b85,
                       # 0x0b85,
                       0x0000,
                       0x0000,
                       0x0000,
                       0x0000,
                       # 0x0570,
                       # 0x0b85,
                       # 0x0040,
                       0x0000,
                       0x0000,
                       0x0050,
                       0x0003,
                       0x0000,
                       0x0fff)


def connect_usb(vid, pid) -> usb.core.Device:
    device = _make_device_from_vid_pid(vid, pid)
    usb.util.claim_interface(device, 0)
    return device


class UsbIO(mp.Process):
    _thread_read = _thread_parse = _thread_image = None

    def __init__(self, vid, pid, image_recv: Connection,  image_send: Connection,
                 flag_run: SyncFlag, logging_handlers: (list, tuple), logging_level: int):
        super().__init__()
        self._log = make_logger('UsbIO', logging_handlers, logging_level)
        try:
            self._device = connect_usb(vid, pid)
        except RuntimeError:
            raise RuntimeError('Could not connect to the Thermapp camera.')
        self._flag_run = flag_run
        self._image_pipe = DuplexPipe(image_send, image_recv, self._flag_run)
        self._preamble_bytes = struct.pack('HHHH', 0xa5a5, 0xa5a5, 0xa5a5, 0xa5d5)

        self._device.write(endpoint=ENDPOINT_OUT | 2, data=self._image_pipe.recv())
        while (res := bytes(self._device.read(ENDPOINT_IN | 1, PACKET_SIZE_BYTES))).find(self._preamble_bytes) != 0:
            continue
        res = res[res.find(self._preamble_bytes):]
        res = res[:len(res) - len(res) % 2]
        res = struct.unpack(len(res) // 2 * 'H', res)
        self._serial_number = np.array(res[5]).astype('uint32') | np.array(res[6] << 16).astype('uint32')
        self._height = res[9]
        self._width = res[10]
        self._image_pipe.send((self._width, self._height))
        self._frame_size = 2 * self._width * self._height

        self._lock_access = th.Lock()
        self._event_read = th.Event()
        self._event_read.clear()
        self._buffer = BytesBuffer(flag_run, size_to_signal=0)

    def run(self) -> None:
        self._thread_image = th.Thread(target=self._th_image_func, name=f'th_thermapp_image_{self._serial_number}',
                                       daemon=False)
        self._thread_image.start()
        self._log.info('Ready.')
        self._thread_image.join()

    def __del__(self) -> None:
        if hasattr(self, '_flag_run'):
            self._flag_run.set(False)
        try:
            self._image_pipe.send(None)
        except (BrokenPipeError, AttributeError):
            pass
        if hasattr(self, '_thread_image') and self._thread_image:
            self._thread_image.join()

    def _reset(self) -> None:
        if not self._flag_run:
            return
        self._device.reset()
        self._buffer.clear_buffer()
        self._event_read.clear()
        self._log.debug('Reset.')

    def _write(self, data: bytes) -> None:
        try:
            with self._lock_access:
                self._device.write(endpoint=ENDPOINT_OUT | 2, data=initial_header())
            self._log.debug(f"Send {data}")
        except (usb.core.USBError, usb.core.NoBackendError) as err:
            self._log.debug(f'Write error {err}.')
            # self._reset()

    def _th_image_func(self) -> None:
        while self._flag_run:
            header = self._image_pipe.recv()  # waits for signal from ThermappGrabber
            if not header:
                break
            while self._flag_run:
                self._device.write(endpoint=ENDPOINT_OUT | 2, data=header)

                # sync to header
                val = b''
                while (idx := val.rfind(self._preamble_bytes)) < 0:
                    val += self._device.read(ENDPOINT_IN | 1, PACKET_SIZE_BYTES)
                val = val[idx:]

                # remove the header
                while len(val) < HEADER_SIZE_BYTES:
                    val += self._device.read(ENDPOINT_IN | 1, PACKET_SIZE_BYTES)
                #### todo: what about the temperature????
                # todo: the temperature is in the header somewhere in 14 and 15

                h_  = struct.unpack(len(header)//2 * 'H', val[:HEADER_SIZE_BYTES])
                image_id = np.array(h_[26]).astype('uint32') | np.array(h_[27] << 16).astype('uint32')
                tempereture = np.array(h_[14]).astype('uint32') | np.array(h_[15] << 16).astype('uint32')
                with open('thermapp_header_dump.csv', 'a') as fp:
                    w = csv.writer(fp)
                    w.writerow(h_[14:16])
                with open('thermapp_header_dump_14.csv', 'a') as fp:
                    w = csv.writer(fp)
                    w.writerow(f'{h_[14]:b}')
                with open('thermapp_header_dump_15.csv', 'a') as fp:
                    w = csv.writer(fp)
                    w.writerow(f'{h_[15]:b}')
                with open('thermapp_header_dump_both.csv', 'a') as fp:
                    w = csv.writer(fp)
                    w.writerow(f'{h_[14]:b}{h_[15]:b}')
                with open('thermapp_dump.csv', 'a') as fp:
                    w = csv.writer(fp)
                    w.writerow(h_)


                val = val[HEADER_SIZE_BYTES:]

                # read the entire image
                while len(val) < self._frame_size:
                    val += self._device.read(ENDPOINT_IN | 1, PACKET_SIZE_BYTES)
                val = val[:self._frame_size]

                # check if header is in val
                if val.rfind(self._preamble_bytes) >= 0:
                    continue

                # transform image to array of uint16
                raw_image_8bit = np.frombuffer(val, dtype='uint8').reshape(-1, 2 * self._width)
                image = raw_image_8bit.view('uint16')

                # send back to the ThermappGrabber
                self._image_pipe.send(image)
                self._log.debug('Grabbed Image')
                break


