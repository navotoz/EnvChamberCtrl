import argparse
from datetime import datetime
from pathlib import Path
from time import sleep, time_ns
from typing import Union, Tuple
import multiprocessing as mp
from zipfile import ZIP_DEFLATED, ZipFile
import numpy as np
import yaml
from matplotlib import pyplot as plt
from tqdm import tqdm

from devices.BlackBodyCtrl import BlackBodyThread
from devices.Camera import T_FPA, T_HOUSING
from devices.Camera.CameraProcess import CameraCtrl
from devices.Oven.OvenProcess import OVEN_RECORDS_FILENAME, OvenCtrl
from devices.Oven.plots import plot_oven_records_in_path


def collect_measurements(bb_generator, blackbody, camera, n_samples, limit_fpa, t_ffc) -> dict:
    dict_meas = {}
    fpa = -float('inf')

    with tqdm() as progressbar:
        while True:
            for bb in bb_generator:
                blackbody.temperature = bb
                sleep(5)  # allows for thermal stabilization
                while t_ffc == 0 and not camera.ffc:
                    sleep(0.5)
                for _ in range(n_samples):
                    fpa = camera.fpa
                    dict_meas.setdefault('frames', []).append(camera.image)
                    dict_meas.setdefault('blackbody', []).append(bb)
                    dict_meas.setdefault(T_FPA, []).append(fpa)
                    dict_meas.setdefault(T_HOUSING, []).append(camera.housing)
                    dict_meas.setdefault('time_ns', []).append(time_ns())
                progressbar.update()
                progressbar.set_postfix_str(f'BB {bb:.1f}C, '
                                            f'FPA {fpa / 100:.1f}C, '
                                            f'Remaining {(limit_fpa - fpa) / 100:.1f}C')

                if fpa >= limit_fpa:
                    return dict_meas


def mp_save_measurements_to_zip(path_to_save: Path, lock_new_meas: mp.Semaphore):
    set_save_measurements = set()
    path_zip = path_to_save / 'measurements.zip'
    while True:
        lock_new_meas.acquire()
        for path in filter(lambda p: p not in set_save_measurements, path_to_save.glob('*.npz')):
            set_save_measurements.add(path)
            with ZipFile(path_zip, 'a', compression=ZIP_DEFLATED, compresslevel=9) as fp_zip:
                fp_zip.write(path, arcname=path.name)
            try:
                path.unlink()  # try to remove the file that was zipped
            except:
                pass


def continuous_collection(*, bb_generator, blackbody, camera, n_samples, time_to_collect_minutes: int,
                          sample_rate: int, filename: str, path_to_save: Path) -> None:
    assert time_to_collect_minutes > 0, f'time_to_collect_minutes must be positive, got {time_to_collect_minutes}.'
    dict_meas = {}
    fpa = -float('inf')

    time_to_collect_ns, t_start_ns = time_to_collect_minutes * 6e10, time_ns()
    with tqdm() as progressbar:
        for bb in bb_generator:
            blackbody.temperature = bb
            sleep(1)  # allows for thermal stabilization
            progressbar.set_description_str(f'BB {bb:.1f}C')
            for _ in range(n_samples):
                fpa = camera.fpa
                dict_meas.setdefault('frames', []).append(camera.image)
                dict_meas.setdefault('blackbody', []).append(bb)
                dict_meas.setdefault(T_FPA, []).append(fpa)
                dict_meas.setdefault(T_HOUSING, []).append(camera.housing)
                dict_meas.setdefault('time_ns', []).append(time_ns())
                progressbar.update()
            time_remaining = 1e-9 * (time_to_collect_ns - (time_ns() - t_start_ns))
            progressbar.set_postfix_str(f'FPA {fpa / 100:.1f}C, Remaining {time_remaining:.1f} Seconds.')
            if time_remaining <= 0:
                break
    if sample_rate != 1:
        dict_meas = {k: v[::sample_rate] for k, v in dict_meas.items()}
    save_results(path_to_save=path_to_save, filename=filename, dict_meas=dict_meas)


def save_results(path_to_save, filename, dict_meas):
    fpa = np.array(dict_meas[T_FPA]).astype('uint16')
    np.savez(str(path_to_save / filename),
             time_ns=dict_meas.get('time_ns', np.zeros_like(fpa)),
             time_limit_fpa_ns=dict_meas.get('time_limit_fpa_ns', 0),
             fpa=fpa,
             housing=np.array(dict_meas[T_HOUSING]).astype('uint16'),
             blackbody=(100 * np.array(dict_meas['blackbody'])).astype('uint16'),
             frames=np.stack(dict_meas['frames']).astype('uint16'))

    # save temperature plot
    try:
        fig, ax = plt.subplots()
        plot_oven_records_in_path(idx=0, fig=fig, ax=ax, path_to_log=path_to_save / OVEN_RECORDS_FILENAME)
        plt.savefig(path_to_save / 'temperature.png')
        plt.close()
    except:
        pass


def wait_for_devices_to_start(blackbody, camera, oven):
    sleep(1)
    with tqdm(desc="Waiting for devices to connect.") as progressbar:
        while not oven.is_connected or not camera.is_connected or not blackbody.is_connected:
            progressbar.set_postfix_str(f"Blackbody {'Connected' if blackbody.is_connected else 'Waiting'}, "
                                        f"Oven {'Connected' if oven.is_connected else 'Waiting'}, "
                                        f"Camera {'Connected' if camera.is_connected else 'Waiting'}")
            progressbar.update()
            sleep(1)
    print('Devices Connected.', flush=True)


def wait_for_devices_without_bb(camera: CameraCtrl, oven: OvenCtrl) -> None:
    sleep(1)
    with tqdm(desc="Waiting for devices to connect.") as progressbar:
        while not oven.is_connected or not camera.is_connected:
            progressbar.set_postfix_str(f"Oven {'Connected' if oven.is_connected else 'Waiting'}, "
                                        f"Camera {'Connected' if camera.is_connected else 'Waiting'}")
            progressbar.update()
            sleep(1)
    print('Devices Connected.', flush=True)


def init_camera_and_oven(*, path_to_save, params) -> Tuple[CameraCtrl, OvenCtrl]:
    camera = CameraCtrl(camera_parameters=params)
    camera.start()
    oven = OvenCtrl(logfile_path=None, output_path=path_to_save)
    oven.start()
    return camera, oven


def init_devices(*, path_to_save, params) -> Tuple[BlackBodyThread, CameraCtrl, OvenCtrl]:
    blackbody = BlackBodyThread(logfile_path=None, output_folder_path=path_to_save)
    blackbody.start()
    camera = CameraCtrl(camera_parameters=params)
    camera.start()
    oven = OvenCtrl(logfile_path=None, output_path=path_to_save)
    oven.start()
    return blackbody, camera, oven


def save_run_parameters(path: str, params: Union[dict, None], args: argparse.Namespace) -> Tuple[Path, str]:
    now = datetime.now().strftime("%Y%m%d_h%Hm%Ms%S")
    path_to_save = Path(path) / now
    if path_to_save.is_file():
        raise TypeError(
            f'Expected folder for path_to_save, given a file {path_to_save}.')
    elif not path_to_save.is_dir():
        path_to_save.mkdir(parents=True)
    if params is not None:
        with open(str(path_to_save / 'camera_params.yaml'), 'w') as fp:
            yaml.safe_dump(params, stream=fp, default_flow_style=False)
    with open(str(path_to_save / 'arguments.yaml'), 'w') as fp:
        yaml.safe_dump(vars(args), stream=fp, default_flow_style=False)
    return path_to_save, now


def wait_for_fpa(*, t_ffc: int, camera: CameraCtrl, wait_time_camera: Union[int, tuple]) -> int:
    """ if args.ffc == 0 performs FFC before each measurement. Else perform only on the given temperature """
    if t_ffc != 0:
        with tqdm(desc=f'Waiting for FPA temperature of {t_ffc / 100}C') as progressbar:
            while True:
                try:
                    fpa = camera.fpa
                    if fpa and fpa >= t_ffc:
                        while not camera.ffc:
                            sleep(0.5)
                        print(f'FFC performed at {fpa / 100:.1f}C', flush=True)
                        return t_ffc
                    progressbar.update()
                    try:
                        progressbar.set_postfix_str(f'FPA {fpa / 100:.1f}C, Remaining {(t_ffc - fpa) / 100:.1f}C')
                    except:
                        pass
                except (BrokenPipeError, ValueError, TypeError, AttributeError, RuntimeError):
                    pass
                finally:
                    sleep(2 * wait_time_camera)
    return t_ffc
