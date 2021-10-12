import multiprocessing as mp
import threading as th
from collections import deque
from pathlib import Path
from time import sleep, time_ns

import numpy as np
import pandas as pd
from devices.Oven.PyCampbellCR1000.device import CR1000
from devices.Oven.PyCampbellCR1000.exceptions import NoDeviceException
from serial import SerialException, SerialTimeoutException
from serial.tools.list_ports import comports
from tqdm import tqdm

from devices import DeviceAbstract
from devices.Camera.CameraProcess import CameraCtrl
from devices.Oven.utils import get_last_measurements, make_temperature_offset
from utils.constants import *
from utils.logger import make_logging_handlers
from utils.misc import tqdm_waiting, get_time

OVEN_RECORDS_FILENAME = 'oven_records.csv'


def make_oven(logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = 20):
    list_ports = comports()
    list_ports = list(filter(lambda x: 'serial' in x.description.lower() and 'usb' in x.device.lower(), list_ports))
    try:
        oven = CR1000.from_url(f'serial:{list_ports[0].device}:115200',
                               logging_handlers=logging_handlers, logging_level=logging_level)
    except (IndexError, RuntimeError, SerialException, SerialTimeoutException):
        raise RuntimeError
    oven.settime(get_time())
    return oven


def make_oven_dummy(logging_handlers: tuple = (), logging_level: int = 20):
    from devices.Oven.PyCampbellCR1000.DummyOven import CR1000
    return CR1000(None, logging_handlers=logging_handlers, logging_level=logging_level)


class OvenCtrl(DeviceAbstract):
    _oven = make_oven_dummy()
    _output_path = _records_path = None

    def __init__(self, logfile_path: (str, Path), output_path: (str, Path)):
        super(OvenCtrl, self).__init__()

        # sync objects
        self._event_connected = mp.Event()
        self._event_connected.clear()
        self._semaphore_setpoint = mp.Semaphore(value=0)
        self._semaphore_collect = mp.Semaphore(value=0)

        # paths
        self._output_path = Path(output_path)
        if not self._output_path.is_dir():
            self._output_path.mkdir(parents=True)
        self._records_path = self._output_path / OVEN_RECORDS_FILENAME

        self._logging_handlers = make_logging_handlers(logfile_path=logfile_path)
        _mp_manager = mp.Manager()
        self._temperatures = _mp_manager.dict()
        self._temperatures[T_FLOOR] = 0.0
        self._temperatures[T_INSULATION] = 0.0
        self._temperatures[T_CAMERA] = 0.0
        self._temperatures[T_FPA] = 0.0
        self._temperatures[T_HOUSING] = 0.0
        self._temperatures[SIGNALERROR] = 0.0
        self._temperatures[SETPOINT] = 0.0

    def _run(self):
        self._workers_dict['conn'] = th.Thread(target=self._th_connect, name='oven_conn', daemon=True)
        self._workers_dict['getter'] = th.Thread(target=self._th_getter, name='oven_getter', daemon=True)
        self._workers_dict['collector'] = th.Thread(target=self._th_collect_records, name='oven_collect', daemon=False)
        self._workers_dict['timer'] = th.Thread(target=self._th_timer, name='oven_timer', daemon=True)
        self._workers_dict['setter_setpoint'] = th.Thread(target=self._th_setter_setpoint,
                                                          name='oven_setter_setpoint', daemon=True)

    def _th_connect(self):
        while self._flag_run:
            try:
                self._oven = make_oven(self._logging_handlers)
                self._getter_temperature()
                self._semaphore_collect.release()
                self._event_connected.set()
                return
            except (RuntimeError, AttributeError, IndexError, ValueError):
                pass
            sleep(5)

    def _getter_temperature(self):
        try:
            for t in [T_FLOOR, T_INSULATION, T_CAMERA, SIGNALERROR]:
                self._temperatures[t] = float(self._oven.get_value(OVEN_TABLE_NAME, f"{t}_Avg"))
        except Exception as err:
            self._oven.log.error(err)
            pass

    @property
    def setpoint(self):
        return self._temperatures[SETPOINT]

    @setpoint.setter
    def setpoint(self, value: float):
        self._temperatures[SETPOINT] = value
        self._semaphore_setpoint.release()

    def set_camera_temperatures(self, fpa: float, housing: float):
        if fpa:
            self._temperatures[T_FPA] = fpa
        if housing:
            self._temperatures[T_HOUSING] = housing

    @property
    def is_connected(self):
        return self._event_connected.is_set()

    def temperature(self, name: str) -> (float, None):
        try:
            return self._temperatures[name]
        except (KeyError, ValueError, NameError, IndexError):
            return None

    def _th_getter(self) -> None:
        self._event_connected.wait()
        while self._flag_run:
            self._getter_temperature()
            sleep(OVEN_LOG_TIME_SECONDS)

    def _th_timer(self):
        self._event_connected.wait()
        timer = time_ns()
        while True:
            if time_ns() - timer >= OVEN_LOG_TIME_SECONDS * 1e9:
                self._semaphore_collect.release()
                timer = time_ns()
            sleep(3)

    def _th_collect_records(self):
        self._event_connected.wait()
        oven_keys = [t['Fields'] for t in self._oven.table_def
                     if OVEN_TABLE_NAME.encode() in t['Header']['TableName']][0]
        oven_keys = [t['FieldName'].decode() for t in oven_keys]
        oven_keys.insert(0, DATETIME)
        oven_keys.append(T_FPA), oven_keys.append(T_HOUSING)
        df = pd.DataFrame(columns=oven_keys)
        df = df.set_index(DATETIME)

        while self._flag_run:
            self._semaphore_collect.acquire()
            try:
                if not (records := get_last_measurements(self._oven)):
                    continue
            except (NoDeviceException, RuntimeError, ValueError, AttributeError, IOError, KeyError):
                self._oven.log.critical('Oven not connected.')
                return
            records[DATETIME] = get_time()  # update inaccurate oven time
            records[T_FPA] = float(self._temperatures[T_FPA]) / 100
            records[T_HOUSING] = float(self._temperatures[T_HOUSING]) / 100
            records = pd.DataFrame(records, index=[records.pop(DATETIME)])
            df = pd.concat([df, pd.DataFrame(records)], ignore_index=False).drop_duplicates().sort_values('RecNbr')
            df.to_csv(self._records_path, index_label=DATETIME)
            self._oven.log.debug("Added a line to the oven logs.")

    def _th_setter_setpoint(self):
        self._event_connected.wait()
        while self._flag_run:
            self._semaphore_setpoint.acquire()
            for _ in range(10):
                if not self._flag_run:
                    return
                try:
                    if self._oven.set_value('Public', SETPOINT, self.setpoint):
                        msg = f'Setting the oven to {self.setpoint:.2f}C'
                        self._oven.log.debug(msg)
                    else:
                        self._oven.log.debug(f'next temperature {self.setpoint:.2f}C is already set in the oven.')
                    break
                except AttributeError:
                    break
                except (ValueError, RuntimeError, ModuleNotFoundError, NameError, ReferenceError, IOError, SystemError):
                    pass

    def _terminate_device_specifics(self) -> None:
        try:
            self._flag_run.set(False)
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._event_connected.set()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._semaphore_collect.release()
            self._semaphore_collect.release()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._semaphore_setpoint.release()
            self._semaphore_setpoint.release()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._oven.__del__()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass


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
