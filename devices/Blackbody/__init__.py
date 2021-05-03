from abc import abstractmethod


class BlackBodyAbstract:
    def __init__(self, logger):
        self._log = logger

    @abstractmethod
    def __del__(self):
        pass

    @abstractmethod
    def echo(self, msg: str = 'echo'):
        pass

    @property
    @abstractmethod
    def temperature(self) -> float:
        pass

    @temperature.setter
    @abstractmethod
    def temperature(self, temperature_to_set: (float, int), wait_for_stable_temperature: bool = True):
        pass

    @property
    @abstractmethod
    def bit(self) -> bool:
        pass

    @abstractmethod
    def __call__(self, temperature_to_set: (float, int)):
        pass

    @property
    @abstractmethod
    def is_dummy(self):
        pass
