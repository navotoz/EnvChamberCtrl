import argparse
from datetime import datetime
from multiprocessing import Event
from pathlib import Path
from time import sleep
from typing import Tuple, Union

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import yaml
from PIL import Image
from tqdm import tqdm

from devices.BlackBodyCtrl import BlackBodyThread
from devices.Camera import T_FPA, T_HOUSING
from devices.Camera.CameraProcess import CameraCtrl
from devices.Oven.OvenProcess import OvenCtrl, OVEN_RECORDS_FILENAME
from devices.Oven.plots import plot_oven_records_in_path


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


def init_devices(*, path_to_save, params):
    blackbody = BlackBodyThread(logfile_path=None, output_folder_path=path_to_save)
    blackbody.start()
    camera = CameraCtrl(camera_parameters=params)
    camera.start()
    oven = OvenCtrl(logfile_path=None, output_path=path_to_save)
    oven.start()
    return blackbody, camera, oven


def wait_for_devices_to_start(blackbody, camera, oven):
    sleep(1)
    with tqdm(desc="Waiting for devices to connect.") as progressbar:
        while not oven.is_connected or not camera.is_connected or not blackbody.is_connected:
            progressbar.set_postfix_str(f"Blackbody {'Connected' if blackbody.is_connected else 'Waiting'}, "
                                        f"Oven {'Connected' if oven.is_connected else 'Waiting'}, "
                                        f"Camera {'Connected' if camera.is_connected else 'Waiting'}")
            progressbar.update()
            sleep(1)
    print('Devices Connected.', flush=True)


def save_results(path_to_save, filename, dict_meas):
    np.savez(str(path_to_save / filename),
             fpa=np.array(dict_meas[T_FPA]).astype('uint16'),
             housing=np.array(dict_meas[T_HOUSING]).astype('uint16'),
             blackbody=(100 * np.array(dict_meas['blackbody'])).astype('uint16'),
             frames=np.stack(dict_meas['frames']).astype('uint16'))

    # save temperature plot
    fig, ax = plt.subplots()
    plot_oven_records_in_path(idx=0, fig=fig, ax=ax, path_to_log=path_to_save / OVEN_RECORDS_FILENAME)
    plt.savefig(path_to_save / 'temperature.png')


def collect_measurements(bb_generator, blackbody, camera, n_samples, limit_fpa, t_ffc) -> dict:
    dict_meas = {}
    fpa = -float('inf')
    flag_run = True

    with tqdm() as progressbar:
        while flag_run:
            for bb in bb_generator:
                blackbody.temperature = bb
                while t_ffc == 0 and not camera.ffc:
                    sleep(0.5)
                for _ in range(n_samples):
                    fpa = camera.fpa
                    dict_meas.setdefault('frames', []).append(camera.image)
                    dict_meas.setdefault('blackbody', []).append(bb)
                    dict_meas.setdefault(T_FPA, []).append(fpa)
                    dict_meas.setdefault(T_HOUSING, []).append(camera.housing)
                progressbar.update()
                progressbar.set_postfix_str(f'BB {bb:.1f}C, '
                                            f'FPA {fpa / 100:.1f}C, '
                                            f'Remaining {(limit_fpa - fpa) / 100:.1f}C')

                if fpa >= limit_fpa:
                    flag_run = False
                    break
    return dict_meas
