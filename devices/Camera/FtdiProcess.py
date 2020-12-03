import usb.core
import usb.util
import binascii
import re
import struct
import threading as th
import multiprocessing as mp
from multiprocessing.connection import Connection
from time import sleep
from typing import List
import numpy as np
from pyftdi.ftdi import Ftdi
from pyftdi.ftdi import FtdiError

from devices.Camera.tau2_config import Code
from gui.utils import SyncFlag
from utils.logger import make_logger

BUFFER_SIZE = int(3e7)  # 30 MBytes
FTDI_PACKET_SIZE = 512 * 8
SYNC_MSG = b'SYNC' + struct.pack(4 * 'B', *[0, 0, 0, 0])
MAGIC_IMAGE_ENDING = 0x0ff0  # ?????????????
N_RETRIES = 3

class BytesBuffer:
    def __init__(self) -> None:
        self._buffer = b''
        self._lock = th.Lock()

    def __del__(self) -> None:
        pass

    def clear_buffer(self) -> None:
        with self._lock:
            self._buffer = b''

    def rfind(self, substring: bytes) -> int:
        with self._lock:
            return self._buffer.rfind(substring)

    def find(self, substring: bytes) -> int:
        with self._lock:
            return self._buffer.find(substring)

    def sync_teax(self) -> None:
        with self._lock:
            idx_sync = self._buffer.rfind(b'TEAX')
            if idx_sync != -1:
                self._buffer = self._buffer[idx_sync:]

    def sync_uart(self) -> None:
        with self._lock:
            idx_sync = self._buffer.rfind(b'UART')
            if idx_sync != -1:
                self._buffer = self._buffer[idx_sync:]

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __add__(self, other: bytes):
        with self._lock:
            self._buffer += other
            if len(self._buffer) > BUFFER_SIZE:
                self._buffer = self._buffer[-BUFFER_SIZE:]
            return self._buffer

    def __iadd__(self, other: bytes):
        with self._lock:
            self._buffer += other
            if len(self._buffer) > BUFFER_SIZE:
                self._buffer = self._buffer[-BUFFER_SIZE:]
            return self

    def __getitem__(self, item: slice) -> bytes:
        with self._lock:
            if isinstance(item, slice):
                return self._buffer[item]

    def __call__(self) -> bytes:
        with self._lock:
            return self._buffer


def generate_subsets_indices_in_string(input_string: (BytesWarning, bytes, bytes, map, filter),
                                       subset: (bytes, str)) -> list:
    reg = re.compile(subset)
    if isinstance(input_string, BytesBuffer):
        return [i.start() for i in reg.finditer(input_string())]
    return [i.start() for i in reg.finditer(input_string)]


def generate_overlapping_list_chunks(generator: (map, filter), n: int):
    lst = list(generator)
    subset_generator = map(lambda idx: lst[idx:idx + n], range(len(lst)))
    return filter(lambda sub: len(sub) == n, subset_generator)


class FtdiIO(mp.Process):
    _thread_read =_thread_parse=_thread_image= None

    def __init__(self, vid, pid, cmd_recv:Connection, cmd_send:Connection,
                 image_recv:Connection, image_send:Connection,
                 frame_size: int, flag_run: SyncFlag, logging_handlers: (list, tuple),
                 logging_level: int):
        super().__init__()
        self._log = make_logger('FtdiIO', logging_handlers, logging_level)
        self._dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self._dev:
            self._connect()
        else:
            raise RuntimeError('Could not connect to the Tau2 camera.')

        self._flag_run = flag_run
        self._frame_size = frame_size
        self._lock_access = th.Lock()
        self._semaphore_access_ftdi = th.Semaphore(value=1)
        self._event_allow_ftdi_access = th.Event()
        self._event_allow_ftdi_access.set()
        self._event_read = th.Event()
        self._event_read.clear()
        self._buffer = BytesBuffer()
        self._cmd_recv, self._image_recv = cmd_recv, image_recv
        self._cmd_send, self._image_send = cmd_send, image_send

    def run(self) -> None:
        self._log.info('Ready.')
        self._thread_read = th.Thread(target=self._th_reader_func, name='th_tau2grabber_reader', daemon=False)
        self._thread_read.start()
        self._thread_parse = th.Thread(target=self._th_parse_func, name='th_tau2grabber_parser', daemon=False)
        self._thread_parse.start()
        self._thread_image = th.Thread(target=self._th_image_func, name='th_tau2grabber_image', daemon=False)
        self._thread_image.start()

        self._thread_read.join()
        self._thread_image.join()
        self._thread_parse.join()
        self._ftdi.close()

    def __del__(self) -> None:
        self._flag_run.set(False)
        self._cmd_send.send(True)
        self._image_send.send(True)
        self._event_allow_ftdi_access.set()
        self._thread_read.join()
        self._thread_image.join()
        self._thread_parse.join()
        self._ftdi.close()

    def _connect(self) -> None:
        if self._dev.is_kernel_driver_active(0):
            self._dev.detach_kernel_driver(0)

        self._claim_dev()

        self._ftdi = Ftdi()
        self._ftdi.open_from_device(self._dev)

        self._ftdi.set_bitmode(0xFF, Ftdi.BitMode.RESET)
        self._ftdi.set_bitmode(0xFF, Ftdi.BitMode.SYNCFF)

    def _claim_dev(self):
        self._dev.reset()
        self._release()

        self._dev.set_configuration(1)

        usb.util.claim_interface(self._dev, 0)
        usb.util.claim_interface(self._dev, 1)

    def _release(self):
        for cfg in self._dev:
            for intf in cfg:
                if self._dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    try:
                        self._dev.detach_kernel_driver(intf.bInterfaceNumber)
                    except usb.core.USBError as e:
                        print("Could not detach kernel driver from interface({0}): {1}".format(intf.bInterfaceNumber,
                                                                                               str(e)))

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
        data = command, n_retry = None, 1
        while self._flag_run:
            while self._flag_run:
                if self._cmd_recv.poll(timeout=1):
                    data, command, n_retry = self._cmd_recv.recv()
                    break
            if not data or not command or not self._flag_run:
                break
            self._event_allow_ftdi_access.wait()
            res = None
            with self._semaphore_access_ftdi:
                self._event_read.set()
                self._write(data)
                sleep(0.2)
                for _ in range(max(1, n_retry)):
                    if not self._flag_run:
                        break
                    if res := self._parse_func(command):
                        self._event_read.clear()
                        self._buffer.clear_buffer()
                        self._log.debug(f"Recv {res}")
                        break
                    self._log.debug('Could not parse, retrying..')
                    self._write(SYNC_MSG)
                    self._write(data)
                    sleep(0.1)
                self._cmd_send.send(res)

    def _th_image_func(self) -> None:
        while self._flag_run:
            while self._flag_run:
                if self._image_recv.poll(timeout=1):
                    _ = self._image_recv.recv()
                    break
            self._event_allow_ftdi_access.clear()
            with self._semaphore_access_ftdi:
                self._event_read.set()
                self._buffer.sync_teax()
                while (buffer_len := len(self._buffer)) < self._frame_size and self._flag_run:
                    continue
                res = self._buffer[:min(self._frame_size, buffer_len)]
                self._event_allow_ftdi_access.set()
                self._log.debug('Grabbed Image')
                self._image_send.send(res)


def get_crc(data) -> List[int]:
    crc = struct.pack(len(data) * 'B', *data)
    crc = binascii.crc_hqx(crc, 0)
    crc = [((crc & 0xFF00) >> 8).to_bytes(1, 'big'), (crc & 0x00FF).to_bytes(1, 'big')]
    return list(map(lambda x: int.from_bytes(x, 'big'), crc))
