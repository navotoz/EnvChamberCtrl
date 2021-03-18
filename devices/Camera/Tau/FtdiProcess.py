import multiprocessing as mp
import struct
import threading as th
from multiprocessing.connection import Connection
from time import sleep
from typing import List

import numpy as np
import usb.core
import usb.util
from pyftdi.ftdi import Ftdi
from pyftdi.ftdi import FtdiError

from devices.Camera import _make_device_from_vid_pid
from devices.Camera.Tau.tau2_config import Code, READ_SENSOR_TEMPERATURE
from devices.Camera.utils import BytesBuffer, generate_subsets_indices_in_string, generate_overlapping_list_chunks, \
    get_crc
from utils.logger import make_logger, make_device_logging_handler
from utils.tools import SyncFlag, DuplexPipe

BORDER_VALUE = 64
FTDI_PACKET_SIZE = 512 * 8
SYNC_MSG = b'SYNC' + struct.pack(4 * 'B', *[0, 0, 0, 0])


class FtdiIO(mp.Process):
    _thread_read = _thread_parse = _thread_image = None

    def __init__(self, vid, pid, cmd_pipe: DuplexPipe, image_pipe:DuplexPipe, frame_size: int, width: int,
                 height: int, flag_run: SyncFlag, logging_handlers: (list, tuple), logging_level: int):
        super().__init__()
        logging_handlers = make_device_logging_handler('FtdiIO', logging_handlers)
        self._log = make_logger('FtdiIO', logging_handlers, logging_level)
        try:
            self._ftdi = connect_ftdi(vid, pid)
        except RuntimeError:
            raise RuntimeError('Could not connect to the Tau2 camera.')

        self._flag_run: SyncFlag = flag_run
        self._frame_size = frame_size
        self._width = width
        self._height = height
        self._lock_access = th.Lock()
        self._semaphore_access_ftdi = th.Semaphore(value=1)
        self._event_allow_ftdi_access = th.Event()
        self._event_allow_ftdi_access.set()
        self._event_read = th.Event()
        self._event_read.clear()
        self._buffer = BytesBuffer(flag_run, self._frame_size)
        self._cmd_pipe = cmd_pipe
        self._image_pipe = image_pipe
        self._n_retries_image = 5

    def run(self) -> None:
        self._thread_read = th.Thread(target=self._th_reader_func, name='th_tau2grabber_reader', daemon=False)
        self._thread_read.start()
        self._thread_parse = th.Thread(target=self._th_parse_func, name='th_tau2grabber_parser', daemon=False)
        self._thread_parse.start()
        self._thread_image = th.Thread(target=self._th_image_func, name='th_tau2grabber_image', daemon=False)
        self._thread_image.start()
        self._log.info('Ready.')

    def purge(self) -> None:
        self._cmd_pipe.send(None)
        self._cmd_pipe.purge()
        self._image_pipe.send(None)
        self._image_pipe.purge()

    def _finish_run(self):
        try:
            self._cmd_pipe.send(None)
        except (BrokenPipeError, AttributeError):
            pass
        try:
            self._image_pipe.send(None)
        except (BrokenPipeError, AttributeError):
            pass
        if hasattr(self, '_thread_read') and self._thread_read:
            self._thread_read.join()
        if hasattr(self, '_thread_image') and self._thread_image:
            self._thread_image.join()
        if hasattr(self, '_thread_parse') and self._thread_parse:
            self._thread_parse.join()
        try:
            self._ftdi.close()
        except:
            pass
        try:
            self._log.critical('Exit.')
        except:
            pass

    def __del__(self) -> None:
        if hasattr(self, '_flag_run'):
            self._flag_run.set(False)
        if hasattr(self, '_event_allow_ftdi_access') and self._event_allow_ftdi_access:
            self._event_allow_ftdi_access.set()
        self._finish_run()

    def _reset(self) -> None:
        if not self._flag_run:
            return
        self._buffer.clear_buffer()
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
            recv_result = self._cmd_pipe.recv()
            if not isinstance(recv_result, tuple):
                self._cmd_pipe.send(None)
                continue
            data, command, n_retry = recv_result
            self._event_allow_ftdi_access.wait()
            with self._semaphore_access_ftdi:
                if not self._flag_run:
                    break
                self._event_read.set()
                self._write(data)
                idx = 0
                sleep(0.2)
                while idx < max(1, n_retry) and self._flag_run:
                    if (parsed_func := self._parse_func(command)) is not None:
                        break
                    self._log.debug('Could not parse, retrying..')
                    self._write(SYNC_MSG)
                    self._write(data)
                    idx += 1
                    sleep(0.2)
                self._cmd_pipe.send(parsed_func)
                self._event_read.clear()
                self._log.debug(f"Recv {parsed_func}") if parsed_func else None
                self._buffer.clear_buffer()

    def _th_image_func(self) -> None:
        while self._flag_run:
            self._image_pipe.recv()  # waits for signal from TeaxGrabber
            self._event_allow_ftdi_access.clear()  # only allows this thread to operate
            with self._semaphore_access_ftdi:
                idx = 0
                while self._flag_run and idx < self._n_retries_image:
                    self._event_read.set()
                    sleep(0.01)
                    idx += 1
                    self._buffer.sync_teax()
                    buffer_len = self._buffer.wait_for_size()
                    res = self._buffer[:min(self._frame_size, buffer_len)]
                    if res and struct.unpack('h', res[10:12])[0] != 0x4000:  # a magic word
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
        if raw_image_8bit is None:
            return False
        if np.nonzero(raw_image_8bit[:, 0] != 0)[0]:
            return False
        valid_idx = np.nonzero(raw_image_8bit[:, -1] != BORDER_VALUE)
        if len(valid_idx) != 1:
            return False
        valid_idx = int(valid_idx[0])
        if valid_idx != self._height - 1:  # the different value should be in the bottom of the border
            return False
        return True


def connect_ftdi(vid, pid) -> Ftdi:
    device = _make_device_from_vid_pid(vid, pid)

    usb.util.claim_interface(device, 0)
    usb.util.claim_interface(device, 1)

    ftdi = Ftdi()
    ftdi.open_from_device(device)

    ftdi.set_bitmode(0xFF, Ftdi.BitMode.RESET)
    ftdi.set_bitmode(0xFF, Ftdi.BitMode.SYNCFF)
    return ftdi
