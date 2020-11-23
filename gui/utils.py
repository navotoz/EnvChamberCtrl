import tkinter as tk
from functools import partial
from logging import Logger
from math import prod
from multiprocessing import Event
from pathlib import Path
from time import sleep
from tkinter import filedialog as fd, Frame

import numpy as np
from PIL import Image

from utils.constants import *
from utils.tools import wait_for_time,  get_time, normalize_image, check_and_make_path
from tqdm import tqdm


def get_spinbox_value(sp_widget_name: str) -> float:
    if sp_widget_name not in dict_variables:
        return -float('inf')
    val = dict_variables[sp_widget_name].get()
    return float(val)


def set_spinbox_value(sp_widget_name: str, value: (float, int)) -> None:
    if isinstance(dict_variables[sp_widget_name], tk.DoubleVar):
        dict_variables[sp_widget_name].set(float(value))
    elif isinstance(dict_variables[sp_widget_name], tk.IntVar):
        dict_variables[sp_widget_name].set(int(value))


def validate_spinbox_range(var, from_, to_):
    num_type = int if isinstance(var, tk.IntVar) else float
    try:
        value = var.get()
        value = num_type(min(max(from_, value), to_))
        var.set(value=value)
    except (ValueError, tk.TclError):
        value = num_type(from_)
        var.set(value=value)
    finally:
        spinbox_validation()


def spinbox_validation(event: (tk.Event, None) = None) -> None:
    if event is not None and event.widget.get() == "":
        event.widget.insert(0, 0)

    for device_name in DEVICE_NAMES:
        if (min_value := get_spinbox_value(device_name + MIN_STRING)) == -float('inf'):
            continue
        min_value = np.clip(min_value, LIMIT_DICT[device_name][MIN_STRING], LIMIT_DICT[device_name][MAX_STRING])
        set_spinbox_value(device_name + MIN_STRING, min_value)
        if (max_value := get_spinbox_value(device_name + MAX_STRING)) == -float('inf'):
            continue
        max_value = np.clip(a=max_value,
                            a_min=max(min_value, LIMIT_DICT[device_name][MIN_STRING]),  # bounds max_value by min_value
                            a_max=LIMIT_DICT[device_name][MAX_STRING])
        set_spinbox_value(device_name + MAX_STRING, max_value)

        inc_value = max(LIMIT_DICT[device_name][RESOLUTION_STRING], get_spinbox_value(device_name + INC_STRING))
        inc_value = min(inc_value, max_value - min_value)
        set_spinbox_value(device_name + INC_STRING, inc_value)


def apply_value_and_make_filename(blackbody_temperature, scanner_angle, focus, devices_dict, logger: Logger) -> str:
    func = partial(apply_and_return_filename_str, devices_dict=devices_dict, logger=logger)
    f_name = f'{get_time().strftime(FMT_TIME)}_'
    f_name += func(blackbody_temperature, BLACKBODY_NAME)
    f_name += func(scanner_angle, SCANNER_NAME)
    f_name += func(focus, FOCUS_NAME)
    return f_name


def apply_and_return_filename_str(val: float, device_name: str, devices_dict: dict, logger: Logger) -> str:
    if val != -float('inf') and devices_dict[device_name]:
        devices_dict[device_name](val)
        logger.debug(f"{device_name.capitalize()} set to {val}.")
        return f"{device_name}_{val}_"
    return ''


def func_thread_grabber(device) -> Image.Image:
    return normalize_image(device.grab().astype('float32'))


def change_state_radiobuttons(root: tk.Tk, state: (tk.DISABLED, tk.NORMAL)):
    for name in DEVICE_NAMES:
        for dev_type in ['real', 'dummy', 'off']:
            if f"{dev_type}_{name}" in root.nametowidget(FRAME_PARAMS).children:
                root.nametowidget(FRAME_PARAMS).nametowidget(f"{dev_type}_{name}").config(state=state)


def change_spinbox_parameters_state(frame: tk.Frame, state):
    sp_names = map(lambda x: str(x).split('.')[-1], frame.winfo_children())
    sp_names = filter(lambda x: not x.startswith('!') and x.startswith(SP_PREFIX), sp_names)
    for sp_name in sp_names:
        change_spinbox_state(frame, sp_name, state)


def disable_fields_and_buttons(root: tk.Tk, buttons_dict: dict):
    change_spinbox_parameters_state(root.nametowidget(FRAME_PARAMS), tk.DISABLED)
    root.nametowidget(FRAME_HEAD).nametowidget(EXPERIMENT_NAME).config(state=tk.DISABLED)
    buttons_dict[BUTTON_BROWSE].config(state=tk.DISABLED)
    buttons_dict[BUTTON_START].config(state=tk.DISABLED, relief=tk.SUNKEN)
    buttons_dict[BUTTON_VIEWER].config(state=tk.DISABLED, relief=tk.SUNKEN)
    buttons_dict[BUTTON_UPLOAD].config(state=tk.DISABLED, relief=tk.SUNKEN)
    buttons_dict[BUTTON_STOP].config(state=tk.NORMAL)
    root.nametowidget(FRAME_BUTTONS).update_idletasks()


def update_status_label(frame_status: tk.Frame, new_status: str):
    name = f"{FRAME_STATUS}_label"
    frame_status.nametowidget(name).config(text=f"Status: {new_status}", bg=STATUS_COLORS[new_status])
    frame_status.nametowidget(name).update_idletasks()


def change_spinbox_state(frame: tk.Frame, sp_name: str, state: int):
    frame.nametowidget(sp_name if SP_PREFIX in sp_name else SP_PREFIX + sp_name).config(state=state)


def set_buttons_by_devices_status(frame: tk.Frame, devices_dict):
    frame.nametowidget(BUTTON_START).config(state=tk.NORMAL)
    frame.nametowidget(BUTTON_VIEWER).config(state=tk.NORMAL)
    if get_device_status(devices_dict[BLACKBODY_NAME]) == DEVICE_OFF:
        frame.nametowidget(BUTTON_START).config(state=tk.DISABLED)
    if get_device_status(devices_dict[CAMERA_NAME]) == DEVICE_OFF:
        frame.nametowidget(BUTTON_START).config(state=tk.DISABLED)
        frame.nametowidget(BUTTON_VIEWER).config(state=tk.DISABLED)


def update_spinbox_parameters_devices_states(frame: tk.Frame, devices_dict: dict):
    for name, device in devices_dict.items():
        state_device = get_device_status(device)
        device_sp_names = map(lambda x: str(x).split('.')[-1], frame.winfo_children())
        device_sp_names = filter(lambda x: not x.startswith('!') and x.startswith(SP_PREFIX), device_sp_names)
        for sp_name in filter(lambda spinbox_name: name.lower() in spinbox_name.lower(), device_sp_names):
            change_spinbox_state(frame, sp_name, tk.NORMAL if state_device != DEVICE_OFF else tk.DISABLED)


def get_device_status(device):
    if not device:
        return DEVICE_OFF
    if device.is_dummy:
        return DEVICE_DUMMY
    return DEVICE_REAL


def thread_get_fpa_housing_temperatures(devices_dict, frame: tk.Frame, flag):
    def getter():
        for t_type in [T_FPA, T_HOUSING]:
            t = devices_dict[CAMERA_NAME].get_inner_temperature(t_type)
            if t and t != -float('inf'):
                dict_variables[t_type].set(t)
                try:
                    frame.nametowidget(f"{t_type}_label").config(text=f"{t:.2f} C")
                except (TypeError, ValueError):
                    pass

    func_wait_and_get_temperature = wait_for_time(getter, FREQ_INNER_TEMPERATURE_SECONDS * 1e9)
    while flag:
        func_wait_and_get_temperature()


def get_values_list(frame: tk.Frame, devices_dict: dict) -> tuple:
    values_list = []
    for device_name in [BLACKBODY_NAME, SCANNER_NAME, FOCUS_NAME]:  # NOT VERY GOOD - CAN LEAD TO PROBLEMS...
        state_device = get_device_status(devices_dict[device_name])
        # The range is invalid or device is off
        if (inc_value := frame.getvar(device_name + INC_STRING)) == 0 or state_device == DEVICE_OFF:
            values_list.append([OFF])
            continue
        min_value = frame.getvar(device_name + MIN_STRING)
        max_value = frame.getvar(device_name + MAX_STRING)
        list_of_intervals = np.arange(float(min_value), float(max_value) + 1e-9,
                                      float(inc_value))  # 1e-9 to include upper limit
        values_list.append(list_of_intervals)
    return values_list, prod(map(lambda x: len(x), values_list))


class ThreadedSyncFlag:
    def __init__(self, init_state: bool = True) -> None:
        self._event = Event()
        self._event.set() if init_state else self._event.clear()

    def __call__(self) -> bool:
        return self._event.is_set()

    def set(self, new_state: bool):
        self._event.set() if new_state else self._event.clear()

    def __bool__(self) -> bool:
        return self._event.is_set()


def reset_all_fields(root: tk.Tk, buttons_dict: dict, devices_dict: dict) -> None:
    root.nametowidget(FRAME_HEAD).nametowidget(EXPERIMENT_NAME).config(state=tk.NORMAL)
    change_state_radiobuttons(root, state=tk.NORMAL)
    buttons_dict[BUTTON_BROWSE].config(state=tk.NORMAL)
    update_spinbox_parameters_devices_states(root.nametowidget(FRAME_PARAMS), devices_dict)
    buttons_dict[BUTTON_START].config(relief=tk.RAISED, state=tk.NORMAL)
    buttons_dict[BUTTON_STOP].config(state=tk.DISABLED)
    buttons_dict[BUTTON_VIEWER].config(relief=tk.RAISED, state=tk.NORMAL)
    buttons_dict[BUTTON_UPLOAD].config(relief=tk.RAISED, state=tk.NORMAL)
    update_status_label(root.nametowidget(FRAME_STATUS), READY)


def browse_btn_func(f_btn: tk.Frame, f_path: tk.Frame) -> None:
    check_and_make_path(Path(f_btn.getvar(EXPERIMENT_SAVE_PATH)))
    new_path = fd.askdirectory(initialdir=f_btn.getvar(EXPERIMENT_SAVE_PATH))
    if new_path != () and new_path != "":
        f_btn.setvar(EXPERIMENT_SAVE_PATH, new_path)
        msg = f"Experiment folder path: {new_path}"
        f_path.nametowidget(f"{FRAME_PATH}_label").config(text=msg)


def get_inner_temperatures(frame: Frame, type_to_get: str = T_HOUSING) -> float:
    type_to_get = type_to_get.lower()
    if T_HOUSING.lower() in type_to_get:
        return frame.getvar(T_HOUSING)
    elif T_FPA.lower() in type_to_get:
        return frame.getvar(T_FPA)
    if 'max' in type_to_get:
        return max(frame.getvar(T_FPA), frame.getvar(T_HOUSING))
    if 'avg' in type_to_get or 'mean' in type_to_get or 'average' in type_to_get:
        return (frame.getvar(T_FPA) + frame.getvar(T_HOUSING)) / 2.0
    if 'min' in type_to_get:
        return min(frame.getvar(T_FPA), frame.getvar(T_HOUSING))
    raise NotImplementedError(f"{type_to_get} was not implemented for inner temperatures.")


def tqdm_waiting(time_to_wait_seconds: int, postfix: str, flag: (ThreadedSyncFlag, None) = None):
    for _ in tqdm(range(time_to_wait_seconds), total=time_to_wait_seconds, leave=True, postfix=postfix):
        sleep(1)
        if flag is not None and not flag:
            return


dict_variables = {}
