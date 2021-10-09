import pickle
from pathlib import Path

import numpy as np
from collections import deque
from time import sleep, time_ns

from tqdm import tqdm

from devices.Camera.CameraProcess import CameraCtrl, TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS
from devices.Oven.OvenProcess import OvenCtrl
from devices.Oven.utils import make_temperature_offset
from utils.constants import SIGNALERROR, PID_FREQ_SEC, OVEN_LOG_TIME_SECONDS, T_FLOOR
from utils.misc import tqdm_waiting


def set_oven_and_settle(setpoint: (float, int), settling_time_minutes: int, oven: OvenCtrl, camera: CameraCtrl) -> None:
    initial_wait_time = PID_FREQ_SEC + OVEN_LOG_TIME_SECONDS * 4  # to let the average ErrSignal settle

    # creates a round-robin queue of differences (dt_camera) to wait until t_camera settles
    queue_temperatures = deque(maxlen=1 + (60 // PID_FREQ_SEC) * settling_time_minutes)
    queue_temperatures.append(-float('inf'))  # -inf so that the diff always returns +inf
    offset = make_temperature_offset(t_next=setpoint, t_oven=oven.temperature(T_FLOOR), t_cam=camera.fpa)
    oven.setpoint = setpoint + offset  # sets the setpoint with the offset of the oven

    # wait until signal error reaches within 1.5deg of setPoint
    tqdm_waiting(initial_wait_time, postfix=f'Waiting for PID to settle near {setpoint + offset}C')
    sleep(0.5)
    while oven.temperature(SIGNALERROR) >= 1.5:
        sleep(1)
    oven.setpoint = setpoint  # sets the setpoint to the oven

    print(f'Waiting for the Camera to settle near {setpoint:.2f}C', flush=True)
    n_minutes_settled = 0
    with tqdm(total=settling_time_minutes, desc=f'Wait for settling') as progressbar:
        while n_minutes_settled > settling_time_minutes:
            queue_temperatures.append(camera.fpa)
            if np.mean(np.diff(queue_temperatures)) >= 1e-2:
                n_minutes_settled = 0
                progressbar.refresh()
                progressbar.reset()
            else:
                n_minutes_settled += PID_FREQ_SEC / 60
            progressbar.set_postfix_str(f"FPA{queue_temperatures[0]:.1f} "
                                        f"{n_minutes_settled:.2f}|{settling_time_minutes:3d}Min")
            sleep(PID_FREQ_SEC)
    sleep(0.5)
    print(f'Camera temperature {camera.fpa:.2f}C and settled after {n_minutes_settled} minutes.', flush=True)








def th_plot_realtime():
    raise NotImplementedError


class PlotterProc(mp.Process):
    def __init__(self, flag_run, event_timer, output_path: (str, Path)):
        super(PlotterProc, self).__init__()
        self._event_timer = event_timer
        self._event_timer.set()
        self._flag_run = flag_run
        self._output_path = Path(output_path) / PLOTS_PATH / 'oven'
        self._records_path = Path(output_path) / const.OVEN_RECORDS_FILENAME

    def run(self) -> None:
        th_timer = th.Thread(target=self._timer, name='th_proc_plotter_timer', daemon=True)
        th_timer.start()
        while self._flag_run:
            try:
                self._event_timer.wait()
                check_and_make_path(self._output_path)
                plot_oven_records_in_path(self._records_path, self._output_path)
            except Exception as err:
                print(f'Records collection failed - {err}')
                pass
            self._event_timer.clear()
        try:
            th_timer.join()
        except (RuntimeError, AssertionError, AttributeError):
            pass

    def __del__(self):
        self.terminate()

    def terminate(self) -> None:
        if hasattr(self, '_flag_run'):
            self._flag_run.set(False)
        try:
            self._event_timer.set()
        except (RuntimeError, AssertionError, AttributeError, TypeError):
            pass
        try:
            self.kill()
        except (RuntimeError, AssertionError, AttributeError, TypeError):
            pass

    def _timer(self):
        while self._flag_run:
            self._event_timer.set()
            sleep(OVEN_LOG_TIME_SECONDS)
        self._event_timer.set()



