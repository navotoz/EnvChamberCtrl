from itertools import product
from time import sleep

import  numpy as np
import tkinter as tk
from datetime import datetime
from pathlib import Path
import threading as th
import multiprocessing as mp
import yaml

from devices.Oven.utils import make_oven_temperatures_list, get_n_experiments
from gui.mask import make_mask_win_and_save
import utils.constants as const
from gui.tools import get_values_list, set_value_and_make_filename, get_inner_temperatures, tqdm_waiting
from utils.analyze import process_plot_images_comparison
from utils.tools import check_and_make_path, normalize_image, save_average_from_images, get_time
from gui.processes import semaphore_mask_sync, camera_cmd, image_grabber, flag_run, oven_temperature, logger, \
    semaphore_plot_proc, mp_values_dict


def thread_run_experiment(output_path: Path, frames_dict:dict, devices_dict:dict):
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
        idx = 0
        while idx < get_n_experiments(frame=frames_dict[const.FRAME_TEMPERATURES]):
            frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).stop()  # resets the progress bar

            # make current values list from GUI
            n_images_per_iteration = int(frames_dict[const.FRAME_PARAMS].getvar(const.CAMERA_NAME + const.INC_STRING))
            values_list, total_stops = get_values_list(frames_dict[const.FRAME_PARAMS], devices_dict)
            total_images = total_stops * n_images_per_iteration

            # find closest blackbody temperature
            bb_list = list(map(lambda x: abs(x - devices_dict[const.BLACKBODY_NAME].temperature), values_list[0]))
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
                logger.info(f"Blackbody temperature {blackbody_temperature}C is set.")
                devices_dict[const.CAMERA_NAME].send((const.FFC, True))  # calibrate
                t_fpa = round(get_inner_temperatures(frames_dict[const.FRAME_TEMPERATURES], const.T_FPA), -1)
                t_housing = get_inner_temperatures(frames_dict[const.FRAME_TEMPERATURES], const.T_HOUSING)
                for i in range(1, n_images_per_iteration + 1):
                    if not flag_run:
                        break
                    # the precision of the housing temperature is 0.01C and the precision for the fpa is 0.1C
                    path = output_path / f'{const.T_FPA}_{t_fpa}' / \
                           f'{const.BLACKBODY_NAME}_{int(blackbody_temperature * 100)}'
                    f_name_to_save = f_name + f"fpa_{t_fpa}_housing_{t_housing}_"
                    image_grabber.send(True)
                    if (image := image_grabber.recv()) is None:
                        break
                    f_name_to_save = str(path / f"{f_name_to_save}{i}of{n_images_per_iteration}")
                    if not path.is_dir():
                        path.mkdir(parents=True)
                    np.save(f_name_to_save, image)
                    normalize_image(image).save(f_name_to_save + '.jpeg', format='jpeg')
                    logger.debug(f"Taken {i} image")
                    frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).step(1 / total_images * 100)
                    frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).update_idletasks()
            idx += 1
            logger.info(f"Experiment ended.")
            semaphore_plot_proc.release()
            save_average_from_images(output_path)
    oven_temperature.send(0)
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

    # apply mask to camera output
    make_mask_win_and_save(camera_cmd, image_grabber, semaphore_mask_sync, output_path)
    th.Thread(target=thread_run_experiment, args=(output_path, frames_dict, devices_dict,),
              name='th_run_experiment', daemon=False).start()
