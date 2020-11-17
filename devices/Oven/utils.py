import csv
import multiprocessing as mp
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from tkinter import Frame

import numpy as np

from devices.Oven.PyCampbellCR1000.device import CR1000
from gui.utils import get_spinbox_value
from utils.constants import *
from utils.tools import get_time, wait_for_time


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


def collect_oven_records(oven, logger, path_to_log: Path, frame: Frame, oven_keys: (list, tuple),
                         is_real_camera: bool) -> bool:
    get = wait_for_time(func=get_last_measurements, wait_time_in_nsec=OVEN_LOG_TIME_SECONDS * 1e9)
    records = get(oven)
    if not records:
        with open(path_to_log, 'r') as fp_csv:
            reader_csv = csv.reader(fp_csv)
            rows = list(reader_csv)
        records = dict().fromkeys(rows[0])
        if rows[0] == rows[-1]:  # there are only keys in the csv file
            return False
        records = {key: val for key, val in zip(records.keys(), rows[-1])}
        records[DATETIME] = str(to_datetime(records[DATETIME]) + timedelta(seconds=OVEN_LOG_TIME_SECONDS))
        logger.debug('Failed to get records, using previous records.')
    if is_real_camera:
        for t_type in [T_FPA, T_HOUSING]:
            while (t := frame.getvar(t_type)) is None:
                pass
            records[t_type] = float(t)
    records = {key: val for key, val in records.items() if key in oven_keys}
    for key in [CTRLSIGNAL, 'dInputKd', 'sumErrKi', f'{SIGNALERROR}Kp', 'dInput', 'sumErr', f'{SIGNALERROR}']:
        try:
            records[f"{key}_Avg"] = 0 if records[SETPOINT] <= 0 else records[f"{key}_Avg"]
        except (IndexError, KeyError, TypeError):
            pass
    with open(path_to_log, 'a') as fp_csv:
        writer_csv = csv.writer(fp_csv)
        writer_csv.writerow([records[key] for key in oven_keys])
    logger.debug("Added a line to the oven logs.")
    return True


def get_last_measurements(oven) -> (dict, None):
    records = get_oven_results(oven, start_date=get_time() - timedelta(seconds=OVEN_LOG_TIME_SECONDS + 30))
    if records:
        records = {key: val[-1] for key, val in records.items()}
    return records


def get_n_experiments(frame: Frame) -> int:
    return int(frame.getvar(ITERATIONS_IN_TEMPERATURE))


def make_oven_temperatures_list(current_temperature: float = -float('inf')) -> tuple:
    lower_bound = int(get_spinbox_value(OVEN_NAME + MIN_STRING))
    upper_bound = int(get_spinbox_value(OVEN_NAME + MAX_STRING))
    increment = int(get_spinbox_value(OVEN_NAME + INC_STRING))
    temperatures = list(range(lower_bound, upper_bound, increment))
    temperatures.append(upper_bound) if temperatures and temperatures[-1] != upper_bound else None
    try:
        return tuple(temperatures)[min(np.nonzero([t > current_temperature for t in temperatures])[0]):]
    except ValueError:
        return tuple()


class VariableLengthDeque:
    def __init__(self, maxlen: int):
        self._deque = deque(maxlen=maxlen)
        self._lock = mp.Lock()

    def append(self, value: (float, int)) -> None:
        with self._lock:
            self._deque.append(value)

    @property
    def maxlen(self):
        with self._lock:
            return self._deque.maxlen

    @maxlen.setter
    def maxlen(self, new_len: int):
        new_len = int(new_len)
        with self._lock:
            if new_len == self._deque.maxlen:
                return
            elif new_len > self._deque.maxlen:
                new_deque = deque(maxlen=new_len)
                new_deque.extend(self._deque)
            elif new_len < self._deque.maxlen:
                new_deque = deque(maxlen=new_len)
                [new_deque.append(x) for x in list(self._deque)]
            self._deque = new_deque

    def __iter__(self):
        with self._lock:
            return self._deque.__iter__()
