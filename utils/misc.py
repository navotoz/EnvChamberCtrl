from datetime import datetime
from multiprocessing import Event
from pathlib import Path
from time import time_ns, sleep

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def mean(values: (list, tuple, np.ndarray, float)) -> float:
    if not values:
        return -float('inf')
    if isinstance(values, float):
        return values
    ret_values = list(filter(lambda x: x is not None and np.abs(x) != -float('inf'), values))
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


def normalize_image(image: np.ndarray) -> Image.Image:
    if image.dtype == np.bool:
        return Image.fromarray(image.astype('uint8') * 255)
    image = image.astype('float32')
    if (0 == image).all():
        return Image.fromarray(image.astype('uint8'))
    mask = image > 0
    image[mask] -= image[mask].min()
    image[mask] = image[mask] / image[mask].max()
    image[~mask] = 0
    image *= 255
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
            avg = np.mean(np.stack([np.load(str(x)) for x in dir_path.glob(f'*.{suffix}')]), 0).astype('uint16')
            np.save(str(dir_path / 'average.npy'), avg)
            normalize_image(avg).save(str(dir_path / 'average.jpeg'), format='jpeg')
