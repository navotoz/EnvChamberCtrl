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
from utils.misc import save_run_parameters, args_var_bb_fpa

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
    args = args_var_bb_fpa()
    if not 0.1 <= args.blackbody_increments <= 10:
        raise ValueError(f'blackbody_increments must be in [0.1, 10], got {args.blackbody_increments}')
    if args.n_samples <= 0:
        raise ValueError(f'n_samples must be > 0, got {args.n_samples}')
    if not 10 < args.blackbody_max <= 70:
        raise ValueError(f'blackbody_max must be in [10, 70], got {args.blackbody_max}')
    if not 10 <= args.blackbody_min < 70:
        raise ValueError(f'blackbody_min must be in [0.1, 10], got {args.blackbody_min}')
    if args.blackbody_max <= args.blackbody_min:
        raise ValueError(
            f'blackbody_min ({args.blackbody_min}) must be smaller than blackbody_max ({args.blackbody_max}.')
    if args.blackbody_increments >= (args.blackbody_max - args.blackbody_min):
        raise ValueError(f'blackbody_increments must be bigger than abs(max-min) of the Blackbody.')
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
    bb_min = args.blackbody_min
    bb_max = args.blackbody_max
    bb_inc = args.blackbody_increments
    bb_temperatures = np.linspace(bb_min, bb_max, 1 + int((bb_max - bb_min) / bb_inc)).round(2)

    print(f'\nEstimated size of data per iteration (256 x 336) shape * 2 bytes * n_samples * stops = '
          f'{256 * 336 * 2 * args.n_samples * len(bb_temperatures) / 2 ** 30} Gb\n', flush=True)

    oven.setpoint = 120  # the Soft limit of the oven is 120C
    dict_meas = dict(camera_params=params.copy(), arguments=vars(args))
    filename = f"{now}.pkl" if not args.filename else Path(args.filename).with_suffix('.npz')
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
