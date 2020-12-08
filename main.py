import logging
import multiprocessing as mp
import signal
from datetime import datetime
from functools import partial
from itertools import product
from pathlib import Path
from threading import Thread, Semaphore
from time import sleep
from tkinter import TclError

import numpy as np
import yaml

from devices.Oven.OvenProcess import OvenCtrl
from devices.Oven.make_oven_program import make_oven_basic_prog
from devices.Oven.plots import plot_btn_func
from devices.Oven.utils import get_n_experiments, make_oven_temperatures_list
from gui.makers import make_frames, make_buttons
from gui.mask import make_mask_win_and_save
from gui.utils import apply_value_and_make_filename, disable_fields_and_buttons, \
    update_status_label, get_values_list, reset_all_fields, set_buttons_by_devices_status, \
    browse_btn_func, thread_get_fpa_housing_temperatures, getter_safe_variables, get_inner_temperatures, \
    update_spinbox_parameters_devices_states
from gui.windows import open_upload_window, open_viewer_window
from utils.analyze import process_plot_images_comparison
import utils.constants as const
from utils.logger import make_logger, make_logging_handlers
from utils.tools import normalize_image, get_time, check_and_make_path, SyncFlag

handlers = make_logging_handlers(logfile_path=Path('log/log.txt'), verbose=True)
logger = make_logger('GUI', handlers=handlers, level=logging.INFO)

oven_process: mp.Process
recv_temperature, send_temperature = mp.Pipe(duplex=False)
recv_is_temperature_set, send_is_temperature_set = mp.Pipe(duplex=False)
semaphore_plot_proc = mp.Semaphore(0)
semaphore_mask_sync = Semaphore(0)
flag_run = SyncFlag()


def _stop():
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
            bb_list = list(map(lambda x:abs(x - devices_dict[const.BLACKBODY_NAME].temperature), values_list[0]))
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
                f_name = apply_value_and_make_filename(blackbody_temperature, scanner_angle, focus, devices_dict,
                                                       logger)
                logger.info(f"Blackbody temperature {blackbody_temperature}C is set.")
                devices_dict[const.CAMERA_NAME].ffc()  # calibrate
                for i in range(1, n_images_per_iteration + 1):
                    if not flag_run:
                        break
                    sleep(0.2)
                    t_fpa = get_inner_temperatures(frames_dict[const.FRAME_TEMPERATURES], const.T_FPA)
                    t_housing = get_inner_temperatures(frames_dict[const.FRAME_TEMPERATURES], const.T_HOUSING)
                    # the precision of the housing temperature is 0.01C and the precision for the fpa is 0.1C
                    f_name_to_save = f_name + f"fpa_{t_fpa:.2f}_housing_{t_housing:.2f}_"
                    image = devices_dict[const.CAMERA_NAME].grab()
                    f_name_to_save = str(output_path / f"{f_name_to_save}{i}|{n_images_per_iteration}")
                    np.save(f_name_to_save, image)
                    normalize_image(image).save(f_name_to_save + '.jpeg', format='jpeg')
                    logger.debug(f"Taken {i} image")
                    frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).step(1 / total_images * 100)
                    frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).update_idletasks()
            idx += 1
            logger.info(f"Experiment ended.")
            blackbody_temperature = permutations[0][0]
            if blackbody_temperature and blackbody_temperature != -float('inf'):
                Thread(None, devices_dict[const.BLACKBODY_NAME], 'th_bb_reset',
                       (blackbody_temperature,), daemon=True).start()
            semaphore_plot_proc.release()
    send_temperature.send(0)
    semaphore_plot_proc.release()
    proc_plot.kill()
    reset_all_fields(root, buttons_dict, devices_dict)


def func_start_run_loop() -> None:
    global oven_process
    root.focus_set()
    disable_fields_and_buttons(root, buttons_dict)
    update_status_label(frames_dict[const.FRAME_STATUS], const.WORKING)

    # set ffc and gain here because the mask process is blocking
    devices_dict[const.CAMERA_NAME].n_retry = 10  # todo: check does changing the n_retry works?
    devices_dict[const.CAMERA_NAME].ffc_mode = const.INIT_CAMERA_PARAMETERS.get('ffc_mode', 'manual')
    devices_dict[const.CAMERA_NAME].isotherm = const.INIT_CAMERA_PARAMETERS.get('isotherm', 0)
    devices_dict[const.CAMERA_NAME].dde = const.INIT_CAMERA_PARAMETERS.get('dde', 0)
    devices_dict[const.CAMERA_NAME].tlinear = const.INIT_CAMERA_PARAMETERS.get('tlinear', 0)
    devices_dict[const.CAMERA_NAME].gain = const.INIT_CAMERA_PARAMETERS.get('gain', 'high')
    devices_dict[const.CAMERA_NAME].agc = const.INIT_CAMERA_PARAMETERS.get('agc', 'manual')
    devices_dict[const.CAMERA_NAME].sso = const.INIT_CAMERA_PARAMETERS.get('sso', 0)
    devices_dict[const.CAMERA_NAME].contrast = const.INIT_CAMERA_PARAMETERS.get('contrast', 0)
    devices_dict[const.CAMERA_NAME].brightness = const.INIT_CAMERA_PARAMETERS.get('brightness', 0)
    devices_dict[const.CAMERA_NAME].brightness_bias = const.INIT_CAMERA_PARAMETERS.get('brightness_bias', 0)
    devices_dict[const.CAMERA_NAME].cmos_depth = const.INIT_CAMERA_PARAMETERS.get('cmos_depth', 0)  # 14bit pre AGC
    devices_dict[const.CAMERA_NAME].correction_map = const.INIT_CAMERA_PARAMETERS.get('corr_mask', 0)  # off
    devices_dict[const.CAMERA_NAME].n_retry = 3
    # todo: CORRECTION MASK command?

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
                                is_dummy=oven_status == const.DEVICE_DUMMY, **getter_safe_variables())
        oven_process.start()

    # apply mask to camera output
    make_mask_win_and_save(devices_dict[const.CAMERA_NAME], semaphore_mask_sync, output_path)

    kwargs = dict(semaphore_mask=semaphore_mask_sync, output_path=output_path)
    Thread(target=thread_run_experiment, kwargs=kwargs, name='th_run_experiment', daemon=False).start()


devices_dict = dict().fromkeys([const.OVEN_NAME, const.CAMERA_NAME,
                                const.BLACKBODY_NAME, const.SCANNER_NAME, const.FOCUS_NAME])
root, frames_dict = make_frames(logger, handlers, devices_dict)
root.protocol('WM_DELETE_WINDOW', close_gui)
signal.signal(signal.SIGINT, close_gui)
signal.signal(signal.SIGTERM, close_gui)

func_dict = {const.BUTTON_BROWSE: partial(browse_btn_func, f_btn=frames_dict[const.FRAME_BUTTONS],
                                          f_path=frames_dict[const.FRAME_PATH]),
             const.BUTTON_STOP: func_stop_run,
             const.BUTTON_START: func_start_run_loop,
             const.BUTTON_VIEWER: partial(open_viewer_window, devices_dict=devices_dict, name=const.CAMERA_NAME),
             const.BUTTON_UPLOAD: open_upload_window,
             const.BUTTON_OVEN_PROG: make_oven_basic_prog,
             const.BUTTON_PLOT: partial(plot_btn_func, frame_button=frames_dict[const.FRAME_BUTTONS])}
buttons_dict = make_buttons(frames_dict[const.FRAME_BUTTONS], func_dict)

Thread(target=thread_get_fpa_housing_temperatures, name='th_get_fpa_housing_temperatures',
       args=(devices_dict, frames_dict[const.FRAME_TEMPERATURES], flag_run,), daemon=True).start()

update_status_label(frames_dict[const.FRAME_STATUS], const.READY)
update_spinbox_parameters_devices_states(root.nametowidget(const.FRAME_PARAMS), devices_dict)
set_buttons_by_devices_status(root.nametowidget(const.FRAME_BUTTONS), devices_dict)

root.mainloop()

# todo: the blackbody should visit temperatures by closest, not start from the lowest temperature.
# todo: check that the FTDI exits correctly
# todo: sometimes when starting the experiment the mask doesn't come out right
