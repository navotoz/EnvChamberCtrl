import usb.core
import usb.util
from pyftdi.ftdi import Ftdi
import binascii
import multiprocessing as mp
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
        self._event_buffer_bigger_than = mp.Event()
        self._event_buffer_bigger_than.clear()
        self._size_to_signal = size_to_signal
        self._flag_run = flag_run

    def wait_for_size(self):
        while not self._event_buffer_bigger_than.wait(timeout=1) and self._flag_run:
            pass
        return len(self._buffer)

    def __del__(self) -> None:
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


class DuplexPipe:
    def __init__(self, conn_send, conn_recv, flag_run):
        self.__recv = conn_recv
        self.__send = conn_send
        self.__flag_run = flag_run

    def send(self, data):
        self.__send.send(data)

    def recv(self):
        while self.__flag_run:
            if self.__recv.poll(timeout=1):
                return self.__recv.recv()


def get_crc(data) -> List[int]:
    crc = struct.pack(len(data) * 'B', *data)
    crc = binascii.crc_hqx(crc, 0)
    crc = [((crc & 0xFF00) >> 8).to_bytes(1, 'big'), (crc & 0x00FF).to_bytes(1, 'big')]
    return list(map(lambda x: int.from_bytes(x, 'big'), crc))


def connect_ftdi(vid, pid) -> Ftdi:
    device = usb.core.find(idVendor=vid, idProduct=pid)
    if not device:
        raise RuntimeError

    if device.is_kernel_driver_active(0):
        device.detach_kernel_driver(0)

    device.reset()
    for cfg in device:
        for intf in cfg:
            if device.is_kernel_driver_active(intf.bInterfaceNumber):
                try:
                    device.detach_kernel_driver(intf.bInterfaceNumber)
                except usb.core.USBError as e:
                    print(f"Could not detach kernel driver from interface({intf.bInterfaceNumber}): {e}")
    device.set_configuration(1)

    usb.util.claim_interface(device, 0)
    usb.util.claim_interface(device, 1)

    ftdi = Ftdi()
    ftdi.open_from_device(device)

    ftdi.set_bitmode(0xFF, Ftdi.BitMode.RESET)
    ftdi.set_bitmode(0xFF, Ftdi.BitMode.SYNCFF)
    return ftdi
