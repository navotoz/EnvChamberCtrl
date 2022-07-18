import sys
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
from utils.common import collect_measurements, save_results, wait_for_devices_to_start, init_devices, \
    save_run_parameters

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

    # if args.ffc == 0 performs FFC before each measurement. Else perform only on the given temperature
    t_ffc = args.ffc
    if t_ffc != 0:
        while True:
            try:
                fpa = camera.fpa
                if fpa and fpa >= t_ffc:
                    while not camera.ffc:
                        sleep(0.5)
                    break
            except (BrokenPipeError, ValueError, TypeError, AttributeError, RuntimeError):
                pass
            finally:
                sleep(2 * TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS)

    # start measurements
    dict_meas = collect_measurements(bb_generator=bb_generator, blackbody=blackbody, camera=camera,
                                     n_samples=args.n_samples, limit_fpa=limit_fpa, t_ffc=t_ffc)
    oven.setpoint = 0  # turn the oven off
    dict_meas['camera_params'] = params.copy()
    dict_meas['arguments'] = vars(args)
    save_results(path_to_save=path_to_save, filename=filename, dict_meas=dict_meas)
