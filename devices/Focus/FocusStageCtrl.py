import logging
import struct
from time import sleep

import serial
import serial.tools.list_ports

from utils.logger import make_logger, make_logging_handlers

ERR_NO_CONN = f'Could not locate the stage. Check if it connected and powered-on.'
SLEEP_BETWEEN_CMD_SEC = 0.1
VID = 0x067B
PID = 0x2303
BAUD_RATE = 115000
FIRST_BYTE = 228
SECOND_BYTE = 165
CMD_MOVE = 1
CMD_KILL = 23
CMD_REPORT = 26
VAR_FPOS = 9
VAR_BUSY = 2010
POSITIONING_ITERS = 81
MSG_FMT_DICT = {CMD_MOVE: ('f', 4), CMD_REPORT: ('H', 2)}


def make_msg(cmd: int, msg: (int, float, None) = None):
    init = [FIRST_BYTE, SECOND_BYTE, 0]
    fmt = '<BBBBB'
    if cmd == CMD_KILL:
        return struct.pack(fmt, *[*init, 1, cmd])
    return struct.pack(fmt + MSG_FMT_DICT[cmd][0], *[*init, 1 + MSG_FMT_DICT[cmd][1], cmd, msg])


def read_msg(msg) -> (str, float, None):
    code = msg[4]
    status = bool(msg[5])
    msg = msg[6:]  # remove init bytes
    if not status:
        return None
    if code == CMD_MOVE:
        return 'OK'
    if code == CMD_REPORT:
        return struct.unpack('f', msg)[0]


class FocusStage:
    def __init__(self, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        super().__init__()
        self.__log = make_logger('FocusStage', logging_handlers, logging_level)

        ports = serial.tools.list_ports.comports()
        ports = filter(lambda x: x.pid is not None and x.vid is not None, ports)
        ports = list(filter(lambda x: x.pid == PID and x.vid == VID, ports))
        if not ports:
            self.__log.critical(ERR_NO_CONN)
            raise RuntimeError(ERR_NO_CONN)

        self.__connection = serial.Serial(ports[0].device, baudrate=BAUD_RATE)
        if self.__is_valid_connection():
            self.__log.info(f"Connected to FocusStage at {self.__connection.name}.")
        else:
            self.__log.critical(ERR_NO_CONN)
            raise RuntimeError(ERR_NO_CONN)

    def __send(self, cmd: bytes) -> bytes:
        self.__connection.write(cmd)
        self.__log.debug(f"send: send {len(cmd)} bytes - {cmd}.")
        return cmd

    def __receive(self) -> (str, None):
        ret_msg, idx, num_of_bytes_to_read = '', 0, 0
        for idx in range(1, 8):
            sleep(SLEEP_BETWEEN_CMD_SEC)
            num_of_bytes_to_read = self.__connection.inWaiting()
            ret_msg = self.__connection.read(num_of_bytes_to_read)
            if ret_msg:
                break
        self.__log.debug(f"receive: {idx} try - read {num_of_bytes_to_read} bytes - \'{ret_msg}\'.")
        return read_msg(ret_msg) if ret_msg else None

    def __is_valid_connection(self) -> bool:
        if self.__connection.is_open:
            self.__connection.timeout = 2  # seconds
            position = self.position
            if position:
                self.__log.debug(f"Initial position is {position:.2f}mm")  # check stage version, to verify connection
                return True
        return False

    def __wait_for_position(self):
        idx = 1
        while not self.is_positioned and idx < POSITIONING_ITERS:
            self.__log.debug(f'{idx} iteration of positioning process.')
            idx += 1
            sleep(0.2)
        if idx >= POSITIONING_ITERS:
            self.__log.error('Could not fix position.')

    @property
    def is_positioned(self):
        self.__send(make_msg(CMD_REPORT, VAR_BUSY))
        return not bool(int(self.__receive()))  # in-position only when NOT busy

    @property
    def position(self):
        msg = make_msg(CMD_REPORT, VAR_FPOS)
        self.__send(msg)
        return self.__receive()

    @position.setter
    def position(self, position_to_set: float):
        delta = abs(position_to_set - self.position)
        if delta > 1e-3:
            msg = make_msg(CMD_MOVE, position_to_set)
            self.__send(msg)
            ret_msg = self.__receive()
            if not ret_msg:
                msg = f'Could not move the stage.'
                self.__log.critical(msg)
                raise RuntimeError(msg)
            self.__wait_for_position()
        else:
            self.__log.debug(f'Position was not changed because delta = {delta:.2g}.')
        self.__log.info(f"Position {self.position:.2f}mm.")

    def kill(self):
        self.__send(make_msg(CMD_KILL))
        self.__receive()

    def __call__(self, position_to_set: float):
        self.position = position_to_set

    @property
    def is_dummy(self):
        return False
