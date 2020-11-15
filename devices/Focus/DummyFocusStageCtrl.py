import logging
import random
from time import sleep

from utils.constants import FAILURE_PROBABILITY_FOR_DUMMIES
from utils.logger import make_logger, make_logging_handlers


class FocusStage:
    def __init__(self, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        super().__init__()
        self.__log = make_logger('DummyFocusStage', logging_handlers, logging_level)
        self.__fake_position = 0
        if random.random() < FAILURE_PROBABILITY_FOR_DUMMIES:
            raise RuntimeError('Dummy FocusStage simulates failure.')
        self.__log.info('Ready.')

    def __repr__(self):
        return 'DummyFocusStage'

    @property
    def is_positioned(self):
        return True

    @property
    def position(self):
        return self.__fake_position

    @position.setter
    def position(self, position_to_set: float):
        sleep(random.uniform(0.1, 0.5))
        self.__fake_position = position_to_set
        self.__log.info(f"Position {self.__fake_position:.2f}mm.")

    def kill(self):
        return

    def __call__(self, position_to_set: float):
        self.position = position_to_set

    @property
    def is_dummy(self) -> bool:
        return True
