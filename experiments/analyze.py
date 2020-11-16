from datetime import datetime
from functools import partial
from multiprocessing import cpu_count, Semaphore
from multiprocessing.dummy import Pool
from operator import itemgetter
from pathlib import Path
from typing import Dict, Tuple, List

import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import numpy as np
from tqdm import tqdm

from utils.constants import *
from utils.tools import check_and_make_path



def plot_double_sides(dict_of_y_right:dict,
                      x_values: (list, np.ndarray),
                      save_path: (Path, None),
                      y_values_left: (np.ndarray, list), y_values_right_names: tuple,
                      y_label_left: str, y_label_right: str,
                      x_label: str = 'Time [Minutes]') -> None:
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



def crop_image_tuples(image_tuple: Tuple[Path, np.ndarray], mask: np.ndarray) -> Tuple[Path, np.ndarray]:
    path, image = image_tuple
    m, n = image.shape
    mask0, mask1 = mask.any(0), mask.any(1)
    col_start, col_end = mask0.argmax(), n - mask0[::-1].argmax()
    row_start, row_end = mask1.argmax(), m - mask1[::-1].argmax()
    return path, image[row_start:row_end, col_start:col_end]


def load_np_to_dict(path_to_load: Path) -> Tuple[str, np.ndarray]:
    return path_to_load.stem, np.load(str(path_to_load))


def load_files_to_mem(path_to_load: (str, Path)) -> Tuple[List[Tuple[Path, np.ndarray]], np.ndarray]:
    path_list = list(filter(lambda x: 'mask' not in str(x), Path(path_to_load).rglob('*.npy')))
    with Pool(cpu_count()) as pool:
        list_files = list(tqdm(pool.imap(load_np_to_dict, path_list), total=len(path_list), leave=False))
    list_files.sort(key=lambda x: x[0])
    path_mask = Path(path_to_load) / 'mask.npy'
    try:
        mask = np.load(path_mask) if path_mask.is_file() else np.ones_like(list_files[0][0]).astype('bool')
    except IndexError:
        return [], np.empty(1)
    return list_files, mask


def crop_images(files_list: List[Tuple[Path, np.ndarray]], mask: np.ndarray) -> List[Tuple[Path, np.ndarray]]:
    cropper = partial(crop_image_tuples, mask=mask)
    with Pool(cpu_count()) as pool:
        list_files = list(tqdm(pool.imap(cropper, files_list), total=len(files_list), leave=False))
    list_files.sort(key=lambda x: x[0])
    return list_files


def average_iterated_images(list_of_images: list, mask: np.ndarray) -> List[Tuple[Path, float]]:
    n_images_iterations = int(list_of_images[0][0].split('|')[-1])
    list_of_images.sort(key=lambda x: x[0])
    new_list = [list_of_images[i:i + n_images_iterations] for i in range(0, len(list_of_images), n_images_iterations)]
    for idx, chunk in enumerate(new_list):
        new_name = '_'.join(chunk[0][0].split('_')[:-1])
        mean_img = np.stack([c[-1] for c in chunk])
        new_list[idx] = (new_name, float(mean_img[:, mask].mean()))
    return new_list


def get_average_temps_entire_experiment(path_to_experiment: (str, Path)) -> (List[Tuple[Path, float]], None):
    files_list, mask = load_files_to_mem(Path(path_to_experiment))
    if not files_list:
        return None
    return average_iterated_images(files_list, mask)


def parse_results_paths_to_values(results_list: (List[Tuple[Path, np.ndarray]], None)) -> (List[Dict], None):
    if not results_list:
        return None
    times_list = list(map(lambda x: datetime.strptime('_'.join(x[0].split('_')[:2]), FMT_TIME), results_list))
    times_list = list(map(lambda x: int((x - times_list[0]).total_seconds()), times_list))
    list_values = list(map(lambda x: (x[0].split('_')[2:], x[1]), results_list))
    list_values = list(map(lambda x, t: ([DATETIME, str(t)] + x[0], x[1]), list_values, times_list))
    dict_values = list(map(lambda x: {key: float(val) for key, val in zip(x[0][::2], x[0][1::2])}, list_values))
    for idx in range(len(dict_values)):
        dict_values[idx]['measurement'] = float(list_values[idx][-1])
    return dict_values


def get_averages_and_values_of_files_in_path(path_to_experiment: (Path, str)) -> List[Dict[str, float]]:
    results = get_average_temps_entire_experiment(Path(path_to_experiment))
    results = parse_results_paths_to_values(results)
    return results


def set_ax_format(ax, n_ticks: int):
    ax.xaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.1f}'))
    ax.xaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    ax.xaxis.set_minor_formatter(StrMethodFormatter('{x:,.1f}'))
    ax.yaxis.set_major_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.1f}'))
    ax.yaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
    ax.yaxis.set_minor_formatter(StrMethodFormatter('{x:,.1f}'))
    try:
        ax.zaxis.set_major_locator(plt.MaxNLocator(n_ticks))
        ax.zaxis.set_major_formatter(StrMethodFormatter('{x:,.1f}'))
        ax.zaxis.set_minor_locator(plt.MaxNLocator(n_ticks))
        ax.zaxis.set_minor_formatter(StrMethodFormatter('{x:,.1f}'))
    except AttributeError:
        pass
    return ax


def plot_3d(values_list, full_save_path: (str, Path, None), xaxis_label: str, yaxis_label: str, zaxis_label: str,
            title: (None, str) = None, use_scatter: bool = False, n_ticks: int = 10, mark_mean=False):
    x, y, z = values_list
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    plotter = ax.scatter if use_scatter else plot
    plotter(x, y, z, cmap='viridis')
    ax.set_xlabel(xaxis_label)
    ax.set_ylabel(yaxis_label)
    ax.set_zlabel(zaxis_label)
    if mark_mean:
        vals, indices, counts = np.unique(x, return_index=True, return_counts=True)
        y_means = [np.mean(y[prev_i:next_i]) for prev_i, next_i in zip(indices, list(indices[1:]) + [len(x)])]
        z_means = [np.mean(z[prev_i:next_i]) for prev_i, next_i in zip(indices, list(indices[1:]) + [len(x)])]
        ax.scatter(vals, y_means, z_means, label=f"Average")
    set_ax_format(ax, n_ticks)
    plt.grid()
    plt.title(title) if title else None
    plt.tight_layout()
    plt.savefig(fname=full_save_path)
    plt.close()


def plot(dict_of_y_values: Dict[str, list], x_values: (list, np.ndarray), full_save_path: (str, Path, None),
         mark_mean: bool = False, yaxis_label: str = 'Temperature [$C^\circ$]', n_ticks: int = 10,
         title: (None, str) = None, xaxis_label: str = 'Blackbody Temperature [$C^\circ$]',
         use_scatter: bool = False):
    _, ax = plt.subplots()
    plotter = plt.plot if not use_scatter else plt.scatter
    for key, value in dict_of_y_values.items():
        plotter(x_values, value, label=key.capitalize())
    if mark_mean:
        for name in dict_of_y_values.keys():
            vals = np.unique(x_values, return_index=False, return_counts=False)
            indices = {f"{v:.1f}": list() for v in vals}
            for idx, v in enumerate([f"{v:.1f}" for v in x_values]):
                indices[v].append(idx)
            means = [itemgetter(*ind)(dict_of_y_values[name]) for ind in indices.values()]
            means = list(map(lambda x: x if isinstance(x, tuple) else None, means))
            vals = [v for idx, v in enumerate(vals) if means[idx]]
            means = [np.mean(m) for m in means if m]
            plt.plot(vals, means, label=f"{name.capitalize()} Avg", color='red')
    set_ax_format(ax, n_ticks)
    plt.legend()
    plt.xlabel(xaxis_label)
    plt.ylabel(yaxis_label)
    plt.tight_layout()
    plt.grid()
    plt.title(title) if title else None
    plt.savefig(full_save_path) if full_save_path else plt.show()
    plt.close()


def group_same_blackbody_temperatures(results: List[Dict[str, float]]) -> Dict[float, List[Dict[str, float]]]:
    clustered_results = dict()
    for d in results.copy():
        blackbody_temperature = d['blackbody']
        clustered_results.setdefault(blackbody_temperature, []).append(
            {key: val for key, val in d.items() if 'blackbody' not in key})
    return clustered_results


def plot_clustered(results, path_to_save:Path):
    clustered_results = group_same_blackbody_temperatures(results)
    for blackbody_temperature in clustered_results.keys():
        measurements = [item['measurement'] for item in clustered_results[blackbody_temperature]]
        fpa = [item[T_FPA] for item in clustered_results[blackbody_temperature]]
        housing = [item[T_HOUSING] for item in clustered_results[blackbody_temperature]]
        time_running = [item[DATETIME] for item in clustered_results[blackbody_temperature]]
        plot_3d([fpa, housing, measurements],
                path_to_save / Path(f"3d_{blackbody_temperature:.2f}C.png"),
                'FPA', 'Housing', 'Measurements', f"Blackbody temperature {blackbody_temperature:.2f}C",
                use_scatter=True)
        p = partial(plot, dict_of_y_values=dict(measurement=measurements), yaxis_label='Measurements [$C^\circ$]',
                    use_scatter=True, title=f"Blackbody temperature {blackbody_temperature:.2f}C", mark_mean=False)
        p(x_values=fpa, xaxis_label='FPA Temperature [$C^\circ$]',
          full_save_path=path_to_save / Path(f"fpa_{blackbody_temperature:.2f}C.png"))
        p(x_values=housing, xaxis_label='Housing Temperature [$C^\circ$]',
          full_save_path=path_to_save / f"housing_{blackbody_temperature:.2f}C.png")

        plot_double_sides(dict_of_y_right={T_FPA:fpa, T_HOUSING:housing},
        x_values=time_running,
        save_path=path_to_save / f"time_{blackbody_temperature:.2f}C.png",
        y_values_left=measurements,
        y_values_right_names=(T_FPA, T_HOUSING),
        y_label_left='Measurements [Levels]', y_label_right=TEMPERATURE_LABEL)
        p = partial()


def plot_diff(results, path_to_save):
    fpa = [item[T_FPA] for item in results]
    housing = [item[T_HOUSING] for item in results]
    diff = [abs(item['blackbody'] - item['measurement']) for item in results]
    p = partial(plot, dict_of_y_values=dict(difference=diff), yaxis_label='Difference [$C^\circ$]', mark_mean=True,
                use_scatter=True, title=f"Difference between real and measured temperatures")
    p(x_values=fpa, xaxis_label='FPA Temperature [$C^\circ$]',
      full_save_path=Path(path_to_save) / Path(f"diff_fpa.png"))
    p(x_values=housing, xaxis_label='Housing Temperature [$C^\circ$]',
      full_save_path=Path(path_to_save) / Path(f"diff_housing.png"))


def plot_3d_fpa_housing_diff(results, path_to_save: Path) -> None:
    plot_3d([[item['blackbody'] for item in results],
             [item['measurement'] for item in results],
             [item[T_FPA] for item in results]], Path(path_to_save) / Path('3d_fpa.png'),
            'Blackbody [$C^\circ$]', 'Measurement [$C^\circ$]', 'FPA [$C^\circ$]',
            mark_mean=True, title='Measurement as a function of FPA and blackbody [$C^\circ$]', use_scatter=True)
    plot_3d([[item['blackbody'] for item in results],
             [item['measurement'] for item in results],
             [item[T_HOUSING] for item in results]], Path(path_to_save) / Path('3d_housing.png'),
            'Blackbody [$C^\circ$]', 'Measurement [$C^\circ$]', 'Housing [$C^\circ$]',
            mark_mean=True, title='Measurement as a function of Housing and blackbody [$C^\circ$]', use_scatter=True)
    plot_3d([[item[T_HOUSING] for item in results],
             [item[T_FPA] for item in results],
             [abs(item['blackbody'] - item['measurement']) for item in results]],
            Path(path_to_save) / Path('3d_diff.png'),
            'Housing [$C^\circ$]', 'FPA [$C^\circ$]', 'Difference [$C^\circ$]',
            title='Difference as a function of Housing and FPA [$C^\circ$]', use_scatter=True)


def process_plot_images_comparison(path_to_experiment: (Path, str), semaphore: Semaphore, flag) -> None:
    path_to_save = path_to_experiment / PLOTS_PATH / 'camera'
    check_and_make_path(path_to_save)
    while flag:
        semaphore.acquire()
        plot_images_cmp(path_to_experiment, path_to_save)


def plot_images_cmp(path_to_experiment, path_to_save):
    results = get_averages_and_values_of_files_in_path(path_to_experiment)
    if not results:
        return
    results.sort(key=lambda x: x['blackbody'])
    try:
        plot_3d_fpa_housing_diff(results.copy(), path_to_save)
    except:
        pass
    try:
        plot_clustered(results.copy(), path_to_save)
    except:
        pass
    # try:
    #     plot_diff(results.copy(), path_to_save)
    # except:
    #     pass
    try:
        plot(dict(measurement=[item['measurement'] for item in results]),
             [item['blackbody'] for item in results],
             path_to_save / 'meas_vs_bb.png', yaxis_label='Measured Temperature [$C^\circ$]',
             title='Real Vs Measured Temperature', use_scatter=True, mark_mean=True)
    except:
        pass
