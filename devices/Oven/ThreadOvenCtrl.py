import csv
import multiprocessing as mp
from functools import partial
from logging import Logger
from pathlib import Path
from queue import Queue, Empty
from threading import Semaphore, Thread
from time import time_ns
from tkinter import Frame
from typing import Dict

from devices.Oven.PyCampbellCR1000.device import CR1000
from devices.Oven.plots import plot_oven_records_in_path
from devices.Oven.utils import collect_oven_records, make_oven_temperatures_list, \
    get_n_experiments, VariableLengthDeque
from gui.utils import get_spinbox_value, ThreadedSyncFlag, get_device_status, get_inner_temperatures, tqdm_waiting
from utils.constants import *
from utils.logger import make_logger, make_logging_handlers
from utils.tools import check_and_make_path, wait_for_time


def process_plotter(path_to_log: Path, semaphore_plotter: mp.Semaphore, logger: Logger):
    path_to_save = path_to_log.parent / PLOTS_PATH / 'oven'
    check_and_make_path(path_to_save)
    while True:
        semaphore_plotter.acquire()
        plot_oven_records_in_path(path_to_log, path_to_save)
        logger.debug('Fetched oven logs and plotted them.')


def thread_collect_oven_temperatures(devices_dict: dict, flag_run_experiment: ThreadedSyncFlag, frame: Frame,
                                     path_to_log: (Path, str), logger=Logger):
    if get_device_status(devices_dict[OVEN_NAME]) != DEVICE_REAL:
        return
    oven_keys = [t['Fields'] for t in devices_dict[OVEN_NAME].table_def
                 if OVEN_TABLE_NAME.encode() in t['Header']['TableName']][0]
    oven_keys = [t['FieldName'].decode() for t in oven_keys]
    is_real_camera = get_device_status(devices_dict[CAMERA_NAME]) == DEVICE_REAL
    if is_real_camera:
        oven_keys.extend([T_FPA, T_HOUSING])
    oven_keys.insert(0, DATETIME)
    path_to_log /= OVEN_RECORDS_FILENAME
    with open(path_to_log, 'w') as fp_csv:
        writer_csv = csv.writer(fp_csv)
        writer_csv.writerow(oven_keys)
    semaphore_plotter: mp.Semaphore = mp.Semaphore(0)
    p = mp.Process(target=process_plotter, daemon=True, name='proc_oven_temps_plotter',
                   kwargs=dict(path_to_log=path_to_log, semaphore_plotter=semaphore_plotter, logger=logger))
    p.start()
    while flag_run_experiment:
        # notice that wait_for_time doesn't block CR1000, because the func returns before the wait
        if not collect_oven_records(devices_dict[OVEN_NAME], logger, path_to_log, frame, oven_keys, is_real_camera):
            continue
        semaphore_plotter.release()
    semaphore_plotter.release()
    p.kill()


def wait_for_experiment_iterations(semaphore_oven_sync: Semaphore, flag_run: ThreadedSyncFlag, logger: Logger,
                                   n_of_experiments: int, next_temperature: float, semaphore_exp: Semaphore):
    [semaphore_exp.release() for _ in range(n_of_experiments)]  # allows the experiments to run
    logger.info(f'Waiting for {n_of_experiments} experiments to occur for next oven level.')
    for _ in range(n_of_experiments):
        while not semaphore_oven_sync.acquire(timeout=3):  # checks every timeout for flag
            if not flag_run:
                raise RuntimeError('Running flag is down')
        logger.debug(f"Experiment iteration conducted for {next_temperature}")
    logger.info(f'{n_of_experiments} experiments conducted for {next_temperature}.')


def set_oven_temperature(oven: CR1000, next_temp: float, logger: Logger, flag_run: ThreadedSyncFlag,
                         offset: float = 0.0, verbose: bool = True):
    if offset < 0:
        logger.warning(f"Oven was given negative offset {offset:.2f}, Disregarding.")
        offset = 0.0
    while flag_run:
        try:
            if oven.set_value('Public', SETPOINT, float(next_temp) + offset):
                msg = f'Setting the oven to {next_temp:.2f}C'
                if offset != 0:
                    msg += f' with {offset:.2f}C offset.'
                logger.info(msg) if verbose else None
            else:
                logger.debug(f'next temperature {next_temp:.2f}C is already set in the oven.') if verbose else None
            break
        except ValueError:
            pass


def set_and_wait_for_temperatures_to_settle(temperature_queue: Queue, semaphore_wait4temp: Semaphore, frame: Frame,
                                            flag_run: ThreadedSyncFlag, logger: Logger, devices_dict: dict):
    def make_maxlength() -> int:
        mean_change = int(frame.getvar(SETTLING_TIME_MINUTES)) * 60
        if not int(frame.getvar(USE_CAM_INNER_TEMPS)):
            return int(mean_change // OVEN_LOG_TIME_SECONDS)
        return int(mean_change // FREQ_INNER_TEMPERATURE_SECONDS)

    logger_mean = make_logger('OvenTempDiff',
                              make_logging_handlers(Path('log/log_oven_temperature_differences.txt'), False))
    next_temperature, prev_temperature = 0, 0
    set_temperature = partial(set_oven_temperature, flag_run=flag_run, logger=logger, oven=devices_dict[OVEN_NAME])
    if int(frame.getvar(USE_CAM_INNER_TEMPS)):
        get_inner_temperature = wait_for_time(partial(get_inner_temperatures, frame=frame),
                                              wait_time_in_nsec=FREQ_INNER_TEMPERATURE_SECONDS * 1e9)
    else:
        get_inner_temperature = wait_for_time(partial(oven_temperatures.get, T_CAMERA),
                                              wait_time_in_nsec=OVEN_LOG_TIME_SECONDS * 1e9)
    get_error = wait_for_time(partial(oven_temperatures.get, SIGNALERROR), wait_time_in_nsec=PID_FREQ_SEC * 1e9)
    while flag_run:
        while flag_run:
            try:
                next_temperature = temperature_queue.get(block=True, timeout=3)
                break
            except Empty:
                pass
        if next_temperature == 0 or not flag_run:
            break
        difference_lifo = VariableLengthDeque(maxlen=max(1, make_maxlength()))
        difference_lifo.append(float('inf'))  # +inf so that it is always bigger than DELTA_TEMPERATURE
        current_temperature = get_inner_temperature()
        offset = round(DELAY_FROM_FLOOR_TO_CAMERA_CONSTANT * (next_temperature - current_temperature), 0)
        set_temperature(next_temp=next_temperature, verbose=True, offset=offset)
        tqdm_waiting(2 * (OVEN_LOG_TIME_SECONDS + PID_FREQ_SEC), 'PID settling', flag_run)
        while flag_run and get_error() >= 1.5:  # wait until signal error reaches within 1.5deg of setPoint
            pass
        # time_of_setting -= time_ns()  # result is negative
        # time_of_setting *= 1e-9
        # time_of_setting += DELAY_FROM_FLOOR_TO_CAMERA_SECONDS
        # tqdm_waiting(int(max(0, time_of_setting)), 'Waiting', flag_run)
        set_temperature(next_temp=next_temperature, verbose=True, offset=0)
        logger.info(f'Waiting for the Camera to settle near {next_temperature:.2f}C')
        logger_mean.info(f'#######   {next_temperature}   #######')
        max_temperature = MaxTemperatureTimer()
        while flag_run and \
                (max(difference_lifo) > float(frame.getvar(DELTA_TEMPERATURE)) or
                 max_temperature.time_since_setting_in_minutes < frame.getvar(SETTLING_TIME_MINUTES)):
            difference_lifo.maxlength = make_maxlength()
            current_temperature = get_inner_temperature()
            max_temperature.max = current_temperature
            diff = abs(current_temperature - prev_temperature)
            difference_lifo.append(diff)
            logger_mean.info(f"{diff:.4f} "
                             f"prev{prev_temperature:.4f} "
                             f"curr{current_temperature:.4f} "
                             f"max{max_temperature.max:.4f}")
            prev_temperature = current_temperature
            if current_temperature >= next_temperature:
                break
        semaphore_wait4temp.release()
        logger.info(f'Camera reached temperature {prev_temperature:.2f}C '
                    f'and settled for {frame.getvar(SETTLING_TIME_MINUTES)} minutes '
                    f'under {frame.getvar(DELTA_TEMPERATURE):g} delta.')
    set_temperature(next_temp=0.0, verbose=True)


def _thread_handle_oven_func(devices_dict: dict, semaphore_oven_sync: Semaphore, logger: Logger, frame: Frame,
                             semaphore_experiment_sync: Semaphore, flag_run_experiment: ThreadedSyncFlag) -> None:
    semaphore_wait4temp = Semaphore(value=0)
    queue_temperature = Queue()
    wait_for_temperature_kwargs = dict(frame=frame, flag_run=flag_run_experiment, logger=logger,
                                       temperature_queue=queue_temperature, devices_dict=devices_dict,
                                       semaphore_wait4temp=semaphore_wait4temp)
    Thread(target=thread_get_oven_temperatures, name='thread_get_oven_temperatures',
           args=(devices_dict, flag_run_experiment,), daemon=True).start()
    tqdm_waiting(OVEN_LOG_TIME_SECONDS + PID_FREQ_SEC, 'Wait for first measurement from controller',
                 flag_run_experiment)
    th_set_temperature = Thread(target=set_and_wait_for_temperatures_to_settle, name='th_wait_for_oven_temperature',
                                kwargs=wait_for_temperature_kwargs, daemon=True)
    th_set_temperature.start()
    wait_for_iters = partial(wait_for_experiment_iterations, semaphore_oven_sync=semaphore_oven_sync,
                             flag_run=flag_run_experiment, logger=logger, semaphore_exp=semaphore_experiment_sync)

    if get_device_status(devices_dict[OVEN_NAME]) == DEVICE_OFF:
        return
    if (increment := get_spinbox_value(OVEN_NAME + INC_STRING)) == 0 or increment == -float('inf'):
        return  # if given oven temperatures are invalid, just ignore them

    temperatures_list = make_oven_temperatures_list(oven_temperatures.get(T_FLOOR))
    devices_dict[OVEN_NAME].log.debug('Entering oven control loop')
    for next_temperature in temperatures_list:
        if not flag_run_experiment:
            break
        queue_temperature.put(next_temperature, block=False)
        while flag_run_experiment and not semaphore_wait4temp.acquire(timeout=3):
            pass
        if flag_run_experiment:
            wait_for_iters(n_of_experiments=get_n_experiments(frame), next_temperature=next_temperature)
    queue_temperature.put_nowait(0.0)
    th_set_temperature.join()


def thread_get_oven_temperatures(devices_dict: dict, flag_run: ThreadedSyncFlag):
    def get() -> None:
        try:
            for t in [T_FLOOR, T_INSULATION, T_CAMERA, SIGNALERROR]:
                oven_temperatures[t] = float(devices_dict[OVEN_NAME].get_value(OVEN_TABLE_NAME, f"{t}_Avg"))
        except Exception as err:
            devices_dict[OVEN_NAME].log.error(err)
            pass

    getter = wait_for_time(get, OVEN_LOG_TIME_SECONDS * 1e9)
    while flag_run:
        getter()


def thread_handle_oven_temperature(**kwargs) -> None:
    try:
        _thread_handle_oven_func(**kwargs)
    except RuntimeError:
        pass
    for _ in range(int(1e6)):
        kwargs['semaphore_experiment_sync'].release()


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


oven_temperatures: Dict[str, float] = dict()
