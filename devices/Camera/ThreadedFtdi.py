import binascii
import re
import struct
from threading import Thread, Lock, Event
from time import sleep
from typing import List

from pyftdi.ftdi import Ftdi
from pyftdi.ftdi import FtdiError

from devices.Camera.tau2_config import Code
from utils.logger import make_logger

BUFFER_SIZE = int(1e7)  # 10 MBytes
FTDI_PACKET_SIZE = 512 * 8
SYNC_MSG = b'SYNC' + struct.pack(4 * 'B', *[0, 0, 0, 0])
MAGIC_IMAGE_ENDING = 0x0ff0  # ?????????????


class BytesBuffer:
    def __init__(self) -> None:
        self._buffer = b''
        self._lock = Lock()

    def __del__(self):
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


class FtdiIO:
    def __init__(self, ftdi: (Ftdi, None), frame_size: int, logging_handlers: (list, tuple), logging_level: int):
        if not ftdi:
            raise RuntimeError('Error in FTDI.')
        self._log = make_logger('FtdiIO', logging_handlers, logging_level)
        self.ftdi = ftdi
        self._frame_size = frame_size
        self._lock_access = Lock()
        self._event_get_image = Event()
        self._event_get_image.set()
        self._event_read = Event()
        self._event_read.clear()
        self._buffer = BytesBuffer()
        self.thread_read = Thread(target=self._func_reader_thread, name='th_tau2grabber_reader', daemon=True)
        sleep(0.2)
        self.thread_read.start()
        self._log.info('Ready.')

    def reset(self) -> None:
        self.ftdi.set_bitmode(0xFF, Ftdi.BitMode.RESET)
        self.ftdi.set_bitmode(0xFF, Ftdi.BitMode.SYNCFF)
        self._buffer.clear_buffer()
        self._event_get_image.set()
        self._event_read.clear()
        self._log.debug('Reset.')

    def _func_reader_thread(self) -> None:
        while True:
            if self._event_read.is_set():
                with self._lock_access:
                    data = self.ftdi.read_data(FTDI_PACKET_SIZE)
                self._buffer += data

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

    def write(self, data: bytes, to_start_reading: bool = True) -> None:
        self._event_get_image.wait()
        buffer = b"UART"
        buffer += int(len(data)).to_bytes(1, byteorder='big')  # doesn't matter
        buffer += data
        self._event_read.set() if to_start_reading else None
        sleep(0.01) if to_start_reading else None
        with self._lock_access:
            try:
                self.ftdi.write_data(buffer)
                self._log.debug(f"Send {data}")
            except FtdiError:
                self._log.debug('Write error.')
                self.reset()
        sleep(0.2) if to_start_reading else None

    def parse(self, data: bytes, command: Code, n_retries: int = 3) -> (bytes, None):
        self._event_get_image.wait()
        for _ in range(n_retries):
            if res := self._parse_func(command):
                self._event_read.clear()
                self._buffer.clear_buffer()
                self._log.debug(f"Recv {res}")
                return res
            self._log.debug('Could not parse, retrying..')
            self.write(SYNC_MSG)
            self.write(data)
        return None

    def get_image(self) -> bytes:
        self._event_read.set()
        self._event_get_image.clear()
        self._buffer.sync_teax()
        while len(self._buffer) < self._frame_size:
            continue
        res = self._buffer[:self._frame_size]
        self._event_get_image.set()
        self._log.debug('Grabbed Image')
        return res


def get_crc(data) -> List[int]:
    crc = struct.pack(len(data) * 'B', *data)
    crc = binascii.crc_hqx(crc, 0)
    crc = [((crc & 0xFF00) >> 8).to_bytes(1, 'big'), (crc & 0x00FF).to_bytes(1, 'big')]
    return list(map(lambda x: int.from_bytes(x, 'big'), crc))
