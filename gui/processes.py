import logging
from pathlib import Path
import multiprocessing as mp
import threading as th
from time import sleep

import utils.constants as const
from devices.Camera.CameraProcess import CameraCtrl
from devices.Oven.OvenProcess import OvenCtrl
from utils.logger import make_logging_handlers, make_logger
from utils.tools import SyncFlag, make_duplex_pipe

log_path = Path('log')
handlers = make_logging_handlers(logfile_path=log_path / 'log.txt', verbose=True)
logger = make_logger('GUI', handlers=handlers, level=logging.INFO)
event_stop = mp.Event()  # This event signals all process in the program to stop
event_stop.clear()
semaphore_plot_proc = mp.Semaphore(0)
semaphore_mask_sync = th.Semaphore(0)
flag_run = SyncFlag(init_state=True)
_mp_manager = mp.Manager()
mp_values_dict = _mp_manager.dict({const.T_FPA: 0.0,
                                   const.T_HOUSING: 0.0
                                   })

_oven_temperature_proc, oven_temperature = make_duplex_pipe(flag_run=None)
_oven_cmd_proc, oven_cmd = make_duplex_pipe(flag_run=None)
_cam_cmd_proc, camera_cmd = make_duplex_pipe(flag_run=None)
_image_grabber_proc, image_grabber = make_duplex_pipe(flag_run=None)

oven = OvenCtrl(logging_handlers=handlers,
                event_stop=event_stop,
                log_path=log_path,
                temperature_pipe=_oven_temperature_proc,
                cmd_pipe=_oven_cmd_proc,
                values_dict=mp_values_dict)
oven.start()

camera = CameraCtrl(logging_handlers=handlers,
                    image_pipe=_image_grabber_proc,
                    event_stop=event_stop,
                    values_dict=mp_values_dict,
                    log_path=log_path,
                    cmd_pipe=_cam_cmd_proc)
camera.start()
