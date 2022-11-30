import logging
from time import sleep
from ctypes import c_int16
import serial
import serial.tools.list_ports

from devices import DeviceAbstract
from utils.logger import make_logger, make_logging_handlers
import multiprocessing as mp
import threading as th


RECV_ITERS = 8
SLEEP_BETWEEN_CMD_SEC = 1
STEPS_PER_REVOLUTION = 400
DEG_PER_STEP = 0.9  # in degrees
BELT_RATIO = 16 / 72


class Scanner(DeviceAbstract):
    def _run(self):
        self._workers_dict['connect'] = th.Thread(target=self._th_connect, name='th_scanner_conn', daemon=False)
        self._workers_dict['move'] = th.Thread(target=self._th_move, name='th_scanner_move', daemon=True)

    def _terminate_device_specifics(self) -> None:
        try:
            self._flag_run.set(False)
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self.__connection.close()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass

    def __init__(self, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        super().__init__()
        self.__log = make_logger('Scanner', logging_handlers, logging_level)
        self._lock = th.Lock()
        self._n_steps: mp.Value = mp.Value(typecode_or_type=c_int16)
        self._pos: mp.Value = mp.Value(typecode_or_type=c_int16)
        self._limit_left: mp.Value = mp.Value(typecode_or_type=c_int16)
        self._limit_left.value = -2000
        self._limit_right: mp.Value = mp.Value(typecode_or_type=c_int16)
        self._limit_right.value = 2000
        self._semaphore_move = mp.Semaphore(0)
        self._event_limit = mp.Event()
        self._event_limit.clear()

    def _th_connect(self, baud=115200):
        ports = serial.tools.list_ports.comports()
        ports = filter(lambda x: x.manufacturer is not None, ports)
        ports = [p for p in ports if 'arduino' in p.manufacturer.lower()]
        if not ports:
            self.__log.critical("Couldn't locate an arduino.")
            raise RuntimeError("Couldn't locate an arduino.")

        self.__connection = serial.Serial(ports[0].device, baudrate=baud)
        if self.__is_valid_connection():
            self.__log.info(f"Connected to Scanner at {self.__connection.name}.")
        else:
            self.__log.critical("Couldn't open connection to the arduino.")
            raise RuntimeError("Couldn't open connection to the arduino.")

    def move(self, num_of_steps: int):
        self._n_steps.value = num_of_steps
        self._semaphore_move.release()

    def _th_move(self):
        self.__log.info('Started Thread Move')
        while self._flag_run:
            self._semaphore_move.acquire()
            n_steps = self._n_steps.value
            self.__log.info(f"Move {n_steps} steps.")
            with self._lock:
                if n_steps > 0 and self._pos.value + n_steps < self._limit_right.value:
                    self._event_limit.clear()
                    self.__move(n_steps)
                    self._pos.value = self._pos.value + n_steps
                elif n_steps < 0 and self._pos.value + n_steps > self._limit_left.value:
                    self._event_limit.clear()
                    self.__move(n_steps)
                    self._pos.value = self._pos.value + n_steps
                else:
                    self._event_limit.set()
                    self.__log.warning(f"Move {n_steps} steps is out of limits.")

    def __send(self, cmd: str) -> bytes:
        cmd = (cmd if cmd.endswith('\n') else f"{cmd}\n").encode('UTF-8')
        self.__connection.write(cmd)
        self.__log.debug(f"send: send {len(cmd)} bytes - {cmd}.")
        return cmd

    def __receive(self) -> str:
        ret_msg, idx, num_of_bytes_to_read = '', 0, 0
        for idx in range(1, RECV_ITERS):
            sleep(SLEEP_BETWEEN_CMD_SEC)
            num_of_bytes_to_read = self.__connection.inWaiting()
            ret_msg = self.__connection.read(num_of_bytes_to_read).decode('UTF-8')
            if ret_msg:
                break
        self.__log.debug(f"receive: {idx} try - read {num_of_bytes_to_read} bytes - \'{ret_msg}\'.")
        return ret_msg

    def __is_valid_connection(self) -> bool:
        if self.__connection.is_open:
            self.__log.debug('Connection is open.')
            self.__connection.timeout = 1  # seconds
            self.__receive().lower()  # check for the connection handshake "OK"
            send_msg = self.__send('ECHO')
            self.__log.debug(f"is_valid_connection: send {send_msg} test.")
            ret_msg = self.__receive().lower()
            self.__log.debug(f"is_valid_connection: recv \'{ret_msg}\' ECHO test.")
            return 'ok' in ret_msg
        return False

    def __move(self, num_of_steps: int) -> None:
        self.__send(f"{num_of_steps}\n")
        self.__log.info(f"Move {num_of_steps} steps.")

    def set_limit(self, pos):
        if pos == 'left':
            self._pos.value = 0
            self._limit_left.value = 0
            self.__log.info(f"Set limit left")
        elif pos == 'right':
            self._limit_right.value = self._pos.value
            self.__log.info(f"Set limit right to {self._limit_right.value}")
        else:
            raise ValueError(f"Invalid position {pos}")

    def move_between_limits(self, *args, **kwargs):
        direction = -1
        while self._flag_run:
            while not self._event_limit.is_set():
                self.move(direction)
                sleep(0.06)  # prevent slipping of the motor
            direction *= -1
            self._event_limit.clear()

