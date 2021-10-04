from abc import abstractmethod
from importlib import import_module
from logging import Logger

from serial.serialutil import SerialException, SerialTimeoutException

from utils.constants import SCANNER_NAME, FOCUS_NAME
from utils.logger import make_logging_handlers
import multiprocessing as mp

from utils.misc import SyncFlag
import threading as th


def initialize_device(element_name: str, logger: Logger, handlers: tuple, use_dummies: bool) -> object:
    use_dummies = 'Dummy' if use_dummies else ''
    if SCANNER_NAME.lower() in element_name.lower():
        m = import_module(f"devices.Scanner.{use_dummies}ScannerCtrl", f"Scanner").Scanner
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
    from utils.misc import get_time
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

    def __init__(self):
        super().__init__()
        self.daemon = False
        self._flag_run = SyncFlag(init_state=True)
        self._event_terminate = mp.Event()
        self._event_terminate.clear()
        self._workers_dict['terminate'] = th.Thread(daemon=False, name='term', target=self._terminate)

    def run(self):
        self._run()
        [p.start() for p in self._workers_dict.values()]

    def _run(self):
        raise NotImplementedError

    def _wait_for_threads_to_exit(self):
        for key, t in self._workers_dict.items():
            try:
                if t.daemon:
                    continue
                t.join()
            except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
                pass

    def terminate(self):
        try:
            self._event_terminate.set()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
            pass

    def _terminate(self) -> None:
        self._event_terminate.wait()
        try:
            self._flag_run.set(False)
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
            pass
        self._terminate_device_specifics()
        self._wait_for_threads_to_exit()
        try:
            self.kill()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
            pass

    @abstractmethod
    def _terminate_device_specifics(self) -> None:
        raise NotImplementedError
