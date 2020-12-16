import multiprocessing as mp
import struct
import threading as th
from multiprocessing.connection import Connection
from time import sleep
from typing import List, Tuple

import numpy as np
from pyftdi.ftdi import Ftdi
from pyftdi.ftdi import FtdiError

from devices.Camera import _make_device_from_vid_pid
from devices.Camera.utils import BytesBuffer, generate_subsets_indices_in_string, generate_overlapping_list_chunks, \
    DuplexPipe, get_crc
from utils.logger import make_logger
from utils.tools import SyncFlag
import usb.core
import usb.util
from usb.util import ENDPOINT_IN, ENDPOINT_OUT

BORDER_VALUE = 64
FTDI_PACKET_SIZE = 512 * 8
SYNC_MSG = b'SYNC' + struct.pack(4 * 'B', *[0, 0, 0, 0])


def connect_usb(vid, pid) -> Tuple[usb.core.Device, usb.core.Endpoint]:
    device = _make_device_from_vid_pid(vid, pid)
    usb.util.claim_interface(device, 0)
    endpoint = device[0][(0, 0)][0]
    return device, endpoint


class UsbIO(mp.Process):
    _thread_read = _thread_parse = _thread_image = None

    def __init__(self, vid, pid, cmd_recv: Connection, cmd_send: Connection, image_recv: Connection,
                 image_send: Connection, flag_run: SyncFlag, logging_handlers: (list, tuple), logging_level: int):
        super().__init__()
        self._log = make_logger('UsbIO', logging_handlers, logging_level)
        try:
            self._device, self._endpoint = connect_usb(vid, pid)
        except RuntimeError:
            raise RuntimeError('Could not connect to the Thermapp camera.')

        self._flag_run = flag_run
        self._lock_access = th.Lock()
        self._semaphore_access_ftdi = th.Semaphore(value=1)
        self._event_allow_ftdi_access = th.Event()
        self._event_allow_ftdi_access.set()
        self._event_read = th.Event()
        self._event_read.clear()
        self._buffer = BytesBuffer(flag_run, size_to_signal=0)
        self._cmd_pipe = DuplexPipe(cmd_send, cmd_recv, self._flag_run)
        self._image_pipe = DuplexPipe(image_send, image_recv, self._flag_run)

        # get serial number ect.
        self._thread_read = th.Thread(target=self._th_reader_func, name='th_thermapp_reader', daemon=False)
        self._thread_read.start()

    def run(self) -> None:
        self._thread_read = th.Thread(target=self._th_reader_func, name=f'th_thermapp_reader_{self._serial_num}', daemon=False)
        self._thread_read.start()
        self._thread_parse = th.Thread(target=self._th_parse_func, name=f'th_thermapp_parser_{self._serial_num}', daemon=False)
        self._thread_parse.start()
        self._thread_image = th.Thread(target=self._th_image_func, name=f'th_thermapp_image_{self._serial_num}', daemon=False)
        self._thread_image.start()
        self._log.info('Ready.')

        self._thread_read.join()
        self._thread_image.join()
        self._thread_parse.join()

    def __del__(self) -> None:
        if not hasattr(self, '_flag_run'):
            return
        self._flag_run.set(False)
        self._cmd_pipe.send(None)
        self._image_pipe.send(None)
        self._event_allow_ftdi_access.set()
        self._thread_read.join()
        self._thread_image.join()
        self._thread_parse.join()
        self._ftdi.close()

    def _reset(self) -> None:
        with self._lock_access:
            self._ftdi.set_bitmode(0xFF, Ftdi.BitMode.RESET)
            self._ftdi.set_bitmode(0xFF, Ftdi.BitMode.SYNCFF)
        self._buffer.clear_buffer()
        self._event_allow_ftdi_access.set()
        self._event_read.clear()
        self._log.debug('Reset.')

    def _parse_func(self, command: Code) -> (List, None):
        len_in_bytes = command.reply_bytes + 10
        argument_length = len_in_bytes * (5 + 1)

        idx_list = generate_subsets_indices_in_string(self._buffer, b'UART')
        if not idx_list:
            return None
        data = map(lambda idx: self._buffer[idx:idx + argument_length][5::6], idx_list)
        data = map(lambda d: d[0], data)
        data = generate_overlapping_list_chunks(data, len_in_bytes)
        data = filter(lambda res: len(res) >= len_in_bytes, data)  # length of message at least as expected
        data = filter(lambda res: res[0] == 110, data)  # header is 0x6E (110)
        data = list(filter(lambda res: res[3] == command.code, data))
        if not data:
            return None
        data = data[-1]
        crc_1 = get_crc(data[:6])
        crc_2 = get_crc(data[8:8 + command.reply_bytes])
        if not crc_1 == data[6:8] or not crc_2 == data[-2:]:
            self._log.error('CRC codes are wrong on received packet.')
            return None
        ret_value = data[8:8 + command.reply_bytes]
        ret_value = struct.pack('<' + len(ret_value) * 'B', *ret_value)
        return ret_value

    def _write(self, data: bytes) -> None:
        buffer = b"UART"
        buffer += int(len(data)).to_bytes(1, byteorder='big')  # doesn't matter
        buffer += data
        try:
            with self._lock_access:
                self._ftdi.write_data(buffer)
            self._log.debug(f"Send {data}")
        except FtdiError:
            self._log.debug('Write error.')
            self._reset()

    def _th_reader_func(self) -> None:
        while self._flag_run:
            if self._event_read.is_set():
                with self._lock_access:
                    data = self._ftdi.read_data(FTDI_PACKET_SIZE)
                    while not data and self._flag_run:
                        data += self._ftdi.read_data(1)
                self._buffer += data

    def _th_parse_func(self) -> None:
        while self._flag_run:
            data, command, n_retry = self._cmd_pipe.recv()
            self._event_allow_ftdi_access.wait()
            with self._semaphore_access_ftdi:
                self._event_read.set()
                self._write(data)
                idx = 0
                sleep(0.2)
                while idx < max(1, n_retry) and self._flag_run:
                    if (res := self._parse_func(command)) is not None:
                        break
                    self._log.debug('Could not parse, retrying..')
                    self._write(SYNC_MSG)
                    self._write(data)
                    idx += 1
                    sleep(0.2)
                self._cmd_pipe.send(res)
                self._event_read.clear()
                self._log.debug(f"Recv {res}") if res else None
                self._buffer.clear_buffer()

    def _th_image_func(self) -> None:
        while self._flag_run:
            self._image_pipe.recv()  # waits for signal from TeaxGrabber
            self._event_allow_ftdi_access.clear()  # only allows this thread to operate
            with self._semaphore_access_ftdi:
                while self._flag_run:
                    self._event_read.set()
                    self._buffer.sync_teax()
                    buffer_len = self._buffer.wait_for_size()
                    res = self._buffer[:min(self._frame_size, buffer_len)]
                    if struct.unpack('h', res[10:12])[0] != 0x4000:  # a magic word
                        continue
                    frame_width = struct.unpack('h', res[5:7])[0] - 2
                    if frame_width != self._width:
                        self._log.debug(f"Received frame has incorrect width of {frame_width}.")
                        continue
                    raw_image_8bit = np.frombuffer(res[10:], dtype='uint8').reshape((-1, 2 * (self._width + 2)))
                    if not self._is_8bit_image_borders_valid(raw_image_8bit):
                        continue
                    self._event_allow_ftdi_access.set()
                    self._image_pipe.send(raw_image_8bit)
                    self._log.debug('Grabbed Image')
                    break

    def _is_8bit_image_borders_valid(self, raw_image_8bit: np.ndarray) -> bool:
        if np.nonzero(raw_image_8bit[:, 0] != 0)[0]:
            return False
        valid_idx = np.nonzero(raw_image_8bit[:, -1] != BORDER_VALUE)
        if len(valid_idx) != 1:
            return False
        valid_idx = int(valid_idx[0])
        if valid_idx != self._height - 1:  # the different value should be in the bottom of the border
            return False
        return True
