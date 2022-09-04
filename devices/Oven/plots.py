from functools import partial
from pathlib import Path

import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.animation import FuncAnimation

from devices.Oven.OvenProcess import OVEN_RECORDS_FILENAME
from utils.constants import *
from utils.constants import OVEN_LOG_TIME_SECONDS

COLOR_FLOOR = {'color': 'blue'}
COLOR_CTRLSIGNAL = {'color': 'magenta'}
COLOR_SETPOINT = {'linestyle': 'dashed', 'color': 'red'}


def plot_oven_records_in_path(idx, *, fig: plt.Figure, ax: plt.Subplot, path_to_log: Path, n_ticks: int = 10):
    try:
        df = get_dataframe(path_to_log)
        df = df.drop(df[df.setPoint == 0].index)
        df.index = pd.to_datetime(list(df.index))
        df.index -= df.index[0]
        df.index = df.index.total_seconds()
        df.index /= 60  # seconds -> minutes
        df_t = df[[T_FLOOR, T_INSULATION, T_CAMERA, T_FPA, T_HOUSING, SETPOINT]]
        df_t = df_t[df_t.fpa != 0.0]
        df_t = df_t[df_t.housing != 0.0]
    except (KeyError, ValueError, RuntimeError, AttributeError, FileNotFoundError, IsADirectoryError, IndexError):
        return

    ax.cla()
    df_t = df_t.rename(columns={name: name.split('T_')[-1].capitalize() for name in df_t.columns}, inplace=False)
    ax.plot(df_t, label=df_t.columns)
    fig.legend(loc='lower left')
    ax.set_xlabel('Time [Minutes]')
    ax.set_ylabel(TEMPERATURE_LABEL)
    ax.xaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.xaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    ax.grid()
    fig.tight_layout()
    return fig


def get_dataframe(log_path: (Path, str)) -> pd.DataFrame:
    df = pd.read_csv(log_path, index_col=DATETIME)
    return df.rename(columns={name: name.split('_Avg')[0] for name in df.columns}, inplace=False)


def mp_realttime_plot(path_to_save: Path):
    fig = plt.figure(figsize=(12, 6))
    ax = plt.subplot()
    plot = partial(plot_oven_records_in_path, fig=fig, ax=ax, path_to_log=path_to_save / OVEN_RECORDS_FILENAME)
    ani = FuncAnimation(fig, plot, interval=OVEN_LOG_TIME_SECONDS * 1e3)
    plt.show()
