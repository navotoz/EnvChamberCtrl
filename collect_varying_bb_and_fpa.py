from itertools import count
import math
import sys
import threading as th
from multiprocessing import Process
from pathlib import Path
from time import sleep

from devices.Camera import INIT_CAMERA_PARAMETERS
from devices.Camera.CameraProcess import (
    TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)
from devices.Oven.OvenProcess import (OVEN_RECORDS_FILENAME)
from devices.Oven.plots import mp_realttime_plot
from utils.args import args_var_bb_fpa
from utils.bb_iterators import TbbGenSawTooth
from utils.common import collect_measurements, continuous_collection, save_results, wait_for_devices_to_start, init_devices, \
    save_run_parameters, wait_for_fpa

sys.path.append(str(Path().cwd().parent))


def th_t_cam_getter():
    while True:
        fpa = camera.fpa
        try:
            oven.set_camera_temperatures(fpa=fpa, housing=camera.housing)
        except (BrokenPipeError, ValueError, TypeError, AttributeError, RuntimeError):
            pass
        sleep(TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)


if __name__ == "__main__":
    print('\n###### TURN ON BOTH OVEN SWITCHES ######\n')
    args = args_var_bb_fpa()
    bb_generator = TbbGenSawTooth(bb_min=args.blackbody_min, bb_max=args.blackbody_max, bb_start=args.blackbody_start,
                                  bb_inc=args.blackbody_increments, bb_is_decreasing=args.blackbody_is_decreasing)
    if args.n_samples <= 0:
        raise ValueError(f'n_samples must be > 0, got {args.n_samples}')
    assert args.ffc == 0 or args.ffc > 1000, f'FFC must be either 0 or given in [100C] range, got {args.ffc}'
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = int(args.tlinear)
    params['ffc_mode'] = 'manual'
    params['ffc_period'] = 0
    params['lens_number'] = args.lens_number
    print(f'Lens Number = {args.lens_number}', flush=True)
    limit_fpa = args.limit_fpa
    print(f'Maximal FPA {limit_fpa}C')
    limit_fpa *= 100  # C -> 100C, same as camera.fpa
    path_to_save, now = save_run_parameters(args.path, params, args)
    blackbody, camera, oven = init_devices(path_to_save=path_to_save, params=params)
    wait_for_devices_to_start(blackbody, camera, oven)
    blackbody.set_temperature_non_blocking(args.blackbody_start)

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
    oven.setpoint = 120  # the Soft limit of the oven is 120C
    filename = f"{now}.npz" if not args.filename else Path(args.filename).with_suffix('.npz')

    t_ffc = wait_for_fpa(t_ffc=args.ffc, camera=camera, wait_time_camera=TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)

    # start measurements
    minutes_in_chunk = int(args.minutes_in_chunk)
    assert minutes_in_chunk > 0, f'argument minutes_in_chunk must be > 0, got {minutes_in_chunk}.'
    for idx in count(start=1, step=1):
        if continuous_collection(bb_generator=bb_generator, blackbody=blackbody, camera=camera,
                                 n_samples=args.n_samples, time_to_collect_minutes=minutes_in_chunk, 
                                 filename=f"{now}_{idx}.npz", path_to_save=path_to_save, limit_fpa=limit_fpa):
            oven.setpoint = 0  # turn the oven off
            limit_fpa = None
