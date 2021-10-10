import matplotlib.pyplot as plt
import matplotlib.animation as animation
import multiprocessing as mp
import pickle
from pathlib import Path

import numpy as np
from collections import deque
from time import sleep, time_ns

from tqdm import tqdm

from devices.Camera.CameraProcess import CameraCtrl, TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS
from devices.Oven.OvenProcess import OvenCtrl
from devices.Oven.plots import plot_oven_records_in_path
from devices.Oven.utils import make_temperature_offset
from utils.constants import SIGNALERROR, PID_FREQ_SEC, OVEN_LOG_TIME_SECONDS, T_FLOOR, SETPOINT
from utils.misc import tqdm_waiting


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


def plot_realtime(path_to_records: (str, Path)):
    def animate(i, xs, ys):
        ax.clear()
        plot_oven_records_in_path(path_to_records, None)

    path_to_records = Path(path_to_records)
    if not path_to_records.is_file():
        raise RuntimeError(f'No records file was found at {str(path_to_records)}.')

    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)

    ani = animation.FuncAnimation(fig, animate, fargs=(None, None), interval=1000)
    plt.show()
    return ani
