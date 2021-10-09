import argparse
import signal
import sys
import threading as th
from datetime import datetime
from functools import partial
from pathlib import Path
from time import sleep

import yaml

from devices.Camera import T_FPA, T_HOUSING, INIT_CAMERA_PARAMETERS
from devices.Oven.OvenProcess import OvenCtrl
from utils.misc import SyncFlag, make_parser
from utils.threads import set_oven_and_settle

sys.path.append(str(Path().cwd().parent))

import numpy as np
from tqdm import tqdm

import pickle

from devices.BlackBodyCtrl import BlackBodyThread
from devices.Camera.CameraProcess import CameraCtrl, TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS


def _stop() -> None:
    try:
        camera.terminate()
        print('Camera terminated.', flush=True)
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass
    try:
        blackbody.terminate()
        print('BlackBody terminated.', flush=True)
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass
    try:
        oven.terminate()
        print('Oven terminated.', flush=True)
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass


def th_t_cam_getter():
    while True:
        oven.set_camera_temperatures(fpa=camera.fpa, housing=camera.housing)
        sleep(TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)


args = make_parser()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = int(args.tlinear)

    path_to_save = Path(args.path) / datetime.now().strftime("%Y%m%d_h%Hm%Ms%S")
    if not path_to_save.is_dir():
        path_to_save.mkdir(parents=True)
    with open(str(path_to_save / 'camera_params.yaml'), 'w') as fp:
        yaml.safe_dump(params, stream=fp, default_flow_style=False)
    with open(str(path_to_save / 'arguments.yaml'), 'w') as fp:
        yaml.safe_dump(vars(args), stream=fp, default_flow_style=False)

    # parse arguments
    n_images, oven_temperature, settling_time = args.n_images, args.oven_temperature, args.settling_time
    ffc_temperature = args.ffc
    list_t_bb = np.linspace(start=args.blackbody_min, stop=args.blackbody_max, num=args.blackbody_stops, dtype=int)
    print()
    print(f'BlackBody temperatures: {list_t_bb}C.')
    print(f'Settling time: {settling_time} minutes.')
    if ffc_temperature == 0:
        print(f'Perform FFC before every measurement.')
    else:
        print(f'Perform FFC at camera temperature {ffc_temperature}C.')
    print()

    # init devices
    oven = OvenCtrl(logfile_path=path_to_save / 'logs' / 'oven.txt', output_path=path_to_save)
    oven.start()
    camera = CameraCtrl(camera_parameters=params)
    camera.start()
    blackbody = BlackBodyThread(logfile_path=path_to_save / 'logs' / 'blackbody.txt', output_folder_path=path_to_save)
    blackbody.start()

    # wait for the devices to start
    while not oven.is_connected or not camera.is_connected or not blackbody.is_connected:
        sleep(1)

    # init thread
    list_th = [th.Thread(target=th_t_cam_getter, name='th_cam2oven_temperatures', daemon=True),
               th.Thread(target=th_plot_realtime, name='th_plot_realtime', daemon=False,
                         kwargs=dict())]
    wait_for_threads_to_start...


    # measurements
    set_oven_and_settle(setpoint=oven_temperature, settling_time_minutes=settling_time, oven=oven, camera=camera)
    dict_meas = dict(camera_params=params.copy(), arguments=args, oven_setpoint=oven_temperature)
    for t_bb in list_t_bb:
        blackbody.temperature = t_bb
        while not camera.ffc(): # todo: add a check for single temperature ffc
            continue
        sleep(0.5)  # clears the buffer after the FFC
        for _ in tqdm(range(n_images), postfix=f'BlackBody {t_bb}C'):
            dict_meas.setdefault('measurements', {}).setdefault(t_bb, []).append(camera.image)
            dict_meas.setdefault(T_FPA, {}).setdefault(t_bb, []).append(camera.fpa)
            dict_meas.setdefault(T_HOUSING, {}).setdefault(t_bb, []).append(camera.housing)
    pickle.dump(dict_meas, open(str(path_to_save / f'fpa_{int(camera.fpa * 100):d}.pkl'), 'wb'))
    _stop()
