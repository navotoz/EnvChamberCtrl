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

import signal
from functools import partial
from threading import Thread
from tkinter import TclError

import utils.constants as const
from devices.Oven.make_oven_program import make_oven_basic_prog
from devices.Oven.plots import plot_btn_func
from gui.makers import make_frames, make_buttons, SafeDoubleVar
from gui.processes import oven, mp_values_dict, oven_cmd, camera_cmd, image_grabber, \
    event_stop, semaphore_plot_proc, semaphore_mask_sync, logger, handlers
from gui.tools import update_status_label, set_buttons_by_devices_status, \
    browse_btn_func, thread_log_fpa_housing_temperatures, update_spinbox_parameters_devices_states, get_device_status, \
    disable_fields_and_buttons, dict_variables
from gui.windows import open_upload_window, open_viewer_window
from utils.tools import SyncFlag
from gui.experiment import init_experiment


def _stop() -> None:
    event_stop.set()
    flag_run.set(False)
    [semaphore_plot_proc.release() for x in range(3)]
    [semaphore_mask_sync.release() for x in range(3)]


def close_gui(*kwargs) -> None:
    event_stop.set()
    _stop()
    for key in devices_dict.keys():
        devices_dict[key] = None
    try:
        oven.terminate()
        oven.join()
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


def func_start_run_loop():
    root.focus_set()
    disable_fields_and_buttons(root, buttons_dict)
    update_status_label(frames_dict[const.FRAME_STATUS], const.WORKING)
    init_experiment(frames_dict=frames_dict, devices_dict=devices_dict)


devices_dict = dict().fromkeys([const.CAMERA_NAME, const.OVEN_NAME, const.BLACKBODY_NAME,
                                const.SCANNER_NAME, const.FOCUS_NAME])
root, frames_dict, path_to_save = make_frames(logger, handlers, devices_dict)
root.protocol('WM_DELETE_WINDOW', close_gui)
signal.signal(signal.SIGINT, close_gui)
signal.signal(signal.SIGTERM, close_gui)
devices_dict[const.CAMERA_NAME] = camera_cmd
devices_dict[const.OVEN_NAME] = oven_cmd
devices_dict[const.OVEN_NAME].send((const.EXPERIMENT_SAVE_PATH,path_to_save ))
assert devices_dict[const.OVEN_NAME].recv() == path_to_save, 'Could not set oven output path.'

func_dict = {const.BUTTON_BROWSE: partial(browse_btn_func, f_btn=frames_dict[const.FRAME_BUTTONS],
                                          f_path=frames_dict[const.FRAME_PATH]),
             const.BUTTON_STOP: func_stop_run,
             const.BUTTON_START: func_start_run_loop,
             const.BUTTON_VIEWER: partial(open_viewer_window, camera_grabber=image_grabber,
                                          name=const.CAMERA_NAME),
             const.BUTTON_UPLOAD: open_upload_window,
             const.BUTTON_OVEN_PROG: make_oven_basic_prog,
             const.BUTTON_PLOT: partial(plot_btn_func, frame_button=frames_dict[const.FRAME_BUTTONS])}
buttons_dict = make_buttons(frames_dict[const.FRAME_BUTTONS], func_dict)

update_status_label(frames_dict[const.FRAME_STATUS], const.READY)
update_spinbox_parameters_devices_states(root.nametowidget(const.FRAME_PARAMS), devices_dict)
set_buttons_by_devices_status(root.nametowidget(const.FRAME_BUTTONS), devices_dict)
frames_dict[const.FRAME_PARAMS].nametowidget('camera_tau2').invoke()
if get_device_status(const.CAMERA_NAME, devices_dict[const.CAMERA_NAME]) == const.DEVICE_DUMMY:
    frames_dict[const.FRAME_PARAMS].nametowidget('camera_thermapp').invoke()

dict_variables[const.DELTA_TEMPERATURE].pipe = oven_cmd
dict_variables[const.DELTA_TEMPERATURE].set(dict_variables[const.DELTA_TEMPERATURE].get())
dict_variables[const.SETTLING_TIME_MINUTES].pipe = oven_cmd
dict_variables[const.SETTLING_TIME_MINUTES].set(dict_variables[const.SETTLING_TIME_MINUTES].get())

flag_run = SyncFlag()
Thread(target=thread_log_fpa_housing_temperatures, name='th_get_fpa_housing_temperatures',
       args=(frames_dict[const.FRAME_TEMPERATURES], mp_values_dict, flag_run,), daemon=True).start()

root.mainloop()

# todo: do a proper kill function for the new camera process
# todo: add commands into camera process
# todo: make BlackBody into a process. The process will have keep-alive feature
# todo: why does changing the values of "Minimal Setteling Time" have no effect during runtime
#todo: does all periferial buttons work?