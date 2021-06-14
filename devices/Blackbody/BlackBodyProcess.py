from numbers import Number
import multiprocessing as mp
import threading as th
from pathlib import Path
from time import sleep

import utils.constants as const
from devices import DeviceAbstract
from utils.logger import make_logging_handlers, make_logger, make_device_logging_handler
from utils.tools import wait_for_time, DuplexPipe
from devices.Blackbody.BlackBodyCtrl import BlackBody
from devices.Blackbody.DummyBlackBodyCtrl import BlackBody as DummyBlackBody


class BlackBodyProc(DeviceAbstract):
    def _terminate_device_specifics(self):
        pass

    _workers_dict = dict()
    _blackbody: (BlackBody, DummyBlackBody, None)

    def __init__(self,
                 logging_handlers: (tuple, list),
                 event_stop: mp.Event,
                 temperature_pipe: DuplexPipe,
                 cmd_pipe: DuplexPipe):
        super(BlackBodyProc, self).__init__(event_stop, logging_handlers, None)
        self._logging_handlers = make_device_logging_handler(f'{const.BLACKBODY_NAME}', logging_handlers)
        t_h = filter(lambda x: 'file' in str(type(x)).lower(), self._logging_handlers)
        t_h = Path(list(filter(lambda x: const.BLACKBODY_NAME in x.baseFilename, t_h))[-1].baseFilename).parent
        t_h /= 'temperatures.txt'
        self._log_temperature = make_logger(f'{const.BLACKBODY_NAME}Temperatures', make_logging_handlers(t_h, False))
        self._temperature_pipe = temperature_pipe
        self._cmd_pipe = cmd_pipe
        self._flags_pipes_list = [self._temperature_pipe.flag_run, self._cmd_pipe.flag_run]
        self._blackbody_type = const.DEVICE_DUMMY

        self._temperature = 0.0
        self._lock_access = th.Lock()

    def _run(self):
        self._blackbody = DummyBlackBody(logging_handlers=self._logging_handlers)
        self._blackbody_type = const.DEVICE_DUMMY

        self._workers_dict['t_collector'] = th.Thread(target=self._th_t_collector, name='t_collector')
        self._workers_dict['t_collector'].start()

        self._workers_dict['check_dummy'] = th.Thread(target=self._th_check_dummy, name='check_dummy')
        self._workers_dict['check_dummy'].start()

    def _th_check_dummy(self):
        def get():
            with self._lock_access:  # lock should be inside function, to prevent idle locked waiting
                # try to change to real blackbody
                if self._blackbody_type == const.DEVICE_DUMMY:
                    try:
                        blackbody = BlackBody(logging_handlers=self._logging_handlers)
                        self._blackbody_type = const.DEVICE_REAL
                        self._blackbody = blackbody
                    except (RuntimeError, BrokenPipeError):
                        pass

                # make sure the blackbody is still connected
                elif self._blackbody_type == const.DEVICE_REAL:
                    try:
                        self._blackbody.echo()
                    except (RuntimeError, BrokenPipeError):
                        if self._blackbody_type == const.DEVICE_REAL:  # echo fail, change from real to dummy
                            self._blackbody = DummyBlackBody(logging_handlers=self._logging_handlers)
                            self._blackbody_type = const.DEVICE_DUMMY

        getter = wait_for_time(get, 1)
        while self._flag_run:
            getter()

    def _th_t_collector(self) -> None:
        def get() -> None:
            with self._lock_access:
                t = self._blackbody.temperature if self._blackbody else None
            if t and t != -float('inf'):
                try:
                    with self._lock_access:
                        self._temperature = t
                        self._log_temperature.info(t)
                except BrokenPipeError:
                    pass

        getter = wait_for_time(get, 1)
        while self._flag_run:
            getter()

    def _th_cmd_parser(self):
        while self._flag_run:
            if (cmd := self._cmd_pipe.recv()) is not None:
                cmd, value = cmd
                if cmd == const.BLACKBODY_NAME:
                    with self._lock_access:
                        if value is True:
                            self._cmd_pipe.send(self._blackbody_type)
                        elif value != self._blackbody_type:
                            self._blackbody = None
                            self._blackbody_type = const.DEVICE_DUMMY
                            try:
                                if value == const.DEVICE_REAL:
                                    self._blackbody = BlackBody(logging_handlers=self._logging_handlers)
                                elif value == const.DEVICE_DUMMY:
                                    self._blackbody = DummyBlackBody(logging_handlers=self._logging_handlers)
                                self._blackbody_type = value
                            except RuntimeError:
                                self._blackbody = DummyBlackBody(logging_handlers=self._logging_handlers)
                        else:
                            self._blackbody_type = value
                    self._cmd_pipe.send(self._blackbody_type)
                elif cmd == const.T_BLACKBODY:
                    with self._lock_access:
                        if isinstance(value, Number) and not isinstance(value, bool):
                            self._blackbody.temperature = value
                            self._temperature = self._blackbody.temperature
                        self._cmd_pipe.send(self._temperature)
                else:
                    self._cmd_pipe.send(None)
