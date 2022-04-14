import pickle
import signal
import sys
import threading as th
from multiprocessing import Process
from pathlib import Path
from time import sleep

import matplotlib.pyplot as plt
from tqdm import tqdm

from devices.BlackBodyCtrl import BlackBodyThread
from devices.Camera import INIT_CAMERA_PARAMETERS, T_FPA, T_HOUSING
from devices.Camera.CameraProcess import (
    TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS, CameraCtrl)
from devices.Oven.OvenProcess import (OVEN_RECORDS_FILENAME, OvenCtrl)
from devices.Oven.plots import plot_oven_records_in_path, mp_realttime_plot
from utils.misc import args_const_tbb, save_run_parameters

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


args = args_const_tbb()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = int(args.tlinear)
    params['ffc_mode'] = 'auto'
    params['ffc_period'] = 1800  # automatic FFC every 30 seconds
    rate_sleep_value = 1 / (args.rate if args.rate < 60 else 120)
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

    print(f'\nEstimated size of data (256 x 336) shape * 2 bytes * {args.rate}Hz * Hour = '
          f'{256 * 336 * 2 * args.rate * 60 * 60 / 2 ** 30} Gb\n', flush=True)

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
    t_bb = args.blackbody
    oven.setpoint = 120  # the Soft limit of the oven is 120C
    dict_meas = dict(camera_params=params.copy(), arguments=vars(args), blackbody=t_bb)
    filename = f"{now}_bb_{int(100 * t_bb):d}.pkl" if not args.filename else Path(args.filename).with_suffix('.pkl')

    blackbody.temperature = t_bb  # set the blackbody to the constant temperature
    with tqdm() as progressbar:
        while (fpa := camera.fpa) < limit_fpa:
            dict_meas.setdefault('frames', []).append(camera.image)
            dict_meas.setdefault(T_FPA, []).append(fpa)
            dict_meas.setdefault(T_HOUSING, []).append(camera.housing)
            sleep(rate_sleep_value)  # limits the Hz of the camera
            progressbar.set_postfix_str(f'FPA {fpa / 100:.1f}C, Remaining {(limit_fpa-fpa) / 100:.1f}C')
            progressbar.update()
    oven.setpoint = 0  # turn the oven off
    pickle.dump(dict_meas, open(str(path_to_save / filename), 'wb'))

    # save temperature plot
    fig, ax = plt.subplots()
    plot_oven_records_in_path(idx=0, fig=fig, ax=ax, path_to_log=path_to_save / OVEN_RECORDS_FILENAME)
    plt.savefig(path_to_save / 'temperature.png')

    _stop(None, None)
