from datetime import datetime, timedelta
from time import sleep, time_ns

import numpy as np
from devices.Oven.PyCampbellCR1000.device import CR1000

from utils.constants import *
from utils.misc import get_time


def to_datetime(s: str, fmt: str = '%Y-%m-%d %H:%M:%S'):
    return datetime.strptime(s, fmt)


def get_oven_results(oven: CR1000, start_date: (datetime, None) = None, stop_date: (datetime, None) = None):
    logs = None
    for _ in range(5):
        try:
            logs = oven.get_data(OVEN_TABLE_NAME, start_date=start_date, stop_date=stop_date)
            logs = {k: [d.get(k) for d in logs] for k in {k for d in logs for k in d}}  # reorders the values
            logs = fix_dict_keys(logs)
        except Exception:
            sleep(3)
        finally:
            if logs:
                break
    return logs


def fix_dict_keys(d) -> dict:
    new_dict = {}
    for d_key, val in d.items():
        split = d_key.split('\'')
        new_dict[split[0 if len(split) == 1 else 1]] = val
    return new_dict


def interp_missing_values(res_with_missing_values: list):
    nans, func_nonzero = np.isnan(res_with_missing_values), lambda z: z.nonzero()[0]
    invalids = np.ma.masked_array(res_with_missing_values, mask=nans).compressed()
    indices_nans = func_nonzero(nans)
    indices_ok = func_nonzero(~nans)
    interps_arr = np.interp(indices_nans, indices_ok, invalids)
    for idx_nan, interp_val in zip(indices_nans, interps_arr):
        res_with_missing_values[idx_nan] = interp_val
    return res_with_missing_values


def get_last_measurements(oven) -> (dict, None):
    records = get_oven_results(oven, start_date=get_time() - timedelta(seconds=OVEN_LOG_TIME_SECONDS + 30))
    if records:
        records = {key: val[-1] for key, val in records.items()}
    return records


class MaxTemperatureTimer:
    def __init__(self) -> None:
        self._max_temperature = -float('inf')
        self._time_of_setting = time_ns()

    @property
    def time_since_setting_in_seconds(self) -> int:
        return int((time_ns() - self._time_of_setting) * 1e-9)

    @property
    def time_since_setting_in_minutes(self) -> float:
        return self.time_since_setting_in_seconds / 60

    @property
    def max(self) -> float:
        return self._max_temperature

    @max.setter
    def max(self, new_max_temperature: float) -> None:
        if new_max_temperature > self._max_temperature:
            self._time_of_setting = time_ns()
            self._max_temperature = new_max_temperature


def make_temperature_offset(t_next: float, t_oven: float, t_cam: float) -> float:
    try:
        offset = t_next - max(t_oven, t_cam)
    except TypeError:  # t_cam or t_oven were not yet calculated
        offset = 0
    offset = round(max(0, DELAY_FLOOR2CAMERA_CONST * offset), 1)
    # empirically, MAX_TEMPERATURE_LINEAR_RISE is very slow to get to - around 75C
    if t_next + offset >= MAX_TEMPERATURE_LINEAR_RISE:
        offset = MAX_TEMPERATURE_LINEAR_RISE - t_next
    return offset
