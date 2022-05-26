import signal
import sys
import threading as th
from multiprocessing import Process
from pathlib import Path
from time import sleep, time_ns

import matplotlib.pyplot as plt
import numpy as np
from tqdm import tqdm

from devices.BlackBodyCtrl import BlackBodyThread
from devices.Camera import INIT_CAMERA_PARAMETERS, T_FPA, T_HOUSING
from devices.Camera.CameraProcess import (
    TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS, CameraCtrl)
from devices.Oven.OvenProcess import (OVEN_RECORDS_FILENAME, OvenCtrl)
from devices.Oven.plots import plot_oven_records_in_path, mp_realttime_plot
from utils.misc import args_rand_bb, save_run_parameters, args_var_bb_fpa

sys.path.append(str(Path().cwd().parent))


def _stop(a, b, **kwargs) -> None:
    try:
        oven.setpoint = 0  # turn the oven off
    except:
        pass
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
        oven.join()  # allows the last records to be saved
        print('Oven terminated.', flush=True)
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass


def th_t_cam_getter():
    while True:
        fpa = camera.fpa
        try:
            oven.set_camera_temperatures(fpa=fpa, housing=camera.housing)
        except (BrokenPipeError, ValueError, TypeError, AttributeError, RuntimeError):
            pass
        sleep(TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    args = args_rand_bb()
    if args.n_samples <= 0:
        raise ValueError(f'n_samples must be > 0, got {args.n_samples}')
    if not 10 <= args.blackbody_max <= 70:
        raise ValueError(f'blackbody_max must be in [10, 70], got {args.blackbody_max}')
    if not 10 <= args.blackbody_min <= 70:
        raise ValueError(f'blackbody_min must be in [10, 70], got {args.blackbody_min}')
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = int(args.tlinear)
    params['ffc_mode'] = 'auto'
    params['ffc_period'] = 1800  # automatic FFC every 30 seconds
    limit_fpa = args.limit_fpa
    print(f'Maximal FPA {limit_fpa}C')
    limit_fpa *= 100  # C -> 100C, same as camera.fpa
    path_to_save, now = save_run_parameters(args.path, params, args)

    # init devices
    blackbody = BlackBodyThread(logfile_path=None, output_folder_path=path_to_save)
    blackbody.start()
    camera = CameraCtrl(camera_parameters=params)
    camera.start()
    oven = OvenCtrl(logfile_path=None, output_path=path_to_save)
    oven.start()

    # wait for the devices to start
    sleep(1)
    with tqdm(desc="Waiting for devices to connect.") as progressbar:
        while not oven.is_connected or not camera.is_connected or not blackbody.is_connected:
            progressbar.set_postfix_str(f"Blackbody {'Connected' if blackbody.is_connected else 'Waiting'}, "
                                        f"Oven {'Connected' if oven.is_connected else 'Waiting'}, "
                                        f"Camera {'Connected' if camera.is_connected else 'Waiting'}")
            progressbar.update()
            sleep(1)
    print('Devices Connected.', flush=True)

    # wait for the records file to be created
    while not (path_to_save / OVEN_RECORDS_FILENAME).is_file():
        sleep(1)

    # init thread
    th_cam_getter = th.Thread(target=th_t_cam_getter, name='th_cam2oven_temperatures', daemon=True)
    th_cam_getter.start()

    # realtime plot of temperatures
    mp_plot = Process(target=mp_realttime_plot, args=(path_to_save,), name='mp_realtime_plot', daemon=True)
    mp_plot.start()

    # measurements
    RESOLUTION = 10
    bb_min = int(args.blackbody_min * RESOLUTION)
    bb_max = int(args.blackbody_max * RESOLUTION)
    bb_temperatures = np.random.randint(low=min(bb_min, bb_max), high=max(bb_min, bb_max), size=abs(bb_max - bb_min))
    bb_temperatures = bb_temperatures.astype('float') / RESOLUTION  # float for the bb
    while True:
        try:
            bb_temperatures = bb_temperatures.reshape(len(bb_temperatures) // args.bins, args.bins)
            bb_temperatures = np.sort(bb_temperatures, axis=1)
            for idx in range(1, bb_temperatures.shape[0], 2):
                bb_temperatures[idx] = np.flip(bb_temperatures[idx])
            bb_temperatures = bb_temperatures.ravel()
            break
        except ValueError:
            args.bins += 1

    oven.setpoint = 120  # the Soft limit of the oven is 120C
    dict_meas = dict(camera_params=params.copy(), arguments=vars(args))
    filename = f"{now}.npz" if not args.filename else Path(args.filename).with_suffix('.npz')
    fpa = -float('inf')
    flag_run = True

    with tqdm() as progressbar:
        while flag_run:
            for bb in bb_temperatures:
                blackbody.temperature = bb
                s = time_ns()
                for _ in range(args.n_samples):
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

            bb_temperatures = np.flip(bb_temperatures)

    oven.setpoint = 0  # turn the oven off
    np.savez(str(path_to_save / filename),
             fpa=np.array(dict_meas[T_FPA]).astype('uint16'),
             housing=np.array(dict_meas[T_HOUSING]).astype('uint16'),
             blackbody=(100 * np.array(dict_meas['blackbody'])).astype('uint16'),
             frames=np.stack(dict_meas['frames']).astype('uint16'))

    # save temperature plot
    fig, ax = plt.subplots()
    plot_oven_records_in_path(idx=0, fig=fig, ax=ax, path_to_log=path_to_save / OVEN_RECORDS_FILENAME)
    plt.savefig(path_to_save / 'temperature.png')
