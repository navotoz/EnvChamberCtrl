import sys
import threading as th
from itertools import count
from multiprocessing import Process, Semaphore
from pathlib import Path
from time import sleep

from tqdm import tqdm
from devices.BlackBodyCtrl import BlackBodyThread

from devices.Camera import INIT_CAMERA_PARAMETERS
from devices.Camera.CameraProcess import TEMPERATURE_ACQUIRE_FREQUENCY_SECONDS
from devices.Oven.OvenProcess import OVEN_RECORDS_FILENAME, set_oven_and_settle
from devices.Oven.plots import mp_realttime_plot
from utils.args import args_fpa_with_ffc
from utils.bb_iterators import TbbGenSawTooth
from utils.common import init_camera_and_oven, save_run_parameters, \
    continuous_collection, wait_for_devices_without_bb, mp_save_measurements_to_zip
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
    args = args_fpa_with_ffc()
    bb_generator = TbbGenSawTooth(bb_min=args.blackbody_min, bb_max=args.blackbody_max, bb_start=args.blackbody_start,
                                  bb_inc=args.blackbody_increments, bb_is_decreasing=args.blackbody_is_decreasing)
    if args.n_samples <= 0:
        raise ValueError(f'n_samples must be > 0, got {args.n_samples}')
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = int(args.tlinear)
    params['ffc_mode'] = 'external'
    params['ffc_period'] = 0
    params['ffc_temp_delta'] = 1000
    params['lens_number'] = args.lens_number
    print(f'Lens Number = {args.lens_number}', flush=True)
    oven_temperature = args.oven_temperature
    settling_time = args.settling_time
    print(f'Oven setpoint {oven_temperature}C.\nSettling time: {settling_time} minutes.', flush=True)
    path_to_save, now = save_run_parameters(args.path, params, args)
    camera, oven = init_camera_and_oven(path_to_save=path_to_save, params=params)
    wait_for_devices_without_bb(camera, oven)

    # wait for the records file to be created
    while not (path_to_save / OVEN_RECORDS_FILENAME).is_file():
        sleep(1)

    # init thread
    th_cam_getter = th.Thread(target=th_t_cam_getter, name='th_cam2oven_temperatures', daemon=True)
    th_cam_getter.start()

    # realtime plot of temperatures
    mp_plot = Process(target=mp_realttime_plot, args=(path_to_save,), name='mp_realtime_plot', daemon=True)
    mp_plot.start()

    set_oven_and_settle(setpoint=oven_temperature, settling_time_minutes=settling_time, oven=oven, camera=camera)

    # start the blackbody and wait for it to connect
    blackbody = BlackBodyThread(logfile_path=None, output_folder_path=path_to_save)
    blackbody.start()
    with tqdm(desc='Waiting for blackbody to connect') as progressbar:
        while not blackbody.is_connected:
            progressbar.update()
            progressbar.set_postfix_str(f'FPA {camera.fpa / 100:.1f}C')
            sleep(1)
    blackbody.set_temperature_non_blocking(args.blackbody_start)
    sleep(1)  # to flush the tqdm progress bar

    # save measurements to zip
    lock_zip = Semaphore(value=0)
    mp_zip_saver = Process(target=mp_save_measurements_to_zip, args=(path_to_save, lock_zip, ), name='mp_zip_saver',
                           daemon=True)
    mp_zip_saver.start()

    # perform FFC after ambient temperature is settled
    while not camera.ffc:
        sleep(0.5)
    print(f'FFC performed at {camera.fpa / 100:.1f}C', flush=True)

    # start measurements
    minutes_in_chunk = int(args.minutes_in_chunk)
    assert minutes_in_chunk > 0, f'argument minutes_in_chunk must be > 0, got {minutes_in_chunk}.'
    for idx in count(start=1, step=1):
        continuous_collection(bb_generator=bb_generator, blackbody=blackbody, camera=camera,
                              n_samples=args.n_samples, time_to_collect_minutes=minutes_in_chunk,
                              sample_rate=args.sample_rate, filename=f"{now}_{idx}.npz", path_to_save=path_to_save)
        lock_zip.release()
    oven.setpoint = 0  # turn the oven off
    print('######### END OF RUN #########', flush=True)
