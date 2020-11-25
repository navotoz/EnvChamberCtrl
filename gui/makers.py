import tkinter as tk
from collections import namedtuple
from ctypes import c_int64, c_double
from functools import partial
from logging import Logger
from multiprocessing import Value, RLock
from pathlib import Path
from tkinter import ttk
from typing import Tuple, Dict, Any

from devices import initialize_device
from gui.utils import spinbox_validation, dict_variables, update_spinbox_parameters_devices_states, \
    validate_spinbox_range, get_device_status, set_buttons_by_devices_status
from utils.constants import *
from utils.logger import GuiMsgHandler


class SafeIntVar(tk.IntVar):
    def __init__(self, *kwargs):
        super().__init__(*kwargs)
        self._mp_value = Value(c_int64, lock=RLock())

    @property
    def value(self):
        return self._mp_value

    def set(self, value):
        """Set the variable to VALUE."""
        self._mp_value.value = int(value)
        return self._tk.globalsetvar(self._name, value)

    def get(self):
        value = self._tk.globalgetvar(self._name)
        try:
            value = self._tk.getint(value)
        except (TypeError, tk.TclError):
            value = self._tk.getdouble(value)
        value = int(value)
        self._mp_value.value = value
        return value


class SafeDoubleVar(tk.DoubleVar):
    def __init__(self, *kwargs):
        super().__init__( *kwargs)
        self._mp_value = Value(c_double, lock=RLock())

    @property
    def value(self):
        return self._mp_value

    def set(self, value):
        """Set the variable to VALUE."""
        self._mp_value.value = float(value)
        return self._tk.globalsetvar(self._name, value)

    def get(self):
        value = float(self._tk.getdouble(self._tk.globalgetvar(self._name)))
        self._mp_value.value = float(value)
        return value


def make_spinbox(frame: tk.Frame, row: int, col: int, name: str,
                 from_: (int, float), to: (int, float), res: (int, float)) -> None:
    sp_name = SP_PREFIX + name
    if isinstance(res, int):
        var = SafeIntVar
    else:
        var = SafeDoubleVar
    var = var(frame, from_, name)
    spinbox = tk.Spinbox(frame, from_=from_, to=to, bd=1, width=7, wrap=1, increment=res, name=sp_name)
    spinbox.config(textvariable=var)
    spinbox.grid(row=row, column=col)
    spinbox.bind("<FocusOut>", lambda event: validate_spinbox_range(var, event.widget['from'], event.widget['to']))
    spinbox.config(command=spinbox_validation)
    dict_variables[name] = var


def make_spinboxes_with_range(frame: tk.Frame, row: int, col: int, name: str) -> None:
    for suffix in [MIN_STRING, MAX_STRING, INC_STRING]:
        make_label(frame, row, col, text=suffix + ": ", pad_y=10)
        from_ = LIMIT_DICT[name][MIN_STRING] if suffix != INC_STRING else 0
        to = LIMIT_DICT[name][MAX_STRING]
        res = LIMIT_DICT[name][RESOLUTION_STRING]
        make_spinbox(frame, row, col + 1, name=name + suffix, from_=from_, to=to, res=res)
        col += 2


def make_label(frame: tk.Frame, row: int, col: int, text: str = "", pad_y: int = 0, pad_x: int = 0,
               name: (str, None) = None) -> tk.Label:
    label = tk.Label(frame, text=text, pady=pad_y, padx=pad_x, name=name)
    label.grid(row=row, column=col)
    return label


def make_range_params(frame: tk.Frame, init_row: int, func_device_maker, devices_dict):
    row = init_row
    for row, name in enumerate([OVEN_NAME, BLACKBODY_NAME, SCANNER_NAME, FOCUS_NAME], start=row):
        make_label(frame, row=row, col=0, text=f"{name.capitalize()} [{METRICS_DICT[name]}]:", pad_y=10)
        make_spinboxes_with_range(frame, row=row, col=1, name=name)
        make_devices_status_radiobox(frame, row=row, col=9, name=name, cmd=func_device_maker, devices_dict=devices_dict)
    row += 1
    make_label(frame, row=row, col=0, text="# images per configuration", pad_y=10)
    make_spinbox(frame, row=row, col=1, name=CAMERA_NAME + INC_STRING, from_=LIMIT_DICT[CAMERA_NAME][MIN_STRING],
                 to=LIMIT_DICT[CAMERA_NAME][MAX_STRING], res=LIMIT_DICT[CAMERA_NAME][RESOLUTION_STRING])
    make_devices_status_radiobox(frame, row=row, col=2, name=CAMERA_NAME, cmd=func_device_maker, devices_dict=devices_dict)

    # set some initial values
    for key in dict_variables.keys():
        name = key.split(' ')
        if name[0] in LIMIT_DICT:
            gen = filter(lambda x: x in [INIT_MAX, INIT_MIN, INIT_INC], LIMIT_DICT[name[0]].keys())
            gen = filter(lambda x: name[-1] in x, gen)
            for init in gen:
                dict_variables[key].set(value=LIMIT_DICT[name[0]][init])


def make_frame(parent: tk.Tk, row: int, bd: int = 0, name: str = "") -> tk.Frame:
    frame = tk.Frame(parent, bd=bd, name=name)
    frame.grid(row=row, column=0)
    return frame


def make_devices_status_radiobox(frame: tk.Frame, row: int, col: int, name: str, cmd, devices_dict: dict):
    def run_func(frame_func: tk.Frame, next_device_status: tk.IntVar, name_func: str, func, devices_dict: dict):
        next_device_status = next_device_status.get()
        curr_device_status = get_device_status(devices_dict[name_func])
        if curr_device_status != next_device_status:
            devices_dict[name_func] = func(name=name_func, frame=frame_func, status=next_device_status)
        if 'camera' in name_func.lower():
            if get_device_status(devices_dict[name_func]) == DEVICE_OFF and next_device_status != DEVICE_OFF:
                devices_dict[name_func] = func(name=name_func, frame=frame_func, status=DEVICE_DUMMY)
        try:
            set_buttons_by_devices_status(frame_func.master.nametowidget(FRAME_BUTTONS), devices_dict)
        except KeyError:
            pass

    var_dev_stat = tk.IntVar(value=DEVICE_REAL, name=f'device_status_{name}')
    make = partial(tk.Radiobutton, master=frame, variable=var_dev_stat, width=5, indicatoron=True)
    run = partial(run_func, frame_func=frame, func=cmd, next_device_status=var_dev_stat, devices_dict=devices_dict)
    off_button = None
    if 'camera' not in name:
        off_button = make(text="Off", name=f'off_{name}', value=DEVICE_OFF)
        off_button.grid(row=row, column=col)
        off_button.config(command=partial(run, name_func=name))
    dummy_button = make(text="Dummy", name=f'dummy_{name}', value=DEVICE_DUMMY)
    dummy_button.grid(row=row, column=col + 1)
    dummy_button.config(command=partial(run, name_func=name))
    real_button = make(text="Real", name=f'real_{name}', value=DEVICE_REAL)
    real_button.grid(row=row, column=col + 2)
    real_button.config(command=partial(run, name_func=name))
    if 'oven' in name and off_button:
        off_button.invoke()
    else:
        real_button.invoke()


def make_button(frame: tk.Frame, col: int, text: str, name: str, command, state=tk.NORMAL) -> tk.Button:
    txt = ''.join([t.capitalize() for t in text.split('_')[1:]])
    button = tk.Button(frame, height=2, width=len(text), bd=2, text=txt, command=command, state=state, name=name)
    button.grid(row=0, column=col)
    return button


def make_buttons(frame: tk.Frame, func_dict: dict) -> dict:
    buttons_dict = dict.fromkeys(func_dict.keys())
    make = partial(make_button, frame=frame)
    for col, button_name in enumerate(buttons_dict.keys()):
        buttons_dict[button_name] = make(col=col, name=button_name, text=button_name, command=func_dict[button_name])
    buttons_dict[BUTTON_START].config(bg='green')
    buttons_dict[BUTTON_STOP].config(state=tk.DISABLED)
    return buttons_dict


def make_terminal(frame: tk.Frame, logger: Logger):
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    terminal = tk.Text(frame, bg="black", fg="white", height=13, width=115, yscrollcommand=scrollbar.set)
    terminal.pack_propagate(0)
    terminal.pack(side=tk.LEFT, fill=tk.X)
    terminal.config(state=tk.DISABLED)
    scrollbar.config(command=terminal.yview)
    logger.addHandler(GuiMsgHandler(terminal, logger=logger))


def make_devices(logger, handlers, use_dummy: bool):
    init_devices = partial(initialize_device, logger=logger, handlers=handlers)
    dict_devices = {}
    for name in [CAMERA_NAME, BLACKBODY_NAME, SCANNER_NAME, FOCUS_NAME]:
        dict_devices[name] = init_devices(name, use_dummies=use_dummy)
    return dict_devices


def make_device_and_handle_parameters(name: str, frame: tk.Frame, logger, handlers, status: int):
    if name in OVEN_NAME:
        device = namedtuple('mockup_oven', field_names=['is_dummy'])(status == DEVICE_DUMMY)
    elif status != DEVICE_OFF:
        device = initialize_device(name, logger, handlers, status == DEVICE_DUMMY)
    else:
        device = None
        logger.info(f"{name.capitalize()} is off.")
    frame.setvar(f'device_status_{name}', get_device_status(device))
    update_spinbox_parameters_devices_states(frame, {name: device})
    return device


def make_frames(logger, handler, devices_dict) -> Tuple[tk.Tk, Dict[Any, tk.Frame]]:
    root = tk.Tk()
    root.title("Environmental Chamber Experiment GUI")
    root.attributes('-zoomed', False)
    root.resizable(height=0, width=0)
    root.option_add("*Font", "TkDefaultFont 18")

    frame_head = make_frame(parent=root, row=0, bd=5, name=FRAME_HEAD)
    frame_temperatures = make_frame(parent=root, row=1, bd=5, name=FRAME_TEMPERATURES)
    frame_params = make_frame(parent=root, row=2, bd=5, name=FRAME_PARAMS)
    frame_buttons = make_frame(parent=root, row=3, bd=5, name=FRAME_BUTTONS)
    frame_path = make_frame(parent=root, row=4, bd=5, name=FRAME_PATH)
    frame_status = make_frame(parent=root, row=5, bd=5, name=FRAME_STATUS)
    frame_progressbar = make_frame(parent=root, row=6, name=FRAME_PROGRESSBAR)
    frame_terminal = make_frame(parent=root, row=7, name=FRAME_TERMINAL)
    make_terminal(frame_terminal, logger)

    func_device_maker = partial(make_device_and_handle_parameters, logger=logger, handlers=handler)

    make_label(frame=frame_head, row=0, col=0, text="Experiment name: ", pad_y=10)
    dict_variables[EXPERIMENT_NAME] = tk.StringVar(frame_head, value='', name=EXPERIMENT_NAME)
    experiment_name = tk.Entry(frame_head, name=EXPERIMENT_NAME, textvariable=dict_variables[EXPERIMENT_NAME])
    experiment_name.grid(row=0, column=1, padx=10)
    make_label(frame=frame_head, row=0, col=2, text="Use camera inner Temperatures")
    dict_variables[USE_CAM_INNER_TEMPS] = tk.StringVar(frame_temperatures, USE_CAM_INNER_TEMPS_INIT_VAL, USE_CAM_INNER_TEMPS)
    rb = tk.Checkbutton(frame_head, variable=dict_variables[USE_CAM_INNER_TEMPS])
    rb.grid(row=0, column=3)
    make_label(frame=frame_head, row=1, col=0, text="Max Temperature Delta [Deg]:", pad_y=10)
    make_spinbox(frame_head, 1, 1, DELTA_TEMPERATURE, from_=0.01, to=10, res=0.01)
    dict_variables[DELTA_TEMPERATURE].set(DELTA_TEMPERATURE_INIT_VAL)
    make_label(frame=frame_head, row=1, col=2, text='Minimal Settling Time [Minutes]:')
    make_spinbox(frame_head, 1, 3, SETTLING_TIME_MINUTES, from_=1, to=120, res=1)
    dict_variables[SETTLING_TIME_MINUTES].set(SETTLING_TIME_MINUTES_INIT_VAL)

    make_label(frame_temperatures, row=0, col=0, text="Housing [C]:")
    make_label(frame_temperatures, row=0, col=1, text='', name=f"{T_HOUSING}_label", pad_x=30)
    make_label(frame_temperatures, row=0, col=2, text="FPA [C]:", pad_x=10)
    make_label(frame_temperatures, row=0, col=3, text='', name=f"{T_FPA}_label", pad_x=30)
    make_label(frame_temperatures, row=0, col=4, text='Iterations in each oven temperature:')
    make_spinbox(frame_temperatures, row=0, col=5, name=ITERATIONS_IN_TEMPERATURE, from_=1, to=20, res=1)
    dict_variables[ITERATIONS_IN_TEMPERATURE].set(ITERATIONS_IN_TEMPERATURE_INIT_VAL)

    dict_variables[T_FPA] = SafeDoubleVar(frame_temperatures, 0.0, T_FPA)
    dict_variables[T_HOUSING] = SafeDoubleVar(frame_temperatures, 0.0, T_HOUSING)

    make_range_params(frame_params, 1, func_device_maker, devices_dict)
    dict_variables[EXPERIMENT_SAVE_PATH] = tk.StringVar(master=frame_buttons, name=EXPERIMENT_SAVE_PATH,
                                                        value=Path.cwd().parent / 'experiments')
    make_label(frame_path, 0, 1, f"Experiment folder path: {dict_variables[EXPERIMENT_SAVE_PATH].get()}",
               name=f"{FRAME_PATH}_label")

    make_label(frame_status, 0, 1, name=f"{FRAME_STATUS}_label")

    progress_bar = ttk.Progressbar(frame_progressbar, mode='determinate', orient=tk.HORIZONTAL,
                                   length=root.winfo_width(), maximum=100, name=PROGRESSBAR)
    progress_bar.pack(fill=tk.X)
    return root, {FRAME_HEAD: frame_head, FRAME_PARAMS: frame_params, FRAME_TEMPERATURES: frame_temperatures,
                  FRAME_BUTTONS: frame_buttons, FRAME_PATH: frame_path, FRAME_STATUS: frame_status,
                  FRAME_PROGRESSBAR: frame_progressbar, FRAME_TERMINAL: frame_terminal}

