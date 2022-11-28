import logging
from time import sleep

import serial
import serial.tools.list_ports

from utils.logger import make_logger, make_logging_handlers

RECV_ITERS = 8
SLEEP_BETWEEN_CMD_SEC = 1
STEPS_PER_REVOLUTION = 400
DEG_PER_STEP = 0.9  # in degrees
BELT_RATIO = 16 / 72


class Scanner:
    def __init__(self, baud=19200, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        super().__init__()
        self.__log = make_logger('Scanner', logging_handlers, logging_level)

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
        self._pos = 0
        self._left_limit = -float('inf')
        self._right_limit = float('inf')
        self._direction = 'left'

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

    def __move(self, num_of_steps: int) -> bool:
        self.__send(f"{num_of_steps}\n")
        self.__log.info(f"Move {num_of_steps} steps.")
        num_of_steps_to_move = self.__receive()
        return int(num_of_steps_to_move) == num_of_steps

    def __set_zero_position(self):
        pass

    def __call__(self, num_of_steps: int):
        if self._pos + num_of_steps < self._right_limit and self._pos - num_of_steps > self._left_limit:
            self.__move(num_of_steps)
            self._pos += num_of_steps
        else:
            raise RuntimeError(f"Reached limit")

    def set_right_limit(self):
        self._right_limit = self._pos

    def set_left_limit(self):
        self._pos = 0
        self._left_limit = 0

    def move_between_limits(self):
        direction = -1 if self._direction == 'left' else 1
        try:
            while True:
                self(direction)
        except RuntimeError:
            self._direction = 'right' if self._direction == 'left' else 'left'
