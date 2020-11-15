import logging
import random
from time import sleep

from utils.constants import FAILURE_PROBABILITY_FOR_DUMMIES
from utils.logger import make_logger, make_logging_handlers

RECV_ITERS = 8
SLEEP_BETWEEN_CMD_SEC = 1
STEPS_PER_REVOLUTION = 400
DEG_PER_STEP = 0.9  # in degrees
BELT_RATIO = 16 / 72


class Scanner:
    # noinspection PyUnusedLocal
    def __init__(self, baud=19200, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        super().__init__()
        self.__log = make_logger('DummyScanner', logging_handlers, logging_level)
        if random.random() < FAILURE_PROBABILITY_FOR_DUMMIES:
            raise RuntimeError('Dummy Scanner simulates failure.')
        self.__log.info(f"Dummy Scanner On.")

    def __repr__(self):
        return "DummyScanner"

    def move(self, num_of_steps: int) -> bool:
        num_of_steps_to_move = num_of_steps
        self.__log.info(f'Moved {num_of_steps}.')
        sleep(random.uniform(0.2, 0.5))
        return int(num_of_steps_to_move) == num_of_steps

    def __set_zero_position(self):
        pass

    def __set_limits(self):
        pass

    def __call__(self, num_of_steps: int):
        self.move(num_of_steps)

    @property
    def is_dummy(self):
        return True
