from abc import abstractmethod
from importlib import import_module
from logging import Logger
from pathlib import Path

from serial.serialutil import SerialException, SerialTimeoutException

from utils.constants import CAMERA_NAME, SCANNER_NAME, BLACKBODY_NAME, FOCUS_NAME, DEVICE_DUMMY, CAMERA_TAU, \
    CAMERA_THERMAPP
from utils.logger import make_logging_handlers
import multiprocessing as mp

from utils.tools import SyncFlag
import threading as th


def initialize_device(element_name: str, logger: Logger, handlers: tuple, use_dummies: bool) -> object:
    use_dummies = 'Dummy' if use_dummies else ''
    if SCANNER_NAME.lower() in element_name.lower():
        m = import_module(f"devices.Scanner.{use_dummies}ScannerCtrl", f"Scanner").Scanner
    elif BLACKBODY_NAME.lower() in element_name.lower():
        m = import_module(f"devices.Blackbody.{use_dummies}BlackBodyCtrl", f"BlackBody").BlackBody
    elif FOCUS_NAME.lower() in element_name.lower():
        m = import_module(f"devices.Focus.{use_dummies}FocusStageCtrl", f"FocusStage").FocusStage
    else:
        raise TypeError(f"{element_name} was not implemented as a module.")
    try:
        element = m(logging_handlers=handlers)
        logger.info(f"{use_dummies}{element_name.capitalize()} connected.")
    except RuntimeError:
        element = None
        logger.warning(f"{use_dummies}{element_name.capitalize()} not detected.")
    return element


def make_oven(logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = 20):
    from devices.Oven.PyCampbellCR1000.device import CR1000
    from utils.tools import get_time
    from serial.tools.list_ports import comports
    list_ports = comports()
    list_ports = list(filter(lambda x: 'serial' in x.description.lower() and 'usb' in x.device.lower(), list_ports))
    try:
        oven = CR1000.from_url(f'serial:{list_ports[0].device}:115200',
                               logging_handlers=logging_handlers, logging_level=logging_level)
    except (IndexError, RuntimeError, SerialException, SerialTimeoutException):
        raise RuntimeError
    oven.settime(get_time())
    return oven


def make_oven_dummy(logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = 20):
    from devices.Oven.PyCampbellCR1000.DummyOven import CR1000
    return CR1000(None, logging_handlers=logging_handlers, logging_level=logging_level)


class DeviceAbstract(mp.Process):
    _workers_dict = {}
    _flags_pipes_list = []

    def __init__(self, event_stop: mp.Event,
                 logging_handlers: (tuple, list),
                 values_dict: dict):
        super().__init__()
        self._event_stop = event_stop
        self._flag_run = SyncFlag(init_state=True)
        self._logging_handlers = logging_handlers
        self._values_dict = values_dict

    def run(self):
        self._workers_dict['event_stop'] = th.Thread(target=self._th_stopper, name='event_stop', daemon=False)
        self._workers_dict['event_stop'].start()

        self._workers_dict['cmd_parser'] = th.Thread(target=self._th_cmd_parser, name='cmd_parser', daemon=True)
        self._workers_dict['cmd_parser'].start()

        self._run()

    @abstractmethod
    def _run(self):
        pass

    @abstractmethod
    def _th_cmd_parser(self):
        pass

    def _th_stopper(self):
        self._event_stop.wait()
        self.terminate()

    def _wait_for_threads_to_exit(self):
        for key, t in self._workers_dict.items():
            if t.daemon:
                continue
            try:
                t.join()
            except (RuntimeError, AssertionError, AttributeError):
                pass

    def terminate(self) -> None:
        if hasattr(self, '_flag_run'):
            self._flag_run.set(False)
        for p in self._flags_pipes_list:
            try:
                p.set(False)
            except (RuntimeError, AssertionError, AttributeError, TypeError):
                pass
        self._terminate_device_specifics()
        self._wait_for_threads_to_exit()
        self.kill()

    @abstractmethod
    def _terminate_device_specifics(self):
        pass

    def __del__(self):
        self._event_stop.set()
        self.terminate()
