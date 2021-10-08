import argparse
import signal
import sys
import threading as th
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep

import yaml

from devices.Oven.OvenProcess import OvenCtrl
from utils.misc import SyncFlag, make_parser

sys.path.append(str(Path().cwd().parent))

import numpy as np
from tqdm import tqdm

import pickle

from devices.BlackBodyCtrl import BlackBody
from devices.Camera.CameraProcess import CameraCtrl


def _stop() -> None:
    try:
        camera.terminate()
    except ():
        pass
    try:
        oven.terminate()
    except ():
        pass
    try:
        blackbody.__del__()
    except ():
        pass


args = make_parser()


params = dict(
    lens_number=2,
    ffc_mode='auto' if args.ffc_auto else 'manual',
    ffc_period=int(args.ffc_period),
    isotherm=0x0000,
    dde=0x0000,
    tlinear=int(args.tlinear),  # T-Linear disabled. The scene will not represent temperatures, because of the filters.
    gain='high',
    agc='manual',
    ace=0,
    sso=0,
    contrast=0,
    brightness=0,
    brightness_bias=0,
    fps=0x0004,  # 60Hz
    lvds=0x0000,  # disabled
    lvds_depth=0x0000,  # 14bit
    xp=0x0002,  # 14bit w/ 1 discrete
    cmos_depth=0x0000,  # 14bit pre AGC
)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    path_to_save = Path(args.path) / datetime.now().strftime("%Y%m%d_h%Hm%Ms%S")
    if not path_to_save.is_dir():
        path_to_save.mkdir(parents=True)
    with open(str(path_to_save / 'camera_params.yaml'), 'w') as fp:
        yaml.safe_dump(params, stream=fp, default_flow_style=False)
    with open(str(path_to_save / 'arguments.yaml'), 'w') as fp:
        yaml.safe_dump(vars(args), stream=fp, default_flow_style=False)
    n_filters, n_images = args.n_filters, args.n_images
    list_t_bb = np.linspace(start=args.blackbody_min, stop=args.blackbody_max, num=args.blackbody_stops, dtype=int)
    if not 0 < n_filters <= 6:
        raise ValueError(f"n_filters must be 0<n_filters<=6. Received {n_filters}.")
    list_filters = [0, 8000, 9000, 10000, 11000, 12000]  # whats set on the filterwheel
    list_filters = list_filters[:n_filters]
    print(f'BlackBody temperatures: {list_t_bb}C')
    print(f'Filters: {list_filters}nm')
    thread = partial(th.Thread, target=th_saver, daemon=False)
    list_threads = []

    blackbody = BlackBody()
    camera = CameraCtrl(camera_parameters=params)
    camera.start()
    # oven = OvenCtrl(logfile_path=, output_path=)

    path_to_save = Path(path_to_save)
    if not path_to_save.is_dir():
        path_to_save.mkdir(parents=True)

    dict_fpa, dict_housing, dict_images = {}, {}, {}

    length_total = len(list_t_bb) * len(list_filters)
    idx = 1
    for t_bb in list_t_bb:
        blackbody.temperature = t_bb
        for position, filter_name in enumerate(sorted(list_filters), start=1):
            filterwheel.position = position
            dict_images.setdefault(t_bb, {}).setdefault(filter_name, [])
            """ do FFC before every filter. This is done under the assumption that the FPA temperature vary
            significantly during each BB stop.
            e.g, 3000 image at 60Hz with 6 filters -> 50sec * 6 filters -> ~6 minutes"""
            while not camera.ffc():
                continue
            sleep(1)  # clears the buffer after the FFC
            with tqdm(total=n_images) as progressbar:
                progressbar.set_description_str(f'{filter_name}nm')
                progressbar.set_postfix_str(f'BlackBody {t_bb}C, Idx {idx}|{length_total}')
                while len(dict_images[t_bb][filter_name]) != n_images:
                    dict_images[t_bb][filter_name].append(camera.image)
                    dict_fpa.setdefault(t_bb, {}).setdefault(filter_name, []).append(camera.fpa)
                    dict_housing.setdefault(t_bb, {}).setdefault(filter_name, []).append(camera.housing)
                    progressbar.update()
                idx += 1
        list_threads.append(thread(kwargs=dict(t_bb_=t_bb, path=path_to_save, params_cam=params,
                                               images=dict_images.pop(t_bb), fpa=dict_fpa.pop(t_bb),
                                               housing=dict_housing.pop(t_bb))))
        list_threads[-1].start()
    try:
        camera.terminate()
        print('Camera terminated.')
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass
    try:
        blackbody.__del__()
        print('BlackBody terminated.')
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass
    try:
        del filterwheel
        print('Filterwheel terminated.')
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass
    [p.join() for p in list_threads]
