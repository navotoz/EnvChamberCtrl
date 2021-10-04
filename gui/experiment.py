from itertools import product
from time import time_ns

import numpy as np
from datetime import datetime
from pathlib import Path
import threading as th
import multiprocessing as mp
import yaml

from devices.Oven.utils import make_oven_temperatures_list
from gui.mask import make_mask_win_and_save
import utils.constants as const
from gui.tools import get_values_list, set_value_and_make_filename
from utils.misc import check_and_make_path, normalize_image, save_average_from_images
from gui.processes import semaphore_mask_sync, camera_cmd, image_grabber, flag_run, oven_temperature, logger, \
    semaphore_plot_proc


def thread_run_experiment(output_path: Path, frames_dict: dict, devices_dict: dict):
    semaphore_mask_sync.acquire()

    flag_run.set(True)
    # proc_plot = mp.Process(kwargs=dict(path_to_experiment=output_path, semaphore=semaphore_plot_proc, flag=flag_run),
    #                        name=f'proc_plot_res_{get_time().strftime("%H%M%S")}',
    #                        target=process_plot_images_comparison, daemon=True)
    # proc_plot.start()

    output_path /= 'images'
    check_and_make_path(output_path)
    oven_temperatures_list = make_oven_temperatures_list()
    while flag_run and oven_temperatures_list:
        next_temperature = oven_temperatures_list.pop(0)
        oven_temperature.send(next_temperature)
        logger.info(f'Waiting for the Oven to settle near {next_temperature:.2f}C')
        if not oven_temperature.recv():  # checks if the oven proc set a stable temp.
            continue
        logger.info(f'Oven has settled near {next_temperature:.2f}C')
        frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).stop()  # resets the progress bar

        # make current values list from GUI
        n_images_per_iteration = int(frames_dict[const.FRAME_PARAMS].getvar(const.CAMERA_NAME + const.INC_STRING))
        values_list, total_stops = get_values_list(frames_dict[const.FRAME_PARAMS], devices_dict)
        total_images = total_stops * n_images_per_iteration

        # find closest blackbody temperature
        for _ in range(3):
            devices_dict[const.BLACKBODY_NAME].send((const.T_BLACKBODY, True))
            blackbody_temperature = devices_dict[const.BLACKBODY_NAME].recv()
        bb_list = list(map(lambda x: abs(x - blackbody_temperature), values_list[0]))
        if bb_list[0] > bb_list[-1]:
            values_list[0] = np.flip(values_list[0])
        permutations = list(product(*values_list))

        logger.info(f"Experiment started. Running {total_images} images in total.")
        for blackbody_temperature, scanner_angle, focus in permutations:
            if blackbody_temperature == -float('inf'):
                flag_run.set(False)
            if not flag_run:
                logger.warning('Stopped the experiment.')
                break
            f_name = set_value_and_make_filename(blackbody_temperature, scanner_angle, focus, devices_dict, logger)
            t_bb = round(blackbody_temperature * 100)
            logger.info(f"Blackbody temperature {blackbody_temperature}C is set.")
            timer_t_bb = time_ns()

            ffc_every_temperature = frames_dict[const.FRAME_TEMPERATURES]
            ffc_every_temperature = ffc_every_temperature.nametowidget(const.FFC_EVERY_T).getvar(const.FFC_EVERY_T)
            if ffc_every_temperature == '1':
                devices_dict[const.CAMERA_NAME].send((const.FFC, True))  # calibrate

            image_grabber.send(n_images_per_iteration)
            images_dict = image_grabber.recv()
            if images_dict is None or images_dict is False:
                break
            frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).step(n_images_per_iteration /
                                                                                      total_images * 100)
            frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).update_idletasks()
            mp.Process(target=_mp_save_images, kwargs=dict(images_dict=images_dict.copy(),
                                                           f_name=f_name,
                                                           output_path=output_path,
                                                           t_bb=t_bb),
                       name=f'SaveImages', daemon=False).start()
            semaphore_plot_proc.release()
            logger.info(f"Finished Blackbody temperature {blackbody_temperature}C "
                        f"after {float(time_ns()-timer_t_bb)*1e-9:.1f} seconds.")
        save_average_from_images(output_path)
        logger.info(f"Experiment for T_FPA"
                    f"{frames_dict[const.FRAME_TEMPERATURES].getvar(const.T_FPA):.1f}"
                    f" at Oven temperature of {float(next_temperature):.1f} ended.")
    semaphore_plot_proc.release()
    devices_dict[const.OVEN_NAME].send((const.BUTTON_START, False))
    # proc_plot.kill()
    # exit()


def init_experiment(frames_dict: dict, devices_dict: dict) -> None:
    # set the parameters for the experiment
    devices_dict[const.CAMERA_NAME].send((const.CAMERA_PARAMETERS, const.INIT_CAMERA_PARAMETERS))
    devices_dict[const.CAMERA_NAME].recv()

    # make output path
    name = frames_dict[const.FRAME_HEAD].getvar(const.EXPERIMENT_NAME)
    output_path = Path(frames_dict[const.FRAME_BUTTONS].getvar(const.EXPERIMENT_SAVE_PATH))
    output_path /= Path(datetime.now().strftime("%Y%m%d_h%Hm%Ms%S") + (f'_{name}' if name else ''))
    check_and_make_path(output_path)
    with open(output_path / 'CameraParams.yaml', 'w') as fp:
        yaml.safe_dump(const.INIT_CAMERA_PARAMETERS, fp)
    devices_dict[const.OVEN_NAME].send((const.EXPERIMENT_SAVE_PATH, output_path))
    assert devices_dict[const.OVEN_NAME].recv() == output_path, 'Oven could not set output path.'
    devices_dict[const.OVEN_NAME].send((const.BUTTON_START, True))

    ffc_every_temperature = frames_dict[const.FRAME_TEMPERATURES]
    ffc_every_temperature = ffc_every_temperature.nametowidget(const.FFC_EVERY_T).getvar(const.FFC_EVERY_T)
    if ffc_every_temperature == '0':
        t_ffc = frames_dict[const.FRAME_HEAD].nametowidget(f'sp {const.FFC_TEMPERATURE}').get()
        devices_dict[const.CAMERA_NAME].send((const.FFC_TEMPERATURE, t_ffc))
        devices_dict[const.CAMERA_NAME].recv()
    else:
        devices_dict[const.CAMERA_NAME].send((const.FFC, True))  # calibrate

    # apply mask to camera output
    make_mask_win_and_save(camera_cmd, image_grabber, semaphore_mask_sync, output_path)
    th.Thread(target=thread_run_experiment, args=(output_path, frames_dict, devices_dict,),
              name='th_run_experiment', daemon=False).start()


def _mp_save_images(images_dict: dict, f_name: str, output_path: Path, t_bb: int):
    n_images_per_iteration = len(images_dict.values())
    for (t_fpa, t_housing, idx), image in images_dict.items():
        path = output_path / f'{const.T_FPA}_{t_fpa}' / f'{const.BLACKBODY_NAME}_{t_bb}'
        f_name_to_save = f_name + f"fpa_{t_fpa}_housing_{t_housing}_"
        f_name_to_save = path / f"{f_name_to_save}{idx}of{n_images_per_iteration}"
        parent = Path(f_name_to_save).parent
        if not parent.is_dir():
            parent.mkdir(parents=True)
        np.save(str(f_name_to_save), image)
        normalize_image(image).save(str(f_name_to_save) + '.jpeg', format='jpeg')
