from collections import deque
from datetime import datetime, timedelta
from time import sleep

import numpy as np
from devices.Oven.PyCampbellCR1000.device import CR1000
from tqdm import tqdm

from devices.Camera.CameraProcess import CameraCtrl
from devices.Oven.OvenProcess import OvenCtrl
from utils.constants import *
from utils.misc import get_time, tqdm_waiting


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


def set_oven_and_settle(setpoint: (float, int), settling_time_minutes: int, oven: OvenCtrl, camera: CameraCtrl) -> None:
    # creates a round-robin queue of differences (dt_camera) to wait until t_camera settles
    queue_temperatures = deque(maxlen=1 + (60 // PID_FREQ_SEC) * settling_time_minutes)
    queue_temperatures.append(camera.fpa)  # -inf so that the diff always returns +inf
    offset = make_temperature_offset(t_next=setpoint, t_oven=oven.temperature(T_FLOOR), t_cam=camera.fpa)
    oven.setpoint = setpoint + offset  # sets the setpoint with the offset of the oven

    # wait until signal error reaches within 1.5deg of setPoint
    initial_wait_time = PID_FREQ_SEC + OVEN_LOG_TIME_SECONDS * 4  # to let the average ErrSignal settle
    tqdm_waiting(initial_wait_time, postfix=f'Initial PID setup time')
    sleep(0.5)
    with tqdm(desc=f'Settling near {oven.temperature(SETPOINT)}C') as progressbar:
        while oven.temperature(SIGNALERROR) >= 1.5:
            progressbar.set_postfix_str(f'Floor temperature {oven.temperature(T_FLOOR):.2f}C, '
                                        f'Signal error {oven.temperature(SIGNALERROR):.2f}')
            sleep(1)
    oven.setpoint = setpoint  # sets the setpoint to the oven
    print(f'Waiting for the Camera to settle near {setpoint:.2f}C', flush=True)
    sleep(1)

    n_minutes_settled = 0
    with tqdm(total=settling_time_minutes, desc=f'Wait for settling {settling_time_minutes} Minutes',
              unit_scale=True, unit_divisor=PID_FREQ_SEC) as progressbar:
        while n_minutes_settled < settling_time_minutes:
            queue_temperatures.append(camera.fpa)
            dt = np.mean(np.diff(queue_temperatures))
            if np.abs(dt) >= 1:
                n_minutes_settled = 0
                progressbar.refresh()
                progressbar.reset()
            else:
                n_minutes_settled += PID_FREQ_SEC / 60
                progressbar.update()
            progressbar.set_postfix_str(f"FPA {queue_temperatures[-1] / 100:.1f}C, "
                                        f"Oven {oven.temperature(T_FLOOR)}, dt {dt / 100:.2f}C")
            sleep(PID_FREQ_SEC)
    sleep(1)
    print(f'Camera temperature {camera.fpa:.2f}C and settled after {n_minutes_settled} minutes.', flush=True)
