# from datetime import datetime
# from pathlib import Path
# from threading import Thread
# from time import sleep
#
# from devices.Camera.Tau.Tau2Grabber import TeaxGrabber
# from gui.tools import thread_log_fpa_housing_temperatures
# from utils.logger import make_logging_handlers
# import utils.constants as const
# import tkinter as tk
#
# from utils.tools import SyncFlag
#
# flag_run = SyncFlag()
# devices_dict = {const.CAMERA_NAME:TeaxGrabber(logging_handlers=make_logging_handlers(Path('log/log.txt'), True))}
# Thread(target=thread_log_fpa_housing_temperatures, name='th_get_fpa_housing_temperatures',
#        args=(devices_dict, tk.Frame(), flag_run,), daemon=True).start()
#
#
# N_ITERS = 100
# devices_dict[const.CAMERA_NAME].ffc_mode = 'external'
# while True:
#     print(f'{datetime.now()}')
#     for i in range(N_ITERS):
#         devices_dict[const.CAMERA_NAME].grab()
#     devices_dict[const.CAMERA_NAME].ffc()


import logging
import multiprocessing as mp
import signal
from ctypes import c_wchar_p
from datetime import datetime
from functools import partial
from itertools import product
from pathlib import Path
from threading import Thread, Semaphore
from time import sleep
from tkinter import TclError

import numpy as np
import yaml

from devices.Camera.CameraProcess import CameraCtrl
from devices.Camera.utils import DuplexPipe
from devices.Oven.OvenProcess import OvenCtrl
from devices.Oven.make_oven_program import make_oven_basic_prog
from devices.Oven.plots import plot_btn_func
from devices.Oven.utils import get_n_experiments, make_oven_temperatures_list
from gui.makers import make_frames, make_buttons
from gui.mask import make_mask_win_and_save
from gui.tools import set_value_and_make_filename, disable_fields_and_buttons, \
    update_status_label, get_values_list, reset_all_fields, set_buttons_by_devices_status, \
    browse_btn_func, thread_log_fpa_housing_temperatures, getter_safe_oven_variables, get_inner_temperatures, \
    update_spinbox_parameters_devices_states, getter_safe_temperature_variables, get_device_status
from gui.windows import open_upload_window, open_viewer_window
from utils.analyze import process_plot_images_comparison
import utils.constants as const
from utils.logger import make_logger, make_logging_handlers
from utils.tools import normalize_image, get_time, check_and_make_path, SyncFlag, save_average_from_images

handlers = make_logging_handlers(logfile_path=Path('log/log.txt'), verbose=True)
logger = make_logger('GUI', handlers=handlers, level=logging.INFO)

oven_process: mp.Process
camera_process: mp.Process
recv_temperature, send_temperature = mp.Pipe(duplex=False)
recv_is_temperature_set, send_is_temperature_set = mp.Pipe(duplex=False)
semaphore_plot_proc = mp.Semaphore(0)
semaphore_mask_sync = Semaphore(0)
flag_run = SyncFlag()

recv_cam_type_proc, send_cam_type_main = mp.Pipe(duplex=False)
recv_cam_type_main, send_cam_type_proc = mp.Pipe(duplex=False)
cam_type_proc = DuplexPipe(send_cam_type_proc, recv_cam_type_proc, flag_run)
cam_type_main = DuplexPipe(send_cam_type_main, recv_cam_type_main, flag_run)

recv_image_proc, send_image_main = mp.Pipe(duplex=False)
recv_image_main, send_image_proc = mp.Pipe(duplex=False)
image_grabber_proc = DuplexPipe(send_image_proc, recv_image_proc, flag_run)
image_grabber_main = DuplexPipe(send_image_main, recv_image_main, flag_run)


def _stop() -> None:
    flag_run.set(False)
    [semaphore_plot_proc.release() for x in range(3)]
    [semaphore_mask_sync.release() for x in range(3)]


def close_gui(*kwargs) -> None:
    flag_run.set(False)
    _stop()
    for key in devices_dict.keys():
        devices_dict[key] = None
    try:
        oven_process.terminate()
        oven_process.join()
    except NameError:
        pass
    try:
        root.destroy()
    except TclError:
        pass
    exit(0)


def signal_handler(sig, frame):
    close_gui()


def func_stop_run() -> None:
    _stop()


def thread_run_experiment(semaphore_mask: Semaphore, output_path: Path):
    global flag_run
    semaphore_mask.acquire()

    flag_run.set(True)
    proc_plot = mp.Process(kwargs=dict(path_to_experiment=output_path, semaphore=semaphore_plot_proc,
                                       flag=flag_run), name=f'proc_plot_res_{get_time().strftime("%H%M%S")}',
                           target=process_plot_images_comparison, daemon=True)
    proc_plot.start()
    output_path /= 'images'
    check_and_make_path(output_path)
    oven_temperatures_list = make_oven_temperatures_list()
    while flag_run and oven_temperatures_list:
        next_temperature = oven_temperatures_list.pop(0)
        send_temperature.send(next_temperature)
        logger.info(f'Waiting for the Oven to settle near {next_temperature:.2f}C')
        while flag_run and not recv_is_temperature_set.poll(timeout=2):  # checks if the oven proc set a stable temp.
            continue
        recv_is_temperature_set.recv()  # to clear the PIPE
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
                devices_dict[const.CAMERA_NAME].ffc()  # calibrate
                for i in range(1, n_images_per_iteration + 1):
                    if not flag_run:
                        break
                    sleep(0.2)
                    t_fpa = get_inner_temperatures(frames_dict[const.FRAME_TEMPERATURES], const.T_FPA)
                    t_housing = get_inner_temperatures(frames_dict[const.FRAME_TEMPERATURES], const.T_HOUSING)
                    # the precision of the housing temperature is 0.01C and the precision for the fpa is 0.1C
                    path = output_path / f'{const.T_FPA}_{t_fpa}' / \
                           f'{const.BLACKBODY_NAME}_{int(blackbody_temperature * 100)}'
                    f_name_to_save = f_name + f"fpa_{t_fpa}_housing_{t_housing}_"
                    if (image := devices_dict[const.CAMERA_NAME].grab()) is None:
                        continue
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
    send_temperature.send(0)
    semaphore_plot_proc.release()
    proc_plot.kill()
    reset_all_fields(root, buttons_dict, devices_dict)


def func_start_run_loop() -> None:
    global oven_process
    root.focus_set()
    disable_fields_and_buttons(root, buttons_dict)
    update_status_label(frames_dict[const.FRAME_STATUS], const.WORKING)

    # set the parameters for the experiment
    devices_dict[const.CAMERA_NAME].set_params_by_dict(const.INIT_CAMERA_PARAMETERS)

    # make output path
    name = frames_dict[const.FRAME_HEAD].getvar(const.EXPERIMENT_NAME)
    output_path = Path(frames_dict[const.FRAME_BUTTONS].getvar(const.EXPERIMENT_SAVE_PATH))
    output_path /= Path(datetime.now().strftime("%Y%m%d_h%Hm%Ms%S") + (f'_{name}' if name else ''))
    check_and_make_path(output_path)
    with open(output_path / 'CameraParams.yaml', 'w') as fp:
        yaml.safe_dump(const.INIT_CAMERA_PARAMETERS, fp)

    # init oven
    oven_status = frames_dict[const.FRAME_PARAMS].getvar(f"device_status_{const.OVEN_NAME}")
    if oven_status != const.DEVICE_OFF:
        oven_process = OvenCtrl(logging_handlers=handlers,
                                log_path=output_path, recv_temperature=recv_temperature,
                                send_temperature_is_set=send_is_temperature_set, flag_run=flag_run,
                                is_dummy=oven_status == const.DEVICE_DUMMY, **getter_safe_oven_variables())
        oven_process.start()

    # apply mask to camera output
    make_mask_win_and_save(devices_dict[const.CAMERA_NAME], semaphore_mask_sync, output_path)

    kwargs = dict(semaphore_mask=semaphore_mask_sync, output_path=output_path)
    Thread(target=thread_run_experiment, kwargs=kwargs, name='th_run_experiment', daemon=False).start()


devices_dict = dict().fromkeys([const.CAMERA_NAME, const.OVEN_NAME,
                                const.BLACKBODY_NAME, const.SCANNER_NAME, const.FOCUS_NAME])
devices_dict[const.CAMERA_NAME] = cam_type_main
root, frames_dict = make_frames(logger, handlers, devices_dict)
root.protocol('WM_DELETE_WINDOW', close_gui)
signal.signal(signal.SIGINT, close_gui)
signal.signal(signal.SIGTERM, close_gui)

func_dict = {const.BUTTON_BROWSE: partial(browse_btn_func, f_btn=frames_dict[const.FRAME_BUTTONS],
                                          f_path=frames_dict[const.FRAME_PATH]),
             const.BUTTON_STOP: func_stop_run,
             const.BUTTON_START: func_start_run_loop,
             const.BUTTON_VIEWER: partial(open_viewer_window, camera_grabber=image_grabber_main,
                                          name=const.CAMERA_NAME),
             const.BUTTON_UPLOAD: open_upload_window,
             const.BUTTON_OVEN_PROG: make_oven_basic_prog,
             const.BUTTON_PLOT: partial(plot_btn_func, frame_button=frames_dict[const.FRAME_BUTTONS])}
buttons_dict = make_buttons(frames_dict[const.FRAME_BUTTONS], func_dict)


camera_process = CameraCtrl(logging_handlers=handlers,
                            image_pipe=image_grabber_proc,
                            flag_run=flag_run,
                            camera_type_pipe=cam_type_proc,
                            **getter_safe_temperature_variables())
camera_process.start()

Thread(target=thread_log_fpa_housing_temperatures, name='th_get_fpa_housing_temperatures',
       args=(frames_dict[const.FRAME_TEMPERATURES], flag_run,), daemon=True).start()

update_status_label(frames_dict[const.FRAME_STATUS], const.READY)
update_spinbox_parameters_devices_states(root.nametowidget(const.FRAME_PARAMS), devices_dict)
set_buttons_by_devices_status(root.nametowidget(const.FRAME_BUTTONS), devices_dict)
frames_dict[const.FRAME_PARAMS].nametowidget('camera_tau2').invoke()
if get_device_status(devices_dict[const.CAMERA_NAME]) == const.DEVICE_DUMMY:
    frames_dict[const.FRAME_PARAMS].nametowidget('camera_thermapp').invoke()

root.mainloop()

# todo: do a proper kill function for the new camera process
# todo: add commands into camera process
# todo: make BlackBody into a process. The process will have keep-alive feature
# todo: why does changing the values of "Minimal Setteling Time" have no effect during runtime
