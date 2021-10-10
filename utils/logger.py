import logging
from pathlib import Path


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
        return logging_handlers + (handler_debug, handler_info,)
    return logging_handlers


def make_fmt():
    return logging.Formatter("%(asctime)s %(name)s:%(levelname)s:%(message)s", datefmt='%Y-%m-%d %H:%M:%S')


def make_logging_handlers(logfile_path: (None, Path) = None, verbose: bool = False, use_fmt: bool = True) -> tuple:
    fmt = make_fmt()
    handlers_list = []
    logfile_path = Path(logfile_path) if logfile_path else None
    if verbose:
        handlers_list.append(logging.StreamHandler())
        handlers_list[0].name = 'stdout'
    if logfile_path and not logfile_path.parent.is_dir():
        logfile_path.parent.mkdir(parents=True)
    try:
        handlers_list.append(logging.FileHandler(str(logfile_path), mode='w')) if logfile_path else None
    except:
        pass
    for handler in handlers_list:
        handler.setFormatter(fmt) if use_fmt else None
    return tuple(handlers_list)


def make_logger(name: str, handlers: (list, tuple), level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    for idx in range(len(handlers)):
        if handlers[idx].name == 'stdout':
            handlers[idx].setLevel(level)
        else:
            handlers[idx].setLevel(logging.DEBUG)
    for handler in handlers:
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


class ExceptionsLogger:
    def __init__(self):
        self._logger = logging.getLogger('ExceptionsLogger')
        path = Path('log') / 'critical.txt'
        if not path.parent.is_dir():
            path.parent.mkdir(parents=True)
        self._logger.addHandler(logging.FileHandler(path, mode='w'))
        self._logger.addHandler(logging.StreamHandler())

    def flush(self):
        pass

    def write(self, message):
        if message != '\n':
            self._logger.critical(message.split('\n')[0])
