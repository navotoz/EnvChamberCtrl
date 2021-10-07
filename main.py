import signal
from functools import partial
from threading import Thread
from tkinter import TclError

import utils.constants as const
from devices.Oven.make_oven_program import make_oven_basic_prog
from devices.Oven.plots import plot_btn_func
from gui.experiment import thread_run_experiment
from gui.makers import make_frames, make_buttons
from gui.processes import semaphore_plot_proc, logger, handlers
from gui.tools import update_status_label, set_buttons_by_devices_status, \
    browse_btn_func, th_cam_t_getter, update_spinbox_parameters_devices_states, get_device_status, \
    disable_fields_and_buttons, dict_variables
from gui.windows import open_upload_window, open_viewer_window


def _stop() -> None:
    try:
        camera.terminate()
    except ():
        pass
    try:
        oven.terminate()
    except ():
        pass
    try:
        blackbody.__del__()
    except ():
        pass
    event_stop.set()
    [semaphore_plot_proc.release() for _ in range(3)]


def close_gui(*kwargs) -> None:
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


def signal_handler(sig, frame):
    close_gui()


def func_stop_run() -> None:
    _stop()


def func_start_run_loop() -> None:
    root.focus_set()
    disable_fields_and_buttons(root, buttons_dict)
    update_status_label(frames_dict[const.FRAME_STATUS], const.WORKING)
    thread_experiment.start()


devices_dict = dict().fromkeys([const.CAMERA_NAME, const.OVEN_NAME, const.BLACKBODY_NAME,
                                const.SCANNER_NAME, const.FOCUS_NAME])
root, frames_dict, path_to_save = make_frames(logger, handlers, devices_dict)
root.protocol('WM_DELETE_WINDOW', close_gui)
signal.signal(signal.SIGINT, close_gui)
signal.signal(signal.SIGTERM, close_gui)
devices_dict[const.CAMERA_NAME] = camera_cmd
devices_dict[const.BLACKBODY_NAME] = blackbody_cmd
devices_dict[const.OVEN_NAME] = oven_cmd
devices_dict[const.OVEN_NAME].send((const.EXPERIMENT_SAVE_PATH, path_to_save))
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

dict_variables[const.SETTLING_TIME_MINUTES].pipe = oven_cmd
dict_variables[const.SETTLING_TIME_MINUTES].set(dict_variables[const.SETTLING_TIME_MINUTES].get())

th_cam_temp_getter = Thread(target=th_cam_t_getter, name='th_cam_t_getter', daemon=True,
                            args=(frames_dict[const.FRAME_TEMPERATURES])).start()
frames_dict[const.FRAME_PROGRESSBAR].nametowidget(const.PROGRESSBAR).config(length=root.winfo_width())

thread_experiment = Thread(target=thread_run_experiment, name='th_run_experiment', daemon=False,
                           kwargs=dict(frames_dict=frames_dict, devices_dict=devices_dict))
root.mainloop()
