import logging
import multiprocessing as mp
from datetime import datetime
from functools import partial
from itertools import product
from pathlib import Path
from threading import Thread, Semaphore
from time import sleep

import numpy as np

from devices.Oven.ThreadOvenCtrl import thread_handle_oven_temperature, thread_collect_oven_temperatures
from devices.Oven.make_oven_program import make_oven_basic_prog
from devices.Oven.plots import plot_btn_func
from experiments.analyze import process_plot_images_comparison
from gui.makers import make_frames, make_buttons
from gui.mask import make_mask_win_and_save
from gui.utils import apply_value_and_make_filename, disable_fields_and_buttons, \
    update_status_label, get_values_list, ThreadedSyncFlag, reset_all_fields, set_buttons_by_devices_status, \
    browse_btn_func, get_inner_temperatures, thread_get_fpa_housing_temperatures, \
    update_spinbox_parameters_devices_states
from gui.windows import open_upload_window, open_viewer_window
from utils.constants import *
from utils.logger import make_logger, make_logging_handlers
from utils.tools import wait_for_time, normalize_image, get_time, check_and_make_path

handlers = make_logging_handlers(logfile_path=Path('log/log.txt'), verbose=True)
logger = make_logger('GUI', handlers=handlers, level=logging.INFO)

semaphore_oven_sync = Semaphore(0)
semaphore_experiment_sync = Semaphore(0)
semaphore_plot_proc = mp.Semaphore(0)
semaphore_mask_sync = Semaphore(0)
flag_run_experiment = ThreadedSyncFlag()


def _stop():
    flag_run_experiment.set(False)
    semaphore_plot_proc.release()
    semaphore_mask_sync.release()
    semaphore_experiment_sync.release()


def close_gui() -> None:
    _stop()
    semaphore_oven_sync.release()
    sleep(3)
    root.destroy()
    exit()


def func_stop_run() -> None:
    _stop()


def thread_run_experiment(semaphore_mask: Semaphore, output_path: Path):
    global flag_run_experiment
    semaphore_mask.acquire()
    kwargs = dict(devices_dict=devices_dict, flag_run_experiment=flag_run_experiment,
                  frame=frames_dict[FRAME_TEMPERATURES], path_to_log=output_path, logger=devices_dict[OVEN_NAME].log)
    Thread(target=thread_collect_oven_temperatures, daemon=True, name='th_oven_getter', kwargs=kwargs).start()
    kwargs.pop('path_to_log')
    kwargs.pop('logger')  # oven logger
    kwargs['semaphore_oven_sync'] = semaphore_oven_sync
    kwargs['semaphore_experiment_sync'] = semaphore_experiment_sync
    kwargs['logger'] = logger  # gui logger
    Thread(target=thread_handle_oven_temperature, daemon=True, name='th_oven_setter', kwargs=kwargs).start()

    flag_run_experiment.set(True)
    proc_plot = mp.Process(kwargs=dict(path_to_experiment=output_path, semaphore=semaphore_plot_proc,
                                       flag=flag_run_experiment), name=f'proc_plot_res_{get_time().strftime("%H%M%S")}',
                           target=process_plot_images_comparison, daemon=True)
    proc_plot.start()
    output_path /= 'images'
    check_and_make_path(output_path)
    while flag_run_experiment:
        semaphore_experiment_sync.acquire()
        frames_dict[FRAME_PROGRESSBAR].nametowidget(PROGRESSBAR).stop()  # resets the progress bar

        # make current values list from GUI
        n_images_per_iteration = int(frames_dict[FRAME_PARAMS].getvar(CAMERA_NAME + INC_STRING))
        values_list, total_stops = get_values_list(frames_dict[FRAME_PARAMS], devices_dict)
        total_images = total_stops * n_images_per_iteration
        permutations = list(product(*values_list))

        logger.info(f"Experiment started. Running {total_images} images in total.")
        for blackbody_temperature, scanner_angle, focus in permutations:
            if blackbody_temperature == -float('inf'):
                flag_run_experiment.set(False)
            if not flag_run_experiment:
                logger.warning('Stopped the experiment.')
                break
            f_name = apply_value_and_make_filename(blackbody_temperature, scanner_angle, focus, devices_dict, logger)
            logger.info(f"Blackbody temperature {blackbody_temperature}C is set.")
            grab = wait_for_time(devices_dict[CAMERA_NAME].grab, wait_time_in_nsec=2e8)
            t_fpa = get_inner_temperatures(frames_dict[FRAME_TEMPERATURES], T_FPA)
            t_housing = get_inner_temperatures(frames_dict[FRAME_TEMPERATURES], T_HOUSING)
            logger.debug(f"FPA {t_fpa:.2f}C Housing {t_housing:.2f}")
            f_name += f"fpa_{t_fpa:.2f}_housing_{t_housing:.2f}_"
            devices_dict[CAMERA_NAME].ffc()  # calibrate
            for i in range(1, n_images_per_iteration + 1):
                if not flag_run_experiment:
                    break
                img = grab()
                f_name_to_save = str(output_path / f"{f_name}{i}|{n_images_per_iteration}")
                np.save(f_name_to_save, img)
                normalize_image(img).save(f_name_to_save, format='jpeg')
                logger.debug(f"Taken {i} image")
                frames_dict[FRAME_PROGRESSBAR].nametowidget(PROGRESSBAR).step(1 / total_images * 100)
                frames_dict[FRAME_PROGRESSBAR].nametowidget(PROGRESSBAR).update_idletasks()

        logger.info(f"Experiment ended.")
        blackbody_temperature = permutations[0][0]
        if blackbody_temperature and blackbody_temperature != -float('inf'):
            Thread(None, devices_dict[BLACKBODY_NAME], 'th_bb_reset', (blackbody_temperature,), daemon=True).start()
        semaphore_oven_sync.release()
        semaphore_plot_proc.release()
    semaphore_plot_proc.release()
    proc_plot.kill()
    reset_all_fields(root, buttons_dict, devices_dict)


def func_start_run_loop() -> None:
    disable_fields_and_buttons(root, buttons_dict)
    update_status_label(frames_dict[FRAME_STATUS], WORKING)

    # set ffc here because the mask process is blocking
    while not devices_dict[CAMERA_NAME].ffc_mode_select('ext'):
        pass

    # make output path
    name = frames_dict[FRAME_HEAD].getvar(EXPERIMENT_NAME)
    output_path = Path(frames_dict[FRAME_BUTTONS].getvar(EXPERIMENT_SAVE_PATH))
    output_path /= Path(datetime.now().strftime("%Y%m%d_h%Hm%Ms%S") + (f'_{name}' if name else ''))
    check_and_make_path(output_path)

    # apply mask to camera output
    make_mask_win_and_save(devices_dict[CAMERA_NAME], semaphore_mask_sync, output_path)

    kwargs = dict(semaphore_mask=semaphore_mask_sync, output_path=output_path)
    Thread(target=thread_run_experiment, kwargs=kwargs, name='th_run_experiment', daemon=False).start()


devices_dict = dict().fromkeys([OVEN_NAME, CAMERA_NAME, BLACKBODY_NAME, SCANNER_NAME, FOCUS_NAME])
root, frames_dict = make_frames(logger, handlers, devices_dict)
root.protocol('WM_DELETE_WINDOW', close_gui)

func_dict = {BUTTON_BROWSE: partial(browse_btn_func, f_btn=frames_dict[FRAME_BUTTONS], f_path=frames_dict[FRAME_PATH]),
             BUTTON_STOP: func_stop_run,
             BUTTON_START: func_start_run_loop,
             BUTTON_VIEWER: partial(open_viewer_window, devices_dict=devices_dict, name=CAMERA_NAME),
             BUTTON_UPLOAD: open_upload_window,
             BUTTON_OVEN_PROG: make_oven_basic_prog,
             BUTTON_PLOT: partial(plot_btn_func, frame_button=frames_dict[FRAME_BUTTONS])}
buttons_dict = make_buttons(frames_dict[FRAME_BUTTONS], func_dict)

Thread(target=thread_get_fpa_housing_temperatures, name='th_get_fpa_housing_temperatures',
       args=(devices_dict, frames_dict[FRAME_TEMPERATURES], flag_run_experiment,), daemon=True).start()

update_status_label(frames_dict[FRAME_STATUS], READY)
update_spinbox_parameters_devices_states(root.nametowidget(FRAME_PARAMS), devices_dict)
set_buttons_by_devices_status(root.nametowidget(FRAME_BUTTONS), devices_dict)

root.mainloop()
