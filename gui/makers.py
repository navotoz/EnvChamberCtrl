import tkinter as tk
from functools import partial
from logging import Logger
from pathlib import Path
from tkinter import ttk
from typing import Tuple, Dict, Any

from devices import initialize_device
from gui.tools import spinbox_validation, dict_variables, update_spinbox_parameters_devices_states, \
    validate_spinbox_range, get_device_status, set_buttons_by_devices_status
from utils.constants import *
from utils.logger import GuiMsgHandler
from utils.tools import DuplexPipe


class SaveVar(tk.IntVar):
    _pipe: (DuplexPipe, None) = None
    _var_type = None

    def __init__(self, *kwargs):
        super().__init__(*kwargs)

    def set(self, value):
        """Set the variable to VALUE."""
        value = self._var_type(value)
        if self._pipe is not None:
            self._pipe.send((self._name, self._var_type(value)))
            assert value == self._pipe.recv(), f'Could not set {self._name} for oven.'
        return self._tk.globalsetvar(self._name, value)

    @property
    def pipe(self):
        return self._pipe

    @pipe.setter
    def pipe(self, pipe: (DuplexPipe, None)):
        self._pipe = pipe


class SafeIntVar(SaveVar):
    def __init__(self, *kwargs) -> None:
        super(SafeIntVar, self).__init__(*kwargs)
        self._var_type = int

    def get(self):
        value = self._tk.globalgetvar(self._name)
        try:
            value = self._tk.getint(value)
        except (TypeError, tk.TclError):
            value = self._tk.getdouble(value)
        value = int(value)
        return value


class SafeDoubleVar(SaveVar):
    def __init__(self, *kwargs) -> None:
        super(SafeDoubleVar, self).__init__(*kwargs)
        self._var_type = float

    def get(self):
        value = float(self._tk.getdouble(self._tk.globalgetvar(self._name)))
        return value


def make_spinbox(frame: tk.Frame, row: int, col: int, name: str,
                 from_: (int, float), to: (int, float), res: (int, float)) -> None:
    sp_name = SP_PREFIX + name
    if name in [SETTLING_TIME_MINUTES, DELTA_TEMPERATURE]:
        if isinstance(res, int):
            var = SafeIntVar
        else:
            var = SafeDoubleVar
    else:
        if isinstance(res, int):
            var = tk.IntVar
        else:
            var = tk.DoubleVar
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


def make_range_params(frame: tk.Frame, init_row: int, func_device_maker, devices_dict) -> int:
    row = init_row
    for row, name in enumerate([OVEN_NAME, BLACKBODY_NAME, SCANNER_NAME, FOCUS_NAME], start=row):
        make_label(frame, row=row, col=0, text=f"{name.capitalize()} [{METRICS_DICT[name]}]:", pad_y=10)
        make_spinboxes_with_range(frame, row=row, col=1, name=name)
        make_devices_status_radiobox(frame, row=row, col=9, name=name, cmd=func_device_maker, devices_dict=devices_dict)
    row += 1

    # set some initial values
    for key in dict_variables.keys():
        name = key.split(' ')
        if name[0] in LIMIT_DICT:
            gen = filter(lambda x: x in [INIT_MAX, INIT_MIN, INIT_INC], LIMIT_DICT[name[0]].keys())
            gen = filter(lambda x: name[-1] in x, gen)
            for init in gen:
                dict_variables[key].set(value=LIMIT_DICT[name[0]][init])

    return row


def make_frame(parent: tk.Tk, row: int, bd: int = 0, name: str = "") -> tk.Frame:
    frame = tk.Frame(parent, bd=bd, name=name)
    frame.grid(row=row, column=0)
    return frame


def make_devices_status_radiobox(frame: tk.Frame, row: int, col: int, name: str, cmd, devices_dict: dict):
    def run_func(frame_func: tk.Frame, next_device_status: tk.IntVar, name_func: str, func, devices_dict: dict):
        next_device_status = next_device_status.get()
        curr_device_status = get_device_status(name_func, devices_dict[name_func])
        if curr_device_status != next_device_status:
            if OVEN_NAME in name:
                if devices_dict[name_func]:
                    devices_dict[name_func].send((OVEN_NAME, next_device_status))
                    next_device_status = devices_dict[name_func].recv()
            devices_dict[name_func] = func(name=name_func, frame=frame_func, status=next_device_status)
        try:
            set_buttons_by_devices_status(frame_func.master.nametowidget(FRAME_BUTTONS), devices_dict)
        except KeyError:
            pass

    var_dev_stat = tk.IntVar(value=DEVICE_REAL, name=f'device_status_{name}')
    make = partial(tk.Radiobutton, master=frame, variable=var_dev_stat, width=5, indicatoron=True)
    run = partial(run_func, frame_func=frame, func=cmd, next_device_status=var_dev_stat, devices_dict=devices_dict)
    dummy_button = make(text="Dummy", name=f'dummy_{name}', value=DEVICE_DUMMY)
    dummy_button.grid(row=row, column=col + 1)
    dummy_button.config(command=partial(run, name_func=name))
    real_button = make(text="Real", name=f'real_{name}', value=DEVICE_REAL)
    real_button.grid(row=row, column=col + 2)
    real_button.config(command=partial(run, name_func=name))
    if OVEN_NAME not in name:
        off_button = make(text="Off", name=f'off_{name}', value=DEVICE_OFF)
        off_button.grid(row=row, column=col)
        off_button.config(command=partial(run, name_func=name))
        off_button.invoke()
    else:
        dummy_button.invoke()


def make_camera_status_radiobox(frame: tk.Frame, row: int, devices_dict: dict):
    def button_maker(name: str, value: (int, str), col_: int):
        b = tk.Radiobutton(text=name.capitalize(), name=f'camera_{name}', value=value,
                           master=frame, variable=var_cam_stat, width=5, indicatoron=True)
        b.grid(row=row, column=col_)
        run = partial(run_func, next_device_status=var_cam_stat, devices_dict=devices_dict)
        b.config(command=run)
        return b

    def run_func(next_device_status: tk.IntVar, devices_dict: dict):
        camera_to_set = next_device_status.get()
        devices_dict[CAMERA_NAME].send((CAMERA_NAME, camera_to_set))
        next_device_status.set(devices_dict[CAMERA_NAME].recv())

    make_label(frame, row=row, col=0, text="# images per configuration", pad_y=10)
    make_spinbox(frame, row=row, col=1, name=CAMERA_NAME + INC_STRING, from_=LIMIT_DICT[CAMERA_NAME][MIN_STRING],
                 to=LIMIT_DICT[CAMERA_NAME][MAX_STRING], res=LIMIT_DICT[CAMERA_NAME][RESOLUTION_STRING])
    var_cam_stat = tk.IntVar(value=DEVICE_DUMMY, name=f'camera_status')
    dict_variables[CAMERA_NAME + INC_STRING].set(LIMIT_DICT[CAMERA_NAME][INIT_INC])
    dummy_button = button_maker('dummy', DEVICE_DUMMY, 2)
    tau_button = button_maker('tau2', CAMERA_TAU, 3)
    thermapp_button = button_maker('thermapp', CAMERA_THERMAPP, 4)
    # tau_button.invoke()
    # if var_cam_stat.get() == DEVICE_DUMMY:
    #     thermapp_button.invoke()
    # if not devices_dict[CAMERA_NAME]:
    # dummy_button.invoke()


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


def make_device_and_handle_parameters(name: str, frame: tk.Frame, logger, handlers, status: int, devices_dict):
    if name in OVEN_NAME:
        device = devices_dict[OVEN_NAME]
    elif status != DEVICE_OFF:
        device = initialize_device(name, logger, handlers, status == DEVICE_DUMMY)
    else:
        device = None
        logger.info(f"{name.capitalize()} is off.")
    frame.setvar(f'device_status_{name}', get_device_status(name, device))
    update_spinbox_parameters_devices_states(frame, {name: device})
    return device


def make_frames(logger, handler, devices_dict) -> Tuple[tk.Tk, Dict[Any, tk.Frame], str]:
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

    make_label(frame=frame_head, row=0, col=0, text="Experiment name: ", pad_y=10)
    dict_variables[EXPERIMENT_NAME] = tk.StringVar(frame_head, value='', name=EXPERIMENT_NAME)
    experiment_name = tk.Entry(frame_head, name=EXPERIMENT_NAME, textvariable=dict_variables[EXPERIMENT_NAME])
    experiment_name.grid(row=0, column=1, padx=10)
    make_label(frame=frame_head, row=0, col=2, text="Use camera inner Temperatures")
    dict_variables[USE_CAM_INNER_TEMPS] = tk.StringVar(frame_temperatures, USE_CAM_INNER_TEMPS_INIT_VAL,
                                                       USE_CAM_INNER_TEMPS)
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

    func_device_maker = partial(make_device_and_handle_parameters, logger=logger, handlers=handler, devices_dict=devices_dict)
    row_for_camera = make_range_params(frame_params, 1, func_device_maker, devices_dict)
    make_camera_status_radiobox(frame_params, row_for_camera, devices_dict)
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
                  FRAME_PROGRESSBAR: frame_progressbar, FRAME_TERMINAL: frame_terminal},\
           dict_variables[EXPERIMENT_SAVE_PATH].get()
