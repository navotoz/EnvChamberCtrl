from itertools import count
import sys
import threading as th
from multiprocessing import Process, Semaphore
from pathlib import Path
from time import sleep, time_ns

from devices.Camera import INIT_CAMERA_PARAMETERS
from devices.Camera.CameraProcess import TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS
from devices.Oven.OvenProcess import OVEN_RECORDS_FILENAME
from devices.Oven.plots import mp_realttime_plot
from utils.args import args_var_bb_fpa
from utils.bb_iterators import TbbGenRand, TbbGenSawTooth
from utils.common import continuous_collection, mp_save_measurements_to_zip, wait_for_devices_to_start, init_devices, \
    save_run_parameters, wait_for_fpa

sys.path.append(str(Path().cwd().parent))


def th_t_cam_getter():
    while True:
        try:
            oven.set_camera_temperatures(fpa=camera.fpa, housing=camera.housing)
        except (BrokenPipeError, ValueError, TypeError, AttributeError, RuntimeError):
            pass
        sleep(TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)


def th_oven_control():
    INCREMENT_CELSIUS = 1
    TIME_TO_RISE_MINUTES = 10
    INITAL_OVEN_SETPOINT = 22
    t_rise_ns = TIME_TO_RISE_MINUTES * 60 * 1e9
    oven.setpoint = INITAL_OVEN_SETPOINT  # initial setpoint
    while True:
        time_start = time_ns()
        while time_ns() - time_start < t_rise_ns and camera.fpa < limit_fpa:
            sleep(5)
        if camera.fpa >= limit_fpa:
            while True:
                try:
                    oven.setpoint = 0
                    print(f'\nFPA limit {limit_fpa // 100} reached. Oven set to 0C\n', flush=True)
                    return
                except (BrokenPipeError, ValueError, TypeError, AttributeError, RuntimeError):
                    sleep(1)
        try:
            oven.setpoint = oven.setpoint + INCREMENT_CELSIUS
        except (BrokenPipeError, ValueError, TypeError, AttributeError, RuntimeError):
            pass


if __name__ == "__main__":
    print('\n###### TURN ON BOTH OVEN SWITCHES ######\n')
    args = args_var_bb_fpa()
    if args.random:
        bb_generator = TbbGenRand(bb_min=args.blackbody_min, bb_max=args.blackbody_max, bins=args.bins)
    else:
        bb_generator = TbbGenSawTooth(bb_min=args.blackbody_min, bb_max=args.blackbody_max,
                                      bb_start=args.blackbody_start, bb_inc=args.blackbody_increments,
                                      bb_is_decreasing=args.blackbody_is_decreasing)
    if args.n_samples <= 0:
        raise ValueError(f'n_samples must be > 0, got {args.n_samples}')
    assert args.ffc == 0 or args.ffc > 1000, f'FFC must be either 0 or given in [100C] range, got {args.ffc}'
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = int(args.tlinear)
    if args.ffc == 0:
        params['ffc_mode'] = 'auto'
        params['ffc_period'] = 1800  # automatic FFC every 30 seconds
    else:
        params['ffc_mode'] = 'external'
        params['ffc_period'] = 0
    params['ffc_temp_delta'] = 1000
    params['lens_number'] = args.lens_number
    print(f'Lens Number = {args.lens_number}', flush=True)
    limit_fpa = args.limit_fpa
    print(f'Maximal FPA {limit_fpa}C')
    limit_fpa *= 100  # C -> 100C, same as camera.fpa
    path_to_save, now = save_run_parameters(args.path, params, args)
    blackbody, camera, oven = init_devices(path_to_save=path_to_save, params=params)
    wait_for_devices_to_start(blackbody, camera, oven)
    blackbody.set_temperature_non_blocking(args.blackbody_start)
    th_oven = th.Thread(target=th_oven_control, name='th_oven_control', daemon=True)
    th_oven.start()

    # wait for the records file to be created
    while not (path_to_save / OVEN_RECORDS_FILENAME).is_file():
        sleep(1)

    # init thread
    th_cam_getter = th.Thread(target=th_t_cam_getter, name='th_cam2oven_temperatures', daemon=True)
    th_cam_getter.start()

    # realtime plot of temperatures
    mp_plot = Process(target=mp_realttime_plot, args=(path_to_save,), name='mp_realtime_plot', daemon=True)
    mp_plot.start()

    # save measurements to zip
    lock_zip = Semaphore(value=0)
    mp_zip_saver = Process(target=mp_save_measurements_to_zip, args=(path_to_save, lock_zip, ), name='mp_zip_saver',
                           daemon=True)
    mp_zip_saver.start()

    # start measurements
    filename = f"{now}.npz" if not args.filename else Path(args.filename).with_suffix('.npz')
    t_ffc = wait_for_fpa(t_ffc=args.ffc, camera=camera, wait_time_camera=TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)
    minutes_in_chunk = int(args.minutes_in_chunk)
    assert minutes_in_chunk > 0, f'argument minutes_in_chunk must be > 0, got {minutes_in_chunk}.'
    for idx in count(start=1, step=1):
        continuous_collection(bb_generator=bb_generator, blackbody=blackbody, camera=camera,
                              n_samples=args.n_samples, time_to_collect_minutes=minutes_in_chunk,
                              sample_rate=args.sample_rate,
                              filename=f"{now}_{idx}.npz", path_to_save=path_to_save)
        lock_zip.release()  # release the lock to save the measurements to zip
