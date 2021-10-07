import csv
import ctypes
import multiprocessing as mp
import threading as th
from pathlib import Path
from time import sleep

from serial import SerialException, SerialTimeoutException

import utils.constants as const
from devices import DeviceAbstract
from devices.Oven.utils import get_last_measurements
from utils.constants import *
from utils.logger import make_logging_handlers
from utils.misc import wait_for_time

OVEN_RECORDS_FILENAME = 'oven_records.csv'


def make_oven(logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = 20):
    from devices.Oven.PyCampbellCR1000.device import CR1000
    from utils.misc import get_time
    from serial.tools.list_ports import comports
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

    def __init__(self, logfile_path: (str, Path)):
        super(OvenCtrl, self).__init__()

        # sync objects
        self._event_connected = mp.Event()
        self._event_connected.clear()
        self._event_output_path_is_set = th.Event()
        self._event_output_path_is_set.clear()
        self._semaphore_setpoint = mp.Semaphore(value=0)
        self._pipe_output_path_send, self._pipe_output_path_receive = mp.Pipe(duplex=False)

        # paths
        self._logging_handlers = make_logging_handlers(logfile_path=logfile_path)
        _mp_manager = mp.Manager()
        self._temperatures = _mp_manager.dict().fromkeys([T_FLOOR, T_INSULATION, T_CAMERA, T_FPA, T_HOUSING,
                                                          SIGNALERROR, SETPOINT], 0.0)
        self._settling_time_minutes = mp.Value(ctypes.c_ulong)
        self._settling_time_minutes.value = 0

    def set_output_path(self, output_path_to_set: (str, Path)):
        self._pipe_output_path_send.send(output_path_to_set)

    def _th_setter_path(self):
        try:
            self._output_path = Path(self._pipe_output_path_receive.recv())
        except TypeError:
            return
        if not self._output_path.is_dir():
            self._output_path.mkdir(parents=True)
        self._records_path = self._output_path / OVEN_RECORDS_FILENAME
        self._event_output_path_is_set.set()

    def _run(self):
        self._workers_dict['setter_path'] = th.Thread(target=self._th_setter_path, name='oven_setter_path', daemon=True)
        self._workers_dict['conn'] = th.Thread(target=self._th_connect, name='oven_conn', daemon=True)
        self._workers_dict['getter'] = th.Thread(target=self._th_getter, name='oven_getter', daemon=True)
        self._workers_dict['collector'] = th.Thread(target=self._th_collect_records, name='oven_collect', daemon=False)
        self._workers_dict['setter_setpoint'] = th.Thread(target=self._th_setter_setpoint,
                                                          name='oven_setter_setpoint', daemon=True)

    def _th_connect(self):
        while self._flag_run:
            try:
                self._oven = make_oven(self._logging_handlers)
                self._getter_temperature()
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
    def settling_time_minutes(self) -> int:
        return self._settling_time_minutes.value

    @settling_time_minutes.setter
    def settling_time_minutes(self, value: float):
        self.settling_time_minutes.value = value

    @property
    def is_connected(self):
        return self._event_connected.is_set()

    def _make_maxlength(self) -> int:
        time_of_change_in_seconds = self.settling_time_minutes * 60
        return int(time_of_change_in_seconds // FREQ_INNER_TEMPERATURE_SECONDS)

    @staticmethod
    def _samples_to_minutes(n_samples: int) -> float:
        return (n_samples * FREQ_INNER_TEMPERATURE_SECONDS) / 60

    def _th_getter(self) -> None:
        self._event_connected.wait()
        while self._flag_run:
            self._getter_temperature()
            sleep(OVEN_LOG_TIME_SECONDS)

    def _th_collect_records(self):
        self._event_connected.wait()
        self._event_output_path_is_set.wait()
        oven_keys = [t['Fields'] for t in self._oven.table_def
                     if OVEN_TABLE_NAME.encode() in t['Header']['TableName']][0]
        oven_keys = [t['FieldName'].decode() for t in oven_keys]
        oven_keys.insert(0, DATETIME)
        oven_keys.append(T_FPA), oven_keys.append(T_HOUSING)
        with open(self._records_path, 'w') as fp_csv:
            writer_csv = csv.writer(fp_csv)
            writer_csv.writerow(oven_keys)
        get = wait_for_time(func=get_last_measurements, wait_time_in_sec=OVEN_LOG_TIME_SECONDS)
        keys_to_fix = [CTRLSIGNAL, 'dInputKd', 'sumErrKi', f'{SIGNALERROR}Kp', 'dInput', 'sumErr', f'{SIGNALERROR}']

        while self._flag_run:
            if not (records := get(self._oven)):
                continue
            records[T_FPA] = float(self._temperatures[T_FPA])
            records[T_HOUSING] = float(self._temperatures[T_HOUSING])
            records = {key: val for key, val in records.items() if key in oven_keys}
            for key in keys_to_fix:
                try:
                    records[f"{key}_Avg"] = 0 if records[SETPOINT] <= 0 else records[f"{key}_Avg"]
                except (IndexError, KeyError, TypeError):
                    pass
            with open(self._records_path, 'a') as fp_csv:
                writer_csv = csv.writer(fp_csv)
                writer_csv.writerow([records[key] for key in oven_keys])
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

    def _terminate_device_specifics(self) -> None:  # todo: add relevent sync obj
        try:
            self._flag_run.set(False)
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._event_connected.set()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._pipe_output_path_send.send(None)
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._event_output_path_is_set.set()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
        try:
            self._semaphore_setpoint.release()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError):
            pass
