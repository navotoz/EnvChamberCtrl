import pickle
import signal
import sys
import threading as th
from multiprocessing import Process
from pathlib import Path
from time import sleep

import matplotlib.pyplot as plt
import numpy as np
from tqdm import tqdm

from devices.BlackBodyCtrl import BlackBodyDummyThread, BlackBodyThread
from devices.Camera import INIT_CAMERA_PARAMETERS, T_FPA, T_HOUSING
from devices.Camera.CameraProcess import (
    TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS, CameraCtrl)
from devices.Oven.DummyOven import DummyOven
from devices.Oven.OvenProcess import (OVEN_RECORDS_FILENAME, OvenCtrl,
                                      set_oven_and_settle)
from devices.Oven.plots import plot_oven_records_in_path
from utils.misc import args_const_fpa, tqdm_waiting, mp_realttime_plot, save_run_parameters

sys.path.append(str(Path().cwd().parent))


def _stop(a, b, **kwargs) -> None:
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
    flag_ffc = False
    while True:
        fpa = camera.fpa
        oven.set_camera_temperatures(fpa=fpa, housing=camera.housing)
        if not flag_ffc and fpa >= ffc_temperature:
            if flag_ffc := camera.ffc():
                print(f'FFC done at FPA {fpa}C')
        sleep(TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)


args = args_const_fpa()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = int(args.tlinear)
    path_to_save, now = save_run_parameters(args.path, params, args)

    # parse arguments
    n_images, oven_temperature, settling_time = args.n_images, args.oven_temperature, args.settling_time
    ffc_temperature = args.ffc
    list_t_bb = np.linspace(start=args.blackbody_min, stop=args.blackbody_max, num=args.blackbody_stops, dtype=int)
    print(f'\nBlackBody temperatures: {list_t_bb}C.\nSettling time: {settling_time} minutes.', flush=True)
    if ffc_temperature == 0:
        print(f'Perform FFC before every measurement.\n', flush=True)
    else:
        print(f'Perform FFC at FPA temperature {ffc_temperature}C.\n', flush=True)

    # init devices
    if not args.blackbody_dummy:
        blackbody = BlackBodyThread(logfile_path=path_to_save / 'logs' / 'blackbody.txt',
                                    output_folder_path=path_to_save)
        blackbody.start()
    else:
        blackbody = BlackBodyDummyThread()
    camera = CameraCtrl(camera_parameters=params)
    camera.start()

    if oven_temperature != 0:
        oven = OvenCtrl(logfile_path=path_to_save / 'logs' / 'oven.txt', output_path=path_to_save)
        oven.start()
    else:
        oven = DummyOven()

    # wait for the devices to start
    sleep(1)
    with tqdm(desc="Waiting for devices to connect.") as progressbar:
        while not oven.is_connected or not camera.is_connected:
            progressbar.set_postfix_str(f"Oven {'Connected' if oven.is_connected else 'Waiting'}, "
                                        f"Camera {'Connected' if camera.is_connected else 'Waiting'}")
            progressbar.update()
            sleep(1)
    print('Devices Connected.', flush=True)

    # wait for the records file to be created
    while oven_temperature != 0 and not (path_to_save / OVEN_RECORDS_FILENAME).is_file():
        sleep(1)

    # init thread
    th_cam_getter = th.Thread(target=th_t_cam_getter, name='th_cam2oven_temperatures', daemon=True)
    th_cam_getter.start()

    # realtime plot of temperatures
    mp_plot = Process(target=mp_realttime_plot, args=(path_to_save,), name='mp_realtime_plot', daemon=True)
    mp_plot.start() if oven_temperature != 0 else None

    # measurements
    if oven_temperature != 0:
        set_oven_and_settle(setpoint=oven_temperature, settling_time_minutes=settling_time, oven=oven, camera=camera)
    dict_meas = dict(camera_params=params.copy(), arguments=vars(args), oven_setpoint=oven_temperature)
    filename = f"{now}_fpa_{int(camera.fpa):d}.pkl" if not args.filename else Path(args.filename).with_suffix('.pkl')
    try:
        if abs(blackbody.temperature - list_t_bb[-1]) < abs(blackbody.temperature - list_t_bb[0]):
            list_t_bb = list(reversed(list_t_bb))
    except TypeError:
        pass
    for t_bb in list_t_bb:
        blackbody.temperature = t_bb
        while ffc_temperature == 0 and not camera.ffc():  # do ffc only if --ffc == 0
            sleep(0.5)
        sleep(0.5)  # clears the buffer after the FFC
        tqdm_waiting(time_to_wait_seconds=2 * 60, postfix='Settle camera to the blackbody temperature')
        t_bb *= 100
        for _ in tqdm(range(n_images), postfix=f'BlackBody {t_bb / 100}C'):
            dict_meas.setdefault('frames', {}).setdefault(t_bb, []).append(camera.image)
            dict_meas.setdefault(T_FPA, {}).setdefault(t_bb, []).append(camera.fpa)
            dict_meas.setdefault(T_HOUSING, {}).setdefault(t_bb, []).append(camera.housing)
    pickle.dump(dict_meas, open(str(path_to_save / filename), 'wb'))

    # save temperature plot
    if oven_temperature != 0:
        fig, ax = plt.subplots()
        plot_oven_records_in_path(idx=0, fig=fig, ax=ax, path_to_log=path_to_save / OVEN_RECORDS_FILENAME)
        plt.savefig(path_to_save / 'temperature.png')

    _stop(None, None)
