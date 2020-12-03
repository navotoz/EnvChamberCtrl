import csv
import multiprocessing as mp
import threading as th
from datetime import timedelta
from functools import partial
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Dict

from devices import make_oven, make_oven_dummy
from devices.Oven.plots import plot_oven_records_in_path
from devices.Oven.utils import get_last_measurements, to_datetime, VariableLengthDeque, MaxTemperatureTimer
from gui.utils import SyncFlag, tqdm_waiting
from utils.constants import *
from utils.logger import make_logger, make_logging_handlers
from utils.tools import wait_for_time, check_and_make_path


class OvenCtrl(mp.Process):
    _use_camera_inner_temperatures = True
    _oven = None

    def __init__(self, log_path: Path, logging_handlers:(tuple,list),
                 recv_temperature: Connection, send_temperature_is_set: Connection,
                 delta_temperature: mp.Value, fpa_temperature: mp.Value, housing_temperature: mp.Value,
                 flag_run: SyncFlag, settling_time_minutes: mp.Value, is_dummy: bool):
        super(OvenCtrl, self).__init__()
        self._logging_handlers = logging_handlers
        self._path_to_log = log_path
        self._flag_run = flag_run
        self._oven_temperatures: Dict[str, float] = dict()
        self._fpa_temperature = fpa_temperature
        self._housing_temperature = housing_temperature
        self._settling_time_minutes = settling_time_minutes
        self._delta_temperature = delta_temperature
        self._recv_temperature = recv_temperature
        self._send_temperature_is_set = send_temperature_is_set
        self._workers_dict = dict()
        self._is_dummy = is_dummy
        self._path_to_records = self._path_to_log / OVEN_RECORDS_FILENAME

        self._event_start = th.Event()
        self._event_start.clear()
        th.Thread(target=self._starter, daemon=True, name='th_oven_starter').start()

    def start(self):
        self._event_start.set()

    def _starter(self) -> None:
        while self._flag_run and not self._event_start.wait(timeout=1):
            continue
        if not self._flag_run:
            return
        self._event_start.clear()
        try:
            self._oven = make_oven(self._logging_handlers) if not self._is_dummy else make_oven_dummy()
        except RuntimeError:
            self._oven = make_oven_dummy()

        # temperature collector
        self._workers_dict['t_collector'] = th.Thread(target=self._th_get_oven_temperatures, name='t_collector')
        self._workers_dict['t_collector'].start()

        while self._flag_run and not self._event_start.wait(timeout=1):
            continue
        if not self._flag_run:
            return

        if not self._oven.is_dummy:
            # records collector
            self._workers_dict['records'] = th.Thread(target=self._th_collect_records, name='records')
            self._workers_dict['records'].start()

            # temperature plotter
            self._workers_dict['plotter'] = mp.Process(target=self._process_plotter, name='plotter')
            self._workers_dict['plotter'].start()

        # temperature setter
        self._workers_dict['setter'] = th.Thread(target=self._th_temperature_setter, name='setter')
        self._workers_dict['setter'].start()

    def terminate(self) -> None:
        self._flag_run.set(False)
        for p in self._workers_dict.values():
            try:
                p.join()
            except:
                pass

    def __del__(self):
        self._flag_run.set(False)
        for p in self._workers_dict.values():
            try:
                p.join()
            except:
                pass

    def _inner_temperatures(self, type_to_get: str = T_HOUSING) -> float:
        type_to_get = type_to_get.lower()
        if T_HOUSING.lower() in type_to_get:
            return self._housing_temperature.value
        elif T_FPA.lower() in type_to_get:
            return self._fpa_temperature.value
        if 'max' in type_to_get:
            return max(self._fpa_temperature.value, self._housing_temperature.value)
        if 'avg' in type_to_get or 'mean' in type_to_get or 'average' in type_to_get:
            return (self._fpa_temperature.value + self._housing_temperature.value) / 2.0
        if 'min' in type_to_get:
            return min(self._fpa_temperature.value, self._housing_temperature.value)
        raise NotImplementedError(f"{type_to_get} was not implemented for inner temperatures.")

    def _process_plotter(self):
        path_to_save = self._path_to_log / PLOTS_PATH / 'oven'
        check_and_make_path(path_to_save)
        p = wait_for_time(plot_oven_records_in_path, OVEN_LOG_TIME_SECONDS)
        while self._flag_run:
            p(self._path_to_records, path_to_save)

    def _th_get_oven_temperatures(self):
        def get() -> None:
            try:
                for t in [T_FLOOR, T_INSULATION, T_CAMERA, SIGNALERROR]:
                    self._oven_temperatures[t] = float(self._oven.get_value(OVEN_TABLE_NAME, f"{t}_Avg"))
            except Exception as err:
                self._oven.log.error(err)
                pass

        get()
        self._event_start.set()
        getter = wait_for_time(get, OVEN_LOG_TIME_SECONDS)
        while self._flag_run:
            getter()

    def _th_collect_records(self):
        oven_keys = [t['Fields'] for t in self._oven.table_def
                     if OVEN_TABLE_NAME.encode() in t['Header']['TableName']][0]
        oven_keys = [t['FieldName'].decode() for t in oven_keys]
        oven_keys.insert(0, DATETIME)
        oven_keys.append(T_FPA), oven_keys.append(T_HOUSING)
        with open(self._path_to_records, 'w') as fp_csv:
            writer_csv = csv.writer(fp_csv)
            writer_csv.writerow(oven_keys)
        get = wait_for_time(func=get_last_measurements, wait_time_in_sec=OVEN_LOG_TIME_SECONDS)
        while self._flag_run:
            records = get(self._oven)
            if not records:
                with open(self._path_to_records, 'r') as fp_csv:
                    reader_csv = csv.reader(fp_csv)
                    rows = list(reader_csv)
                records = dict().fromkeys(rows[0])
                if rows[0] == rows[-1]:  # there are only keys in the csv file
                    return False
                records = {key: val for key, val in zip(records.keys(), rows[-1])}
                records[DATETIME] = str(to_datetime(records[DATETIME]) + timedelta(seconds=OVEN_LOG_TIME_SECONDS))
                self._oven.log.debug('Failed to get records, using previous records.')
            records[T_FPA] = float(self._fpa_temperature.value)
            records[T_HOUSING] = float(self._housing_temperature.value)
            records = {key: val for key, val in records.items() if key in oven_keys}
            for key in [CTRLSIGNAL, 'dInputKd', 'sumErrKi', f'{SIGNALERROR}Kp', 'dInput', 'sumErr', f'{SIGNALERROR}']:
                try:
                    records[f"{key}_Avg"] = 0 if records[SETPOINT] <= 0 else records[f"{key}_Avg"]
                except (IndexError, KeyError, TypeError):
                    pass
            with open(self._path_to_records, 'a') as fp_csv:
                writer_csv = csv.writer(fp_csv)
                writer_csv.writerow([records[key] for key in oven_keys])
            self._oven.log.debug("Added a line to the oven logs.")

    def _make_maxlength(self) -> int:
        mean_change = int(self._settling_time_minutes.value) * 60
        if not self._use_camera_inner_temperatures:
            return int(mean_change // OVEN_LOG_TIME_SECONDS)
        return int(mean_change // FREQ_INNER_TEMPERATURE_SECONDS)

    def _set_oven_temperature(self, next_temperature: float, offset: float, verbose: bool = True):
        if offset < 0:
            self._oven.log.warning(f"Oven was given negative offset {offset:.2f}, Disregarding.")
            offset = 0.0
        for _ in range(10):
            try:
                if self._oven.set_value('Public', SETPOINT, float(next_temperature) + offset):
                    msg = f'Setting the oven to {next_temperature:.2f}C'
                    if offset != 0:
                        msg += f' with {offset:.2f}C offset.'
                    self._oven.log.info(msg) if verbose else self._oven.log.debug(msg)
                else:
                    self._oven.log.debug(f'next temperature {next_temperature:.2f}C '
                                         f'is already set in the oven.') if verbose else None
                break
            except AttributeError:
                break
            except (ValueError, RuntimeError, ModuleNotFoundError, NameError, ReferenceError, IOError, SystemError):
                pass

    def _th_temperature_setter(self):
        handlers = make_logging_handlers(Path('log/log_oven_temperature_differences.txt'))
        logger_waiting = make_logger('OvenTempDiff', handlers, False)
        next_temperature, prev_temperature = 0, 0
        if self._use_camera_inner_temperatures:
            get_inner_temperature = wait_for_time(self._inner_temperatures, FREQ_INNER_TEMPERATURE_SECONDS)
        else:
            get_inner_temperature = wait_for_time(partial(self._oven_temperatures.get, T_CAMERA), OVEN_LOG_TIME_SECONDS)
        get_error = wait_for_time(partial(self._oven_temperatures.get, SIGNALERROR), wait_time_in_sec=PID_FREQ_SEC)
        while self._flag_run:
            while self._flag_run:
                if self._recv_temperature.poll(timeout=2):
                    next_temperature = self._recv_temperature.recv()
                    break
            if next_temperature == 0 or not self._flag_run:
                break
            difference_lifo = VariableLengthDeque(maxlen=max(1, self._make_maxlength()))
            difference_lifo.append(float('inf'))  # +inf so that it is always bigger than DELTA_TEMPERATURE
            offset = next_temperature - max(self._oven_temperatures.get(T_FLOOR), get_inner_temperature())
            offset = round(max(0, DELAY_FLOOR2CAMERA_CONST * offset), 1)
            # empirically, MAX_TEMPERATURE_LINEAR_RISE is very slow to get to - around 75C
            if next_temperature + offset >= MAX_TEMPERATURE_LINEAR_RISE:
                offset = MAX_TEMPERATURE_LINEAR_RISE - next_temperature
            self._set_oven_temperature(next_temperature, offset=offset, verbose=True)
            tqdm_waiting(2 * (OVEN_LOG_TIME_SECONDS + PID_FREQ_SEC), 'Waiting for PID to settle', self._flag_run)
            while self._flag_run and get_error() >= 1.5:  # wait until signal error reaches within 1.5deg of setPoint
                pass
            self._set_oven_temperature(next_temperature, offset=0, verbose=True)
            self._oven.log.info(f'Waiting for the Camera to settle near {next_temperature:.2f}C')
            logger_waiting.info(f'#######   {next_temperature}   #######')
            max_temperature = MaxTemperatureTimer()
            while self._flag_run and \
                    (max(difference_lifo) > float(self._delta_temperature.value) or
                     max_temperature.time_since_setting_in_minutes < float(self._settling_time_minutes.value)):
                difference_lifo.maxlength = self._make_maxlength()
                current_temperature = get_inner_temperature()
                max_temperature.max = current_temperature
                diff = abs(current_temperature - prev_temperature)
                difference_lifo.append(diff)
                logger_waiting.info(f"{diff:.4f} "
                                 f"prev{prev_temperature:.4f} "
                                 f"curr{current_temperature:.4f} "
                                 f"max{max_temperature.max:.4f}")
                prev_temperature = current_temperature
                if current_temperature >= next_temperature:
                    break
            self._send_temperature_is_set.send(next_temperature)
            self._oven.log.info(f'Camera reached temperature {prev_temperature:.2f}C '
                                f'and settled for {self._settling_time_minutes.value} minutes '
                                f'under {self._delta_temperature.value} delta.')
        self._set_oven_temperature(0, offset=0, verbose=True)
