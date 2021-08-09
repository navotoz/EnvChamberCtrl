import binascii
import re
import struct
import threading as th
from typing import List
from utils.tools import SyncFlag

BUFFER_SIZE = int(2e7)  # 20 MBytes


class BytesBuffer:
    def __init__(self, flag_run: SyncFlag, size_to_signal: int = 0) -> None:
        self._buffer = b''
        self._lock = th.Lock()
        self._event_buffer_bigger_than = th.Event()
        self._event_buffer_bigger_than.clear()
        self._size_to_signal = size_to_signal
        self._flag_run = flag_run

    def wait_for_size(self):
        while not self._event_buffer_bigger_than.wait(timeout=1) and self._flag_run:
            pass
        return len(self._buffer)

    def __del__(self) -> None:
        if hasattr(self, '_event_buffer_bigger_than') and isinstance(self._event_buffer_bigger_than, th.Event):
            self._event_buffer_bigger_than.set()

    def clear_buffer(self) -> None:
        with self._lock:
            self._buffer = b''
            self._event_buffer_bigger_than.clear()

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
                if len(self._buffer) >= self._size_to_signal:
                    self._event_buffer_bigger_than.set()
                else:
                    self._event_buffer_bigger_than.clear()

    def sync_uart(self) -> None:
        with self._lock:
            idx_sync = self._buffer.rfind(b'UART')
            if idx_sync != -1:
                self._buffer = self._buffer[idx_sync:]
                if len(self._buffer) >= self._size_to_signal:
                    self._event_buffer_bigger_than.set()
                else:
                    self._event_buffer_bigger_than.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __add__(self, other: bytes):
        with self._lock:
            self._buffer += other
            if len(self._buffer) > BUFFER_SIZE:
                self._buffer = self._buffer[-BUFFER_SIZE:]
            if len(self._buffer) >= self._size_to_signal:
                self._event_buffer_bigger_than.set()
            else:
                self._event_buffer_bigger_than.clear()
            return self._buffer

    def __iadd__(self, other: bytes):
        with self._lock:
            self._buffer += other
            if len(self._buffer) > BUFFER_SIZE:
                self._buffer = self._buffer[-BUFFER_SIZE:]
            if len(self._buffer) >= self._size_to_signal:
                self._event_buffer_bigger_than.set()
            else:
                self._event_buffer_bigger_than.clear()
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


def get_crc(data) -> List[int]:
    crc = struct.pack(len(data) * 'B', *data)
    crc = binascii.crc_hqx(crc, 0)
    crc = [((crc & 0xFF00) >> 8).to_bytes(1, 'big'), (crc & 0x00FF).to_bytes(1, 'big')]
    return list(map(lambda x: int.from_bytes(x, 'big'), crc))
