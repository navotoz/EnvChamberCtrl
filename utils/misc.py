import argparse
from datetime import datetime
from multiprocessing import Event
from pathlib import Path
from time import time_ns, sleep
from typing import Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import yaml
from PIL import Image
from tqdm import tqdm
import matplotlib as mpl


def mean(values: (list, tuple, np.ndarray, float)) -> float:
    if not values:
        return -float('inf')
    if isinstance(values, float):
        return values
    ret_values = list(
        filter(lambda x: x is not None and np.abs(x) != -float('inf'), values))
    return np.mean(ret_values) if ret_values else -float('inf')


def show_image(image: (Image.Image, np.ndarray), title=None, v_min=None, v_max=None, to_close: bool = True,
               show_axis: bool = False):
    if isinstance(image, Image.Image):
        image = np.array([image])
    if np.any(np.iscomplex(image)):
        image = np.abs(image)
    if len(image.shape) > 2:
        if image.shape[0] == 3 or image.shape[0] == 1:
            image = image.transpose((1, 2, 0))  # CH x W x H -> W x H x CH
        elif image.shape[-1] != 3 and image.shape[-1] != 1:  # CH are not RGB or grayscale
            image = image.mean(-1)
    plt.imshow(image.squeeze(), cmap='gray', vmin=v_min, vmax=v_max)
    if title is not None:
        plt.title(title)
    plt.axis('off' if not show_axis else 'on')
    plt.show()
    plt.close() if to_close else None


def wait_for_time(func, wait_time_in_sec: float = 1):
    def do_func(*args, **kwargs):
        start_time = time_ns()
        res = func(*args, **kwargs)
        sleep(max(0.0, 1e-9 * (start_time + wait_time_in_sec * 1e9 - time_ns())))
        return res

    return do_func


def get_time() -> datetime.time: return datetime.now().replace(microsecond=0)


def normalize_image(image: np.ndarray, cmap=mpl.cm.get_cmap('coolwarm')) -> Image.Image:
    if image.dtype == np.bool:
        return Image.fromarray(image.astype('uint8') * 255)
    image = image.astype('float32')
    if (0 == image).all():
        return Image.fromarray(image.astype('uint8'))
    mask = image > 0
    image[mask] -= image[mask].min()
    image[mask] = image[mask] / image[mask].max()
    image[~mask] = 0
    image = cmap(image)
    image = np.uint8(255 * image)
    return Image.fromarray(image.astype('uint8'))


def check_and_make_path(path: (str, Path, None)):
    if not path:
        return
    path = Path(path)
    if not path.is_dir():
        path.mkdir(parents=True)


class SyncFlag:
    def __init__(self, init_state: bool = True) -> None:
        self._event = Event()
        self._event.set() if init_state else self._event.clear()

    def __call__(self) -> bool:
        return self._event.is_set()

    def set(self, new_state: bool):
        self._event.set() if new_state is True else self._event.clear()

    def __bool__(self) -> bool:
        return self._event.is_set()


def save_average_from_images(path: (Path, str), suffix: str = 'npy'):
    for dir_path in [f for f in Path(path).iterdir() if f.is_dir()]:
        save_average_from_images(dir_path, suffix)
        if any(filter(lambda x: 'average' in str(x), dir_path.glob(f'*.{suffix}'))):
            continue
        images_list = list(dir_path.glob(f'*.{suffix}'))
        if images_list:
            avg = np.mean(np.stack(
                [np.load(str(x)) for x in dir_path.glob(f'*.{suffix}')]), 0).astype('uint16')
            np.save(str(dir_path / 'average.npy'), avg)
            normalize_image(avg).save(
                str(dir_path / 'average.jpeg'), format='jpeg')


def args_const_fpa():
    parser = argparse.ArgumentParser(description='Measures multiple images of the BlackBody at different setpoints, '
                                                 'at a predefined camera temperature.'
                                                 'The Oven temperature is first settled at the predefined temperature, '
                                                 'and when the temperature of the camera settles, '
                                                 'measurements of the BlackBody at different setpoints commence.'
                                                 'The images are saved as a dict in a pickle file.')
    # general
    parser.add_argument('--path', help="The folder to save the results. Creates folder if invalid.",
                        default='measurements')
    parser.add_argument(
        '--n_images', help="The number of images to capture for each point.", default=3000, type=int)
    parser.add_argument(
        '--filename', help="The name of the measurements file", default='', type=str)

    # camera
    parser.add_argument('--ffc', type=int, required=True,
                        help=f"The camera performs FFC before every stop if arg is 0, else at the given temperature.")
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')

    # blackbody
    parser.add_argument('--blackbody_stops', type=int, default=18,
                        help=f"How many BlackBody stops between blackbody_max to blackbody_min.")
    parser.add_argument(
        '--blackbody_max', help=f"Maximal temperature of the BlackBody in C.", type=int, default=80)
    parser.add_argument(
        '--blackbody_min', help=f"Minimal temperature of the BlackBody in C.", type=int, default=10)
    parser.add_argument('--blackbody_dummy',
                        help=f"Uses a dummy BlackBody.", action='store_true')

    # oven
    parser.add_argument('--oven_temperature', type=int, required=True,
                        help=f"What Oven temperatures will be set.\nIf 0 than oven will be dummy.")
    parser.add_argument('--settling_time', help=f"The time in Minutes to wait for the camera temperature to settle"
                                                f" in an Oven setpoint before measurement.", type=int, default=30)
    return parser.parse_args()


def args_const_tbb():
    parser = argparse.ArgumentParser(description='Set the oven to the highest temperature possible and measure a '
                                                 'constant Blackbody temperature. '
                                                 'The images are saved as a dict in a pickle file.')
    # general
    parser.add_argument('--path', help="The folder to save the results. Creates folder if invalid.",
                        default='measurements')
    parser.add_argument(
        '--filename', help="The name of the measurements file", default='', type=str)

    # camera
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')
    parser.add_argument('--rate', help=f"The rate in Hz. The maximal value is 60Hz", type=int,
                        required=True, default=60)
    parser.add_argument('--limit_fpa', help='The maximal allowed value for the FPA temperate.'
                                            'Should adhere to FLIR specs, which are at most 65C.', default=55)

    # blackbody
    parser.add_argument('--blackbody', type=int, required=True,
                        help=f"A constant Blackbody temperature to set, in Celsius.")

    return parser.parse_args()


def args_var_bb_fpa():
    parser = argparse.ArgumentParser(description='Set the oven to the highest temperature possible and cycle '
                                                 'the Blackbody to different Tbb.'
                                                 'The images are saved as a dict in a pickle file.')
    # general
    parser.add_argument('--path', help="The folder to save the results. Creates folder if invalid.",
                        default='measurements')
    parser.add_argument(
        '--filename', help="The name of the measurements file", default='', type=str)

    # camera
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')
    parser.add_argument('--lens_number', help=f"The lens number for calibration.", type=int, required=True)
    parser.add_argument('--limit_fpa', help='The maximal allowed value for the FPA temperate.'
                                            'Should adhere to FLIR specs, which are at most 65C.', default=55)

    # blackbody
    parser.add_argument('--blackbody_max', type=int, required=True,
                        help=f"The maximal value of the Blackbody in Celsius")
    parser.add_argument('--blackbody_min', type=int, required=True,
                        help=f"The minimal value of the Blackbody in Celsius")
    parser.add_argument('--blackbody_increments', type=float, required=True,
                        help=f"The increments in the Blackbody temperature. Allowed values [0.1, 10] C")
    parser.add_argument('--n_samples', type=int, required=True,
                        help=f"The number of samples to take at each Blackbody stop.")

    return parser.parse_args()


def args_rand_bb():
    parser = argparse.ArgumentParser(description='Set the oven to the highest temperature possible and cycle '
                                                 'the Blackbody to different Tbb.'
                                                 'The images are saved as a dict in a pickle file.')
    # general
    parser.add_argument('--path', help="The folder to save the results. Creates folder if invalid.",
                        default='measurements')
    parser.add_argument(
        '--filename', help="The name of the measurements file", default='', type=str)

    # camera
    parser.add_argument('--lens_number', help=f"The lens number for calibration.", type=int, required=True)
    parser.add_argument('--tlinear', help=f"The grey levels are linear to the temperature as: 0.04 * t - 273.15.",
                        action='store_true')
    parser.add_argument('--limit_fpa', help='The maximal allowed value for the FPA temperate.'
                                            'Should adhere to FLIR specs, which are at most 65C.', default=55)
    parser.add_argument('--ffc', default=0,
                        help='A temperature at which the camera performs FFC once. If 0 - performs every 30 seconds.')

    # blackbody
    parser.add_argument('--blackbody_max', type=int, default=70,
                        help=f"The maximal value of the Blackbody in Celsius")
    parser.add_argument('--blackbody_min', type=int, default=10,
                        help=f"The minimal value of the Blackbody in Celsius")
    parser.add_argument('--n_samples', type=int, default=100,
                        help=f"The number of samples to take at each Blackbody stop.")
    parser.add_argument('--bins', type=int, default=6,
                        help="The number of bins in each iteration of BlackBody.")

    return parser.parse_args()


def args_meas_bb_times():
    parser = argparse.ArgumentParser(
        description='Check the time it takes the Blackbody to climb and to descend.')
    parser.add_argument('--path', help="The folder to save the results. Creates folder if invalid.",
                        default='measurements')
    parser.add_argument('--blackbody_max', type=int, required=True,
                        help=f"The maximal value of the Blackbody in Celsius")
    parser.add_argument('--blackbody_min', type=int, required=True,
                        help=f"The minimal value of the Blackbody in Celsius")
    parser.add_argument('--blackbody_increments', type=float, required=True,
                        help=f"The increments in the Blackbody temperature. Allowed values [0.1, 10] C")
    parser.add_argument('--n_samples', type=int, required=True,
                        help=f"The number of samples to take at each Blackbody stop.")
    return parser.parse_args()


def tqdm_waiting(time_to_wait_seconds: int, postfix: str):
    for _ in tqdm(range(time_to_wait_seconds), total=time_to_wait_seconds, leave=True, postfix=postfix):
        sleep(1)


def save_run_parameters(path: str, params: Union[dict, None], args: argparse.Namespace) -> Tuple[Path, str]:
    now = datetime.now().strftime("%Y%m%d_h%Hm%Ms%S")
    path_to_save = Path(path) / now
    if path_to_save.is_file():
        raise TypeError(
            f'Expected folder for path_to_save, given a file {path_to_save}.')
    elif not path_to_save.is_dir():
        path_to_save.mkdir(parents=True)
    if params is not None:
        with open(str(path_to_save / 'camera_params.yaml'), 'w') as fp:
            yaml.safe_dump(params, stream=fp, default_flow_style=False)
    with open(str(path_to_save / 'arguments.yaml'), 'w') as fp:
        yaml.safe_dump(vars(args), stream=fp, default_flow_style=False)
    return path_to_save, now
