import csv
import multiprocessing as mp
import threading as th
from functools import partial
from pathlib import Path
from time import sleep
from typing import Dict

from devices import make_oven, make_oven_dummy
from devices.Oven.plots import plot_oven_records_in_path
from devices.Oven.utils import get_last_measurements, VariableLengthDeque, MaxTemperatureTimer, _make_temperature_offset
from gui.tools import tqdm_waiting
from utils.constants import *
from utils.logger import make_logger, make_logging_handlers
from utils.tools import wait_for_time, check_and_make_path, DuplexPipe
import utils.constants as const
from devices import DeviceAbstract


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


class OvenCtrl(DeviceAbstract):
    _use_camera_inner_temperatures = True
    _oven = None
    _workers_dict = dict()
    _settling_time_minutes: int = 0

    def __init__(self,
                 logging_handlers: (tuple, list),
                 event_stop: mp.Event,
                 temperature_pipe: DuplexPipe,
                 cmd_pipe: DuplexPipe,
                 output_path: (Path, None),
                 values_dict: dict):
        super(OvenCtrl, self).__init__(event_stop, logging_handlers, values_dict)
        self._output_path = Path(output_path) if output_path is not None else Path('')
        self._records_path = self._output_path / const.OVEN_RECORDS_FILENAME
        self._temperature_pipe = temperature_pipe
        self._cmd_pipe = cmd_pipe
        self._flags_pipes_list = [self._temperature_pipe.flag_run, self._cmd_pipe.flag_run]
        self._oven_temperatures: Dict[str, float] = dict()
        self._oven = make_oven_dummy()
        self._event_plotter_plot = mp.Event()
        self._event_start = th.Event()
        self._event_start.clear()

    @property
    def output_path(self):
        return self._output_path

    @output_path.setter
    def output_path(self, output_path_to_set: (str, Path)):
        self._output_path = Path(output_path_to_set)
        self._records_path = self._output_path / const.OVEN_RECORDS_FILENAME

    def _run(self):
        self._flag_run.set(True)

    def _start(self):
        self._flag_run.set(True)

        # temperature collector
        self._workers_dict['t_collector'] = th.Thread(target=self._th_get_oven_temperatures, name='t_collector')
        self._workers_dict['t_collector'].start()

        # wait for first temperature to be collected
        while self._flag_run and not self._event_start.wait(timeout=0.2):
            continue

        # temperature setter
        self._workers_dict['setter'] = th.Thread(target=self._th_temperature_setter, name='setter')
        self._workers_dict['setter'].start()
        self._oven.log.debug('Started temperature setter thread.')

        if self._is_dummy() == const.DEVICE_REAL:
            # records collector
            self._workers_dict['records'] = th.Thread(target=self._th_collect_records, name='records')
            self._workers_dict['records'].start()
            self._oven.log.debug('Started record collection thread.')

            # temperature plotter
            self._workers_dict['plotter'] = PlotterProc(self._flag_run, self._event_plotter_plot,
                                                        output_path=self._output_path)
            self._workers_dict['plotter'].start()
            self._oven.log.debug('Started plotter process.')

    def _terminate_device_specifics(self) -> None:
        self._event_plotter_plot.set()

    def _stop(self):
        self._flag_run.set(False)
        self._event_start.clear()

    def _is_dummy(self):
        return const.DEVICE_DUMMY if 'dummy' in str(type(self._oven)).lower() else const.DEVICE_REAL

    def _th_cmd_parser(self):
        while True:
            if (cmd := self._cmd_pipe.recv()) is not None:
                cmd, value = cmd
                if cmd == const.EXPERIMENT_SAVE_PATH:
                    if isinstance(value, (str, Path)):
                        self.output_path = value
                        self._cmd_pipe.send(value)
                    else:
                        self._cmd_pipe.send(None)
                elif cmd == const.OVEN_NAME:
                    if value is True:
                        self._cmd_pipe.send(self._is_dummy())
                    elif value != const.DEVICE_DUMMY:
                        try:
                            self._oven.log.info('Attempting to connect the Real Oven')
                            oven = make_oven(self._logging_handlers)
                            self._oven = oven
                            self._cmd_pipe.send(const.DEVICE_REAL)
                        except RuntimeError:
                            self._cmd_pipe.send(const.DEVICE_DUMMY)
                            self._stop()
                    else:
                        self._oven = make_oven_dummy()
                        self._cmd_pipe.send(const.DEVICE_DUMMY)
                        self._stop()
                elif cmd == const.SETTLING_TIME_MINUTES:
                    self._settling_time_minutes = int(value) if value is not None else self._settling_time_minutes
                    self._cmd_pipe.send(self._settling_time_minutes)
                elif cmd == const.BUTTON_START:
                    if value is True:
                        self._start()
                    elif value is False:
                        self._start()

    def _inner_temperatures(self, type_to_get: str = T_FPA) -> float:
        type_to_get = type_to_get.lower()
        if T_HOUSING.lower() in type_to_get:
            return self._values_dict[T_HOUSING]
        elif T_FPA.lower() in type_to_get:
            return self._values_dict[T_FPA]
        elif 'max' in type_to_get:
            return max(self._values_dict[T_FPA], self._values_dict[T_HOUSING])
        elif 'avg' in type_to_get or 'mean' in type_to_get or 'average' in type_to_get:
            return (self._values_dict[T_FPA] + self._values_dict[T_HOUSING]) / 2.0
        elif 'min' in type_to_get:
            return min(self._values_dict[T_FPA], self._values_dict[T_HOUSING])
        raise NotImplementedError(f"{type_to_get} was not implemented for inner temperatures.")

    def _th_get_oven_temperatures(self) -> None:
        def get() -> None:
            try:
                for t in [T_FLOOR, T_INSULATION, T_CAMERA, SIGNALERROR]:
                    self._oven_temperatures[t] = float(self._oven.get_value(OVEN_TABLE_NAME, f"{t}_Avg"))
            except Exception as err:
                self._oven.log.error(err)
                pass

        get()
        self._event_start.set()
        self._oven.log.debug('Collected first temperatures.')
        getter = wait_for_time(get, OVEN_LOG_TIME_SECONDS)
        while self._flag_run:
            getter()

    def _th_collect_records(self):
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
            records[T_FPA] = float(self._values_dict[T_FPA])
            records[T_HOUSING] = float(self._values_dict[T_HOUSING])
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

    def _make_maxlength(self) -> int:
        time_of_change_in_seconds = self._settling_time_minutes * 60
        if not self._use_camera_inner_temperatures:
            return int(time_of_change_in_seconds // OVEN_LOG_TIME_SECONDS)
        return int(time_of_change_in_seconds // FREQ_INNER_TEMPERATURE_SECONDS)

    def _samples_to_minutes(self, n_samples: int) -> float:
        if not self._use_camera_inner_temperatures:
            return (n_samples * OVEN_LOG_TIME_SECONDS) / 60
        return (n_samples * FREQ_INNER_TEMPERATURE_SECONDS) / 60

    def _set_oven_temperature(self, next_temperature: float, offset: float, verbose: bool = True):
        if offset < 0:
            self._oven.log.warning(f"Oven was given negative offset {offset:.2f}, Disregarding.")
            offset = 0.0
        for _ in range(10):
            if not self._flag_run:
                return
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

    def _th_temperature_setter(self) -> None:
        next_temperature, fin_msg = 0, 'Finished waiting due to '
        handlers = make_logging_handlers('log/oven/temperature_differences.txt')
        logger_waiting = make_logger('OvenTempDiff', handlers, False)
        if self._use_camera_inner_temperatures:
            get_inner_temperature = wait_for_time(self._inner_temperatures, FREQ_INNER_TEMPERATURE_SECONDS)
        else:
            get_inner_temperature = wait_for_time(partial(self._oven_temperatures.get, T_CAMERA), OVEN_LOG_TIME_SECONDS)

        # handle dummy oven
        if self._is_dummy() == const.DEVICE_REAL:
            get_error = wait_for_time(partial(self._oven_temperatures.get, SIGNALERROR), wait_time_in_sec=PID_FREQ_SEC)
            initial_wait_time = PID_FREQ_SEC + OVEN_LOG_TIME_SECONDS * 4  # to let the average ErrSignal settle
        else:
            get_error = lambda: 0
            initial_wait_time = 1

        # thread loop
        while self._flag_run:
            next_temperature = self._temperature_pipe.recv()
            if not self._flag_run or not next_temperature or next_temperature <= 0:
                break

            # creates a round-robin queue of differences (dt_camera) to wait until t_camera settles
            queue_temperatures = VariableLengthDeque(maxlen=max(1, self._make_maxlength()))
            queue_temperatures.append(-float('inf'))  # -inf so that the diff always returns +inf
            offset = _make_temperature_offset(t_next=next_temperature, t_oven=self._oven_temperatures.get(T_FLOOR),
                                              t_cam=get_inner_temperature())
            self._set_oven_temperature(next_temperature, offset=offset, verbose=True)

            # wait until signal error reaches within 1.5deg of setPoint
            tqdm_waiting(initial_wait_time, 'Waiting for PID to settle', self._flag_run)
            while self._flag_run and get_error() >= 1.5:
                pass
            self._set_oven_temperature(next_temperature, offset=0, verbose=True)

            self._oven.log.info(f'Waiting for the Camera to settle near {next_temperature:.2f}C')
            logger_waiting.info(f'#######   {next_temperature}   #######')
            while msg := self._flag_run:
                if queue_temperatures.is_full:
                    msg = f'{fin_msg}{self._settling_time_minutes}Min without change in temperature.'
                    break
                queue_temperatures.maxlength = self._make_maxlength()
                queue_temperatures.append(get_inner_temperature())
                n_minutes_settled = self._samples_to_minutes(len(queue_temperatures))
                logger_waiting.info(f"FPA{queue_temperatures[0]:.1f} "
                                    f"{self._settling_time_minutes:3d}|{n_minutes_settled:.2f}Min")
            logger_waiting.info(msg) if isinstance(msg, str) else None
            self._oven.log.info(msg) if isinstance(msg, str) else None
            self._temperature_pipe.send(next_temperature)
            self._oven.log.info(f'Camera reached temperature {queue_temperatures[0]:.2f}C '
                                f'and settled for {self._settling_time_minutes} minutes.')
