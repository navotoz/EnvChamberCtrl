#
# pip install PyCampbellCR1000 tqdm scipy numpy pandas matplotlib
#

import argparse
import csv
from collections import namedtuple
from datetime import datetime, timedelta
from multiprocessing import Process
from pathlib import Path
from threading import Thread
from time import sleep
from typing import List, Dict, Tuple

import numpy as np
from serial.tools.list_ports import comports
from tqdm import tqdm

from devices.Camera.Tau2Grabber import TeaxGrabber
from devices.Oven.PyCampbellCR1000.device import CR1000
from devices.Oven.utils import get_oven_results, interp_missing_values
from devices.Oven.plots import plot, get_dataframe, make_runtime_list
from utils.tools import wait_for_time, get_time
from utils.constants import *

KEYS_TO_CHECK = (
    DATETIME, SETPOINT, f'{CTRLSIGNAL}_Avg', f'{T_FLOOR}_Avg', f'{T_INSULATION}_Avg',
    'T_camera_Avg', 'dInputKd_Avg', 'sumErrKi_Avg', f'{SIGNALERROR}Kp_Avg',
    'T_fpa', 'T_housing')

Temperature = namedtuple('Temperature', ('time', 'value'))


def analyze_and_plot(log_path: (Path, None)):
    if not log_path:
        raise ValueError("No log file was given to analyze.")
    if not log_path.is_file():
        raise FileExistsError(f"{log_path} does not exists.")
    save_path = log_path.parent / '_'.join(log_path.stem.split('_')[:2])
    df = get_dataframe(log_path)
    list_running_time = make_runtime_list(df)

    dict_rise_time_minutes = dict().fromkeys([f'{T_FLOOR}_Avg', f'{T_INSULATION}_Avg',
                                              'T_camera_Avg', 'T_fpa_Avg','T_housing_Avg'])
    for key in filter(lambda x: x in df.keys(), dict_rise_time_minutes.keys()):
        idx_max = (df[key] >= 0.95 * df[key].max()).argmax()
        idx_min = (df[key] >= 1.05 * df[key].min()).argmax()
        dict_rise_time_minutes[key] = idx_max-idx_min

    # plot temps as a function of time
    names_list = [name.split('_')[1] for name in list(df.columns) if 'T_' in name]
    dict_of_plots = {name: df[f'T_{name}_Avg'] for name in names_list}
    dict_of_plots[SETPOINT] = df[SETPOINT]
    plot(dict_of_y_values=dict_of_plots, x_values=list_running_time, n_ticks=10,
         dict_rise_time=dict_rise_time_minutes,
         yaxis_label='Temperature [$C^\circ$]', full_save_path=str(save_path) + '_temperatures.png')

    # plot ctrl signal as a function of time
    plot(dict_of_y_values=dict(T_floor=df[f'{T_FLOOR}_Avg'], ctrlSignal=df[f'{CTRLSIGNAL}_Avg'],
                               setPoint=df[SETPOINT]),
         x_values=list_running_time, n_ticks=10, yaxis_label='Temperature [$C^\circ$]',
         full_save_path=str(save_path) + '_ctrl.png')

    # T_floor with ctrl signals
    dict_of_plots = {name: df[name] for name in ['dInputKd_Avg', 'sumErrKi_Avg',
                                                 f'{SIGNALERROR}Kp_Avg', SETPOINT, f'{CTRLSIGNAL}_Avg']}
    dict_of_plots = {key: np.clip(val, -max(df[SETPOINT]), max(df[SETPOINT])) for key, val in dict_of_plots.items()}
    dict_of_plots[T_FLOOR] = df[f'{T_FLOOR}_Avg']
    plot(dict_of_y_values=dict_of_plots, x_values=list_running_time, n_ticks=10,
         full_save_path=str(save_path) + '_ctrl_signals.png')

    # inner temps as a function of insulation
    dict_of_plots = {name: df[name] for name in ['T_fpa_Avg', 'T_housing_Avg']}
    plot(dict_of_y_values=dict_of_plots, x_values=df[f'{T_INSULATION}_Avg'], n_ticks=10,
         xaxis_label='Insulation temperature [$C^\circ$]', yaxis_label='Temperature [$C^\circ$]',
         full_save_path=str(save_path) + '_inner_temps_vs_insulation.png')


def func_get_oven_res_and_parse(oven: CR1000, time_first_res: datetime.time,
                                dict_results: Dict[str, List[Temperature]]):
    oven_log = get_oven_results(oven, time_first_res-timedelta(seconds=30))
    for key in dict_results.keys():
        oven_log.setdefault(key, [np.NaN] * len(oven_log.get(DATETIME)))

    # place the values according to their times - times should be equal for all results in dict_results
    results_times_list = map(lambda x: x.time, list(dict_results.values())[0])
    results_times_list = list(map(lambda x: x.replace(second=0), results_times_list))
    for curr_time in oven_log.get(DATETIME):
        idx_of_curr_time_in_results = int(np.nonzero([res == curr_time for res in results_times_list])[0])
        for key in dict_results.keys():
            oven_log[key][idx_of_curr_time_in_results] = dict_results[key][idx_of_curr_time_in_results].value

    # clip the beginnings of the lists if NaN
    nan_indices = np.nonzero([res != np.NaN for res in oven_log[list(dict_results.keys())[0]]])[0]
    idx_start = int(min(nan_indices))
    idx_end = int(max(nan_indices)) + 1
    oven_log = {key: val[idx_start:idx_end] for key, val in oven_log.items()}

    # interp missing values
    for key in dict_results.keys():
        oven_log[key] = interp_missing_values(oven_log[key])

    # append to csv
    with open(path_to_log, 'a') as fp_csv:
        writer_csv = csv.writer(fp_csv)
        writer_csv.writerows(zip(*[oven_log[key] for key in KEYS_TO_CHECK]))


def collect_camera_temperatures(camera: TeaxGrabber.get_inner_temperature, is_last: bool = False,
                                minutes_to_collect: int = 1) -> Tuple[datetime.time, Temperature, Temperature]:
    def mean(lst: list) -> float:
        return float(np.mean(list(filter(lambda x: x is not None, lst))))

    def save_debug(t_: datetime.time, t_fpa_mean: float,
                   t_fpa_list: list, t_housing_mean: float, t_housing_list: list) -> None:
        with open(path_to_debug, 'a') as f_pointer:
            f_pointer.write(f'#######  {t_}  #######\n')
            writer_ = csv.writer(f_pointer)
            writer_.writerow(['fpa'] + [f"mean{t_fpa_mean:.2f}"] + t_fpa_list)
            writer_.writerow(['housing'] + [f"mean{t_housing_mean:.2f}"] + t_housing_list)

    fpa_mean_list, housing_mean_list = [], []
    time_plus_minute = (get_time() + timedelta(minutes=minutes_to_collect))
    time_plus_minute = time_plus_minute.replace(second=0)
    if not is_last:
        postfix = f"Getting temperatures until {time_plus_minute.strftime('%H:%M:%S')}"
    else:
        postfix = f"Last collection before logging at {time_plus_minute.strftime('%H:%M:%S')}"
    with tqdm(leave=False, postfix=postfix) as progress_bar:
        while datetime.now() <= time_plus_minute:  # microseconds matter here so use now()
            fpa_mean_list.append(camera('fpa'))
            housing_mean_list.append(camera('housing'))
            progress_bar.update()
    temperature_fpa = Temperature(time_plus_minute, mean(fpa_mean_list))
    temperature_housing = Temperature(time_plus_minute, mean(housing_mean_list))
    print(f"Logged {time_plus_minute}")
    Thread(target=save_debug, daemon=False, args=(time_plus_minute, temperature_fpa.value, fpa_mean_list.copy(),
                                                  temperature_housing.value, housing_mean_list.copy(),)).start()
    return time_plus_minute, temperature_fpa, temperature_housing


MINUTES_FOR_LOG = 5
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run experiment to check inner Tau2 temperatures versus '
                                                 'the real environment temperatures.\n'
                                                 'Make sure both Tau2 and the Campbell oven controller are connected to the PC.')
    parser.add_argument('-run', action='store_true', help='Run the entire experiment.')
    parser.add_argument('--path', type=str, default='', required=False, help='Path to save the results.')
    args = parser.parse_args()

    path = Path(args.path) if args.path else (Path().cwd().parent.parent / 'experiments')
    if path.is_file() and args.run:
        raise ValueError(f"{path} already exists. Training will over-run it.")
    path_to_log = path / Path(f'{get_time().strftime("%Y%m%d_h%Hm%Ms%S")}_log_camera_vs_oven.txt')
    path_to_debug = path_to_log.parent / (path_to_log.stem + '_debugging.txt')

    if args.run:
        print('List of available serial ports:')
        list_ports = comports()
        [print(x.device) for x in list_ports]
        list_ports = list(filter(lambda x: 'serial' in x.description.lower() and 'usb' in x.device.lower(), list_ports))

        with open(path_to_log, 'w') as fp:  # write keys in the beginning of the file
            writer = csv.writer(fp)
            writer.writerow(KEYS_TO_CHECK)

        camera = wait_for_time(TeaxGrabber().get_inner_temperature, 1e9)
        oven = CR1000.from_url(f'serial:{list_ports[0].device}:115200')
        oven.settime(get_time())
        print(f"Oven port: {list_ports[0].device}")
        try:
            oven.get_data(OVEN_TABLE_NAME, start_date=get_time() - timedelta(minutes=2))
        except Exception as err:
            print('Failed in using the oven. Try checking the connection and running the program again.')
            raise err

        time_start_experiment = get_time().replace(second=0) + timedelta(minutes=1)
        diff_in_seconds = (time_start_experiment - datetime.now()).total_seconds()  # microseconds matter here
        if diff_in_seconds > 0:
            print(f"Waiting {diff_in_seconds:.1f} seconds for a round minute to start the experiment...")
            sleep(diff_in_seconds)
        print(f"Started the experiment at {time_start_experiment}")

        while True:  # currently, I can't really control the temperature, so this is manual labor
            fpa_list, housing_list, log_time_list = [], [], []

            for minutes in range(1, MINUTES_FOR_LOG + 1):
                time_log, t_fpa, t_housing = collect_camera_temperatures(camera)
                log_time_list.append(time_log)
                fpa_list.append(t_fpa)
                housing_list.append(t_housing)

            thread = Thread(target=func_get_oven_res_and_parse, daemon=False,
                            kwargs={'oven': oven,
                                    'time_first_res': log_time_list[0] if log_time_list else get_time(),
                                    'dict_results': dict(T_fpa=fpa_list.copy(), T_housing=housing_list.copy())})
            thread.start()
            Process(target=analyze_and_plot, args=(path_to_log,), daemon=False).start()
    [analyze_and_plot(log_path=Path(p)) for p in Path(path).glob('*oven.txt')]
