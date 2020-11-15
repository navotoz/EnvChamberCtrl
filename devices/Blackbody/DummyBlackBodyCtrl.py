import logging
import random
from time import sleep

from devices.Blackbody import BlackBodyAbstract
from utils.constants import FAILURE_PROBABILITY_FOR_DUMMIES
from utils.logger import make_logger


# noinspection PyUnusedLocal,PyUnusedLocal,PyUnusedLocal
class BlackBody(BlackBodyAbstract):
    __is_temperature_stable = False
    __fake_temperature = 25.

    def __init__(self, client_ip: str = '10.26.91.56', host_port: int = 5100, client_port: int = 5200,
                 logging_handlers: tuple = (logging.StreamHandler(),), logging_level: int = logging.INFO):
        # raise RuntimeError
        super().__init__(make_logger('DummyBlackBody', logging_handlers, logging_level))

        if random.random() < FAILURE_PROBABILITY_FOR_DUMMIES:
            raise RuntimeError('Dummy BlackBody simulates failure.')
        self._log.info('Ready.')

    def __repr__(self):
        return 'DummyBlackBody'

    def __del__(self):
        pass

    @property
    def temperature(self) -> float:
        return float(self.__fake_temperature)

    @temperature.setter
    def temperature(self, temp: (float, int), wait_for_stable_temperature: bool = True):
        msg = f"Set temperature to {temp}C."
        self._log.info(msg + ' Waiting for stable temperature.' if wait_for_stable_temperature else '')
        self.__fake_temperature = float(temp)
        sleep(random.uniform(0.1, 0.5))
        self._log.info(f"Temperature {temp}C is set.")

    @property
    def bit(self) -> bool:
        return True

    def __call__(self, temperature_to_set: (float, int)):
        """
        The temperature setter as a call function.
        """
        self.temperature = temperature_to_set

    @property
    def is_dummy(self):
        return True
