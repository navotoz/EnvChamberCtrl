from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

from utils.constants import *
from utils.misc import check_and_make_path

COLOR_FLOOR = {'color': 'blue'}
COLOR_CTRLSIGNAL = {'color': 'magenta'}
COLOR_SETPOINT = {'linestyle': 'dashed', 'color': 'red'}


def plot_temperatures(df: pd.DataFrame, save_path: (Path, None), n_ticks: int = 10):
    df = df.rename(columns={name: name.split('T_')[-1].capitalize() for name in df.columns}, inplace=False)
    ax = df.plot()
    plt.xlabel('Time [Minutes]')
    plt.ylabel(TEMPERATURE_LABEL)
    plt.title('Temperatures')
    plt.grid()
    ax.xaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.xaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    plt.tight_layout()
    plt.show()
    if save_path:
        save_path /= 'temperatures.png'
        check_and_make_path(save_path)
        plt.savefig(save_path)
        plt.close()


def plot_signals(df: pd.DataFrame, save_path: (Path, None), n_ticks: int = 10):
    ax = df.plot()
    plt.xlabel('Time [Minutes]')
    plt.ylabel(TEMPERATURE_LABEL)
    plt.grid()
    plt.title('Control signals')
    ax.xaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.xaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    plt.tight_layout()
    plt.show()
    if save_path:
        save_path /= 'ctrl.png'
        check_and_make_path(save_path)
        plt.savefig(save_path)
        plt.close()


def plot_oven_records_in_path(path_to_log: Path, path_to_save: (Path, str, None) = None):
    try:
        df = get_dataframe(path_to_log)
        df.index = pd.to_datetime(list(df.index))
        df.index -= df.index[0]
        df.index = df.index.total_seconds()
        df.index /= 60  # seconds -> minutes
        df_temperatures = df[[T_FLOOR, T_INSULATION, T_CAMERA, T_FPA, T_HOUSING, SETPOINT]]
        df_signals = df[[CTRLSIGNAL, 'sumErrKi', f'{SIGNALERROR}Kp', SETPOINT]]
        df_signals = pd.concat([df_signals, -df['dInputKd']], axis=1)
    except (KeyError, ValueError, RuntimeError, AttributeError, FileNotFoundError, IsADirectoryError, IndexError):
        return
    if path_to_save:
        path_to_save = Path(path_to_save)
        if path_to_save.is_file():
            raise TypeError(f'Expected folder for path_to_save, given a file {path_to_save}.')
        elif not path_to_save.is_dir():
            path_to_save.mkdir(parents=True)

    plot_temperatures(df=df_temperatures, save_path=path_to_save, n_ticks=10)
    plot_signals(df=df_signals, save_path=path_to_save, n_ticks=10)

    # double = partial(plot_double_sides, df=df, y_values_right_names=('T_floor_Avg', 'setPoint'),
    #                  y_label_right=TEMPERATURE_LABEL, x_values=list_running_time)
    # names_list = ['dInput', 'sumErr', f'{SIGNALERROR}']
    # for name in names_list:
    #     y_values_left = df[f'{name}_Avg'] if 'dInput' not in name else -df[f'{name}_Avg']
    #     double(y_label_left=name, y_values_left=y_values_left,
    #            save_path=(path_to_save / f'{name}.png') if path_to_save else None)
    # double(y_label_left=CTRLSIGNAL, y_values_left=df[f'{CTRLSIGNAL}_Avg'],
    #        save_path=(path_to_save / f'ctrl_vs_{T_FLOOR}.png') if path_to_save else None)
    #
    # diff = df[SETPOINT] - df[f"{T_FLOOR}_Avg"]
    # diff[df[SETPOINT].astype('float') <= 0] = 0
    # df['Diff'] = diff
    # plot_double_sides(df, x_values=list_running_time,
    #                   save_path=(path_to_save / 'diff.png') if path_to_save else None,
    #                   y_label_right=TEMPERATURE_LABEL, y_values_right_names=('Diff',),
    #                   y_label_left='Control Signal', y_values_left=df[f'{CTRLSIGNAL}_Avg'])


def get_dataframe(log_path: (Path, str)) -> pd.DataFrame:
    df = pd.read_csv(log_path, index_col=DATETIME)
    return df.rename(columns={name: name.split('_Avg')[0] for name in df.columns}, inplace=False)


def plot_double_sides(df, x_values: (list, np.ndarray, pd.DataFrame), save_path: (Path, None),
                      y_values_left: (np.ndarray, pd.DataFrame), y_values_right_names: tuple,
                      y_label_left: str, y_label_right: str, x_label: str = 'Time [Minutes]') -> None:
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
    if save_path:
        if isinstance(save_path, str):
            save_path = Path(save_path)
        check_and_make_path(save_path.parent)
        plt.savefig(save_path)
    else:
        plt.show()
