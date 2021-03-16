import logging
from pathlib import Path
from tkinter import END, DISABLED, NORMAL, Text

from utils.tools import check_and_make_path


def make_device_logging_handler(name, logging_handlers):
    handler = [handler for handler in logging_handlers if isinstance(handler, logging.FileHandler)]
    if handler:
        path = Path(handler[0].baseFilename).parent
        path = path / 'log' if 'log' not in path.name.lower() else path
        path /= name.lower()
        if not path.is_dir():
            path.mkdir(parents=True)
        path_to_debug = path / 'debug.txt'
        path_to_info = path / 'info.txt'
        fmt = handler[0].formatter
        handler_debug = logging.FileHandler(str(path_to_debug), mode='w')
        handler_debug.setLevel(logging.DEBUG)
        handler_debug.setFormatter(fmt)
        handler_info = logging.FileHandler(str(path_to_info), mode='w')
        handler_info.setLevel(logging.INFO)
        handler_info.setFormatter(fmt)
        return logging_handlers + (handler_debug, handler_info, )
    return logging_handlers


def make_logging_handlers(logfile_path: (None, Path) = None, verbose: bool = False) -> tuple:
    fmt = logging.Formatter("%(asctime)s %(name)s:%(levelname)s:%(message)s", datefmt='%Y-%m-%d %H:%M:%S')
    handlers_list = []
    handlers_list.append(logging.StreamHandler()) if verbose else None
    if logfile_path:
        logfile_path = Path(logfile_path)
        logfile_path.parent.mkdir(parents=True) if not logfile_path.parent.is_dir() else None
        check_and_make_path(logfile_path.parent)
    handlers_list.append(logging.FileHandler(str(logfile_path), mode='w')) if logfile_path else None
    for handler in handlers_list:
        handler.setFormatter(fmt)
    return tuple(handlers_list)


def make_logger(name: str, handlers: (list, tuple), level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    for idx in range(len(handlers)):
        if not isinstance(handlers[idx], logging.FileHandler):
            handlers[idx].setLevel(level)
        # else:
        #     handlers[idx].setLevel(logging.DEBUG)
    for handler in handlers:
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


class GuiMsgHandler(logging.StreamHandler):
    def __init__(self, text_box: Text, logger:logging.Logger) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)10s | %(message)s", datefmt='%Y-%m-%d %H:%M:%S'))
        self.text_box: Text = text_box
        handlers_list = [x for x in logger.handlers if not isinstance(x, logging.FileHandler)]
        if handlers_list:
            self.setLevel(handlers_list[0].level)

    def emit(self, record):
        self.text_box.config(state=NORMAL)
        self.text_box.insert(END, self.format(record) + self.terminator)
        self.text_box.see(END)
        self.text_box.config(state=DISABLED)
        self.text_box.update_idletasks()


class ExceptionsLogger:
    def __init__(self):
        self._logger = logging.getLogger('ExceptionsLogger')
        self._logger.addHandler(logging.FileHandler('log_critical.txt', mode='w'))
        self._logger.addHandler(logging.StreamHandler())

    def flush(self):
        pass

    def write(self, message):
        if message != '\n':
            self._logger.critical(message)