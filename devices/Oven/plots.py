import csv
from functools import partial
from pathlib import Path
from threading import Thread
from tkinter import Frame
from tkinter.filedialog import askdirectory
from typing import Dict

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

from devices.Oven.utils import to_datetime
from utils.analyze import plot_images_cmp
from utils.constants import *
from utils.tools import check_and_make_path

COLOR_FLOOR = {'color': 'blue'}
COLOR_CTRLSIGNAL = {'color': 'magenta'}
COLOR_SETPOINT = {'linestyle': 'dashed', 'color': 'red'}


def plot(dict_of_y_values: Dict[str, list], x_values: (list, np.ndarray), full_save_path: (Path, None),
         dict_rise_time: (dict, None) = None,
         yaxis_label: str = TEMPERATURE_LABEL, n_ticks: int = 10, xaxis_label: str = 'Time [Minutes]'):
    _, ax = plt.subplots()
    for key, values in dict_of_y_values.items():
        if dict_rise_time:
            if any([key in k for k in dict_rise_time.keys()]):
                key = f"{key.capitalize()}, RiseTime {dict_rise_time[f'T_{key}_Avg']}Min"
        else:
            key = key.capitalize()
        if 'setpoint' in key.lower():
            plt.plot(x_values, values, label=key, **COLOR_SETPOINT)
        elif 'floor' in key.lower():
            plt.plot(x_values, values, label=key, **COLOR_FLOOR)
        elif 'ctrlsignal' in key.lower():
            plt.plot(x_values, values, label=key, **COLOR_CTRLSIGNAL)
        else:
            plt.plot(x_values, values, label=key)
    ax.xaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.xaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    plt.legend()
    plt.xlabel(xaxis_label)
    plt.ylabel(yaxis_label)
    plt.tight_layout()
    plt.grid()
    check_and_make_path(full_save_path.parent) if full_save_path else None
    plt.savefig(full_save_path) if full_save_path else plt.show()
    plt.close()


def plot_double_sides(df, x_values: (list, np.ndarray, pd.DataFrame), save_path: (Path, None),
                      y_values_left: (np.ndarray, pd.DataFrame), y_values_right_names: tuple,
                      y_label_left: str, y_label_right: str, x_label: str = 'Time [Minutes]') -> None:
    if isinstance(save_path, str):
        save_path = Path(save_path)
    fig, ax = plt.subplots()
    color_left = 'red'
    plt.plot(x_values, y_values_left, label=y_label_left.capitalize(), color=color_left)
    ax.xaxis.set_major_locator(plt.MaxNLocator(10))
    ax.xaxis.set_minor_locator(plt.MaxNLocator(10))
    ax.yaxis.set_major_locator(plt.MaxNLocator(10))
    ax.yaxis.set_minor_locator(plt.MaxNLocator(10))
    ax.set_xlabel(x_label, color='black')
    ax.tick_params(axis='x', labelcolor='black')
    ax.set_ylabel(y_label_left, color=color_left)
    ax.tick_params(axis='y', labelcolor=color_left)

    ax2 = ax.twinx()  # instantiate a second axes that shares the same x-axis
    color_right = 'blue'
    for y_values_right_name in y_values_right_names:
        if 'floor' in y_values_right_name.lower():
            kwargs = {'color': 'blue'}
        elif 'setpoint' in y_values_right_name.lower():
            kwargs = {'linestyle': 'dashed', 'color': 'blue'}
        elif 'ctrlsignal' in y_values_right_name.lower():
            kwargs = {'color': 'blue'}
        else:
            kwargs = {'color': 'blue'}
        if 'avg' in y_values_right_name.lower():
            label_name = y_values_right_name.split('_Avg')[0].capitalize()
        else:
            label_name = y_values_right_name.capitalize()
        plt.plot(x_values, df[y_values_right_name], label=label_name, **kwargs)
    ax2.xaxis.set_major_locator(plt.MaxNLocator(10))
    ax2.xaxis.set_minor_locator(plt.MaxNLocator(10))
    ax2.yaxis.set_major_locator(plt.MaxNLocator(10))
    ax2.yaxis.set_minor_locator(plt.MaxNLocator(10))
    ax2.set_ylabel(y_label_right, color=color_right)
    ax2.tick_params(axis='y', labelcolor=color_right)
    fig.legend()
    plt.tight_layout()
    plt.grid()
    check_and_make_path(save_path.parent) if save_path else None
    plt.savefig(save_path) if save_path else plt.show()
    plt.close()


def plot_oven_records_in_path(path_to_log: Path, path_to_save: Path):
    try:
        df = get_dataframe(path_to_log)
        list_running_time = make_runtime_list(df)
    except (KeyError, ValueError, RuntimeError, AttributeError, FileNotFoundError, IsADirectoryError, IndexError):
        return

    names_list = [name.split('_')[1] for name in list(df.columns) if 'T_' in name]
    dict_of_plots = {name: df[f'T_{name}_Avg'] for name in names_list}
    dict_of_plots[SETPOINT] = df[SETPOINT]
    try:
        dict_of_plots[T_FPA] = df[T_FPA]
        dict_of_plots[T_HOUSING] = df[T_HOUSING]
    except KeyError:
        pass
    plot(dict_of_y_values=dict_of_plots, x_values=list_running_time, n_ticks=10,
         yaxis_label=TEMPERATURE_LABEL, full_save_path=path_to_save / 'temperatures.png')

    names_list = [CTRLSIGNAL, 'dInputKd', 'sumErrKi', f'{SIGNALERROR}Kp']
    dict_of_plots = {name: df[f'{name}_Avg'] for name in names_list}
    dict_of_plots['dInputKd'] = -dict_of_plots['dInputKd']  # the controller subtracts dInput
    dict_of_plots[SETPOINT] = df[SETPOINT]
    plot(dict_of_y_values=dict_of_plots, x_values=list_running_time, n_ticks=10,
         yaxis_label='Control Signal', full_save_path=path_to_save / 'ctrl.png')

    double = partial(plot_double_sides, df=df, y_values_right_names=('T_floor_Avg', 'setPoint'),
                     y_label_right=TEMPERATURE_LABEL, x_values=list_running_time)
    names_list = ['dInput', 'sumErr', f'{SIGNALERROR}']
    for name in names_list:
        y_values_left = df[f'{name}_Avg'] if 'dInput' not in name else -df[f'{name}_Avg']
        double(y_label_left=name, y_values_left=y_values_left, save_path=path_to_save / f'{name}.png')
    double(y_label_left=CTRLSIGNAL, y_values_left=df[f'{CTRLSIGNAL}_Avg'],
           save_path=path_to_save / f'ctrl_vs_{T_FLOOR}.png')

    diff = df[SETPOINT] - df[f"{T_FLOOR}_Avg"]
    diff[df[SETPOINT].astype('float') <= 0] = 0
    df['Diff'] = diff
    plot_double_sides(df, x_values=list_running_time, save_path=path_to_save / 'diff.png',
                      y_label_right=TEMPERATURE_LABEL, y_values_right_names=('Diff',),
                      y_label_left='Control Signal', y_values_left=df[f'{CTRLSIGNAL}_Avg'])


def get_dataframe(log_path: (Path, str)) -> pd.DataFrame:
    with open(log_path, 'r') as fp:
        df = pd.DataFrame(csv.reader(fp))
    col_names = [df[i][0] for i in range(len(df.columns))]
    if not DATETIME in col_names:
        col_names = [df[i][1] for i in range(len(df.columns))]
        df = df[3:]
        df.index = range(len(df))
        col_names[0] = DATETIME
        col_names = {val: key for key, val in enumerate(col_names)}
    times_list = list(df[0])[1:]
    df.drop(0, inplace=True)
    df.rename(columns={key: val for key, val in zip(df.columns, col_names)}, inplace=True)
    df.pop(DATETIME)
    df.rename(index={key: val for key, val in zip(df.index, times_list)}, inplace=True)
    df.rename(columns={name: f"{name}_Avg" for name in col_names if 'T_' in name and 'Avg' not in name}, inplace=True)
    return df.astype('float')


def make_runtime_list(df) -> np.ndarray:
    run_time_minutes = (to_datetime(df.index[-1]) - to_datetime(df.index[0])).total_seconds() / 60  # to minutes
    return np.linspace(0, run_time_minutes, num=len(df.index), dtype=int)


def plot_btn_func(frame_button: Frame):
    check_and_make_path(Path(frame_button.getvar(EXPERIMENT_SAVE_PATH)))
    path_to_experiment = askdirectory(initialdir=frame_button.getvar(EXPERIMENT_SAVE_PATH),
                                           title='Choose experiment path')
    if not path_to_experiment:
        path_to_experiment = Path().cwd()
    path_to_experiment = Path(path_to_experiment)

    # oven logs
    for path in path_to_experiment.glob('*.csv'):
        Thread(target=plot_oven_records_in_path, name=f'th_plot_btn_oven_{path.stem}', daemon=True,
               args=(path, path_to_experiment / PLOTS_PATH / 'oven' / path.stem,)).start()

    # images logs
    Thread(target=plot_images_cmp, name='th_plot_btn_images', daemon=True,
           args=(path_to_experiment, path_to_experiment / PLOTS_PATH / 'camera',)).start()