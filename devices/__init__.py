from importlib import import_module
from logging import Logger

from serial.serialutil import SerialException, SerialTimeoutException

from utils.constants import CAMERA_NAME, SCANNER_NAME, BLACKBODY_NAME, FOCUS_NAME, DEVICE_DUMMY, CAMERA_TAU, \
    CAMERA_THERMAPP
from utils.logger import make_logging_handlers


def initialize_cameras(camera_name: str, logger: Logger, handlers: tuple):
    if camera_name == DEVICE_DUMMY:
        from devices.Camera.Tau.DummyTau2Grabber import TeaxGrabber as m
    elif CAMERA_TAU == camera_name:
        from devices.Camera.Tau.Tau2Grabber import TeaxGrabber as m
    elif CAMERA_THERMAPP == camera_name:
        from devices.Camera.Thermapp.ThermappCtrl import ThermappGrabber as m
    else:
        raise TypeError(f"Camera type {camera_name} was not implemented as a module.")
    try:
        element = m(logging_handlers=handlers)
        log_string = 'Tau2' if CAMERA_TAU == camera_name else 'Thermapp'
        logger.info(f'Camera {log_string} connected.')
    except RuntimeError:
        element = None
    return element

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