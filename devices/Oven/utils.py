from datetime import datetime, timedelta
from time import sleep

from devices.Oven.PyCampbellCR1000.device import CR1000

from utils.constants import *
from utils.misc import get_time


def get_oven_results(oven: CR1000, start_date: (datetime, None) = None, stop_date: (datetime, None) = None):
    logs = None
    for _ in range(5):
        try:
            logs = oven.get_data(OVEN_TABLE_NAME, start_date=start_date, stop_date=stop_date)
            logs = {k: [d.get(k) for d in logs] for k in {k for d in logs for k in d}}  # reorders the values
            logs = fix_dict_keys(logs)
        except (AttributeError, IndexError, NameError, RuntimeError, KeyError, ValueError, TypeError):
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


def get_last_measurements(oven) -> (dict, None):
    records = get_oven_results(oven, start_date=get_time() - timedelta(seconds=OVEN_LOG_TIME_SECONDS + 30))
    if records:
        records = {key: val[-1] for key, val in records.items()}
    return records


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
