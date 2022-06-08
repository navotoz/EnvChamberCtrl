from abc import abstractmethod

import numpy as np


@abstractmethod
class TbbGenAbs:
    def __init__(self, *, bb_min: int, bb_max: int):
        if not 10 <= bb_max <= 70:
            raise ValueError(f'blackbody_max must be in [10, 70], got {bb_max}')
        if not 10 <= bb_min <= 70:
            raise ValueError(f'blackbody_min must be in [10, 70], got {bb_min}')
        self.bb_min = bb_min
        self.bb_max = bb_max

    def __iter__(self):
        return self

    @abstractmethod
    def __next__(self):
        raise NotImplementedError


class TbbGenSawTooth(TbbGenAbs):
    def __init__(self, *, bb_min: int, bb_max: int, bb_inc: int, bb_start: int = None, bb_is_decreasing: bool = False):
        super(TbbGenSawTooth, self).__init__(bb_min=bb_min, bb_max=bb_max)
        if bb_inc >= abs(bb_max - bb_min):
            raise ValueError(f'blackbody_increments must be bigger than abs(max-min) of the Blackbody.')
        if bb_start is not None and not bb_min <= bb_start <= bb_max:
            raise ValueError(f'blackbody_start must be inside the range of the Blackbody.')
        if not 0.1 <= bb_inc <= 10:
            raise ValueError(f'blackbody_increments must be in [0.1, 10], got {bb_inc}')
        self.bb_inc = bb_inc
        self._direction = 'down' if bb_is_decreasing else 'up'
        if bb_start is not None:
            if self._direction == 'up':
                self._current = max(bb_start - bb_inc, bb_min)
            elif self._direction == 'down':
                self._current = min(bb_start + bb_inc, bb_max)
        else:
            self._current = bb_max + bb_inc if bb_is_decreasing else bb_min - bb_inc

    def __next__(self):
        if self._direction == 'up':
            self._current += self.bb_inc
            if self._current <= self.bb_max:
                return self._current
            elif self._current > self.bb_max:
                self._direction = 'down'
                self._current -= 2 * self.bb_inc
                return self._current
        elif self._direction == 'down':
            self._current -= self.bb_inc
            if self._current >= self.bb_min:
                return self._current
            elif self._current < self.bb_min:
                self._direction = 'up'
                self._current += 2 * self.bb_inc
                return self._current
        else:
            raise ValueError(f'Direction must be either "up" or "down", got {self._direction}')


class TbbGenRand(TbbGenAbs):
    def __init__(self, *, bb_min: int, bb_max: int, bins: int, resolution: int = 10):
        super(TbbGenRand, self).__init__(bb_min=bb_min, bb_max=bb_max)
        bb_min = int(bb_min * resolution)
        bb_max = int(bb_max * resolution)
        bb_temperatures = np.random.randint(low=min(bb_min, bb_max), high=max(bb_min, bb_max),
                                            size=abs(bb_max - bb_min))
        bb_temperatures = bb_temperatures.astype('float') / resolution  # float for the bb
        while True:
            try:
                bb_temperatures = bb_temperatures.reshape(len(bb_temperatures) // bins, bins)
                bb_temperatures = np.sort(bb_temperatures, axis=1)
                for idx in range(1, bb_temperatures.shape[0], 2):
                    bb_temperatures[idx] = np.flip(bb_temperatures[idx])
                bb_temperatures = bb_temperatures.ravel()
                break
            except ValueError:
                bins += 1
        self._list_tbb = list(bb_temperatures)

    def __next__(self):
        try:
            return self._list_tbb.pop(0)
        except IndexError:
            return None
