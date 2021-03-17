import multiprocessing as mp
from asyncio import sleep
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Dict
import threading as th

from devices.Camera import CameraAbstract
from devices.Camera.Tau.DummyTau2Grabber import TeaxGrabber as DummyTeaxGrabber
from devices.Camera.Tau.Tau2Grabber import TeaxGrabber
from devices.Camera.Thermapp.ThermappCtrl import ThermappGrabber
from utils.tools import SyncFlag, wait_for_time, DuplexPipe
import utils.constants as const
from devices import DeviceAbstract


class CameraCtrl(DeviceAbstract):
    def _terminate_device_specifics(self):
        pass

    _workers_dict = dict()
    _camera: (CameraAbstract, None)

    def __init__(self,
                 logging_handlers: (tuple, list),
                 event_stop: mp.Event,
                 image_pipe: DuplexPipe,
                 cmd_pipe: DuplexPipe,
                 log_path: Path,
                 values_dict: dict):
        super(CameraCtrl, self).__init__(event_stop, logging_handlers, values_dict, log_path)
        self._image_pipe = image_pipe
        self._cmd_pipe = cmd_pipe
        self._flags_pipes_list = [self._image_pipe.flag_run, self._cmd_pipe.flag_run]
        self._camera_type = const.DEVICE_DUMMY

    def _run(self):
        self._camera = DummyTeaxGrabber(logging_handlers=self._logging_handlers)
        self._camera_type = const.DEVICE_DUMMY

        self._workers_dict['t_collector'] = th.Thread(target=self._th_get_temperatures, name='t_collector')
        self._workers_dict['t_collector'].start()

        self._workers_dict['img_collector'] = th.Thread(target=self._th_images, name='img_collector')
        self._workers_dict['img_collector'].start()

        self._wait_for_threads_to_exit()

    def _th_get_temperatures(self) -> None:
        def get() -> None:
            for t_type in [const.T_FPA, const.T_HOUSING]:
                t = self._camera.get_inner_temperature(t_type) if self._camera else None
                if t and t != -float('inf'):
                    try:
                        self._values_dict[t_type] = t
                    except BrokenPipeError:
                        pass

        getter = wait_for_time(get, const.FREQ_INNER_TEMPERATURE_SECONDS)
        while self._flag_run:
            getter()

    def _th_images(self):
        while self._flag_run:
            self._image_pipe.recv()
            self._image_pipe.send(self._camera.grab() if self._camera else None)

    def _th_cmd_parser(self):
        while self._flag_run:
            if (cmd := self._cmd_pipe.recv()) is not None:
                cmd, value = cmd
                if cmd == const.CAMERA_NAME:
                    if value is True:
                        self._cmd_pipe.send(self._camera_type)
                        continue
                    if value != self._camera_type:
                        self._camera = None
                        self._camera_type = const.DEVICE_DUMMY
                        try:
                            if value == const.CAMERA_TAU:
                                self._camera = TeaxGrabber(logging_handlers=self._logging_handlers)
                            elif value == const.CAMERA_THERMAPP:
                                self._camera = ThermappGrabber(logging_handlers=self._logging_handlers)
                            elif value == const.DEVICE_DUMMY:
                                self._camera = DummyTeaxGrabber(logging_handlers=self._logging_handlers)
                            self._camera_type = value
                        except RuntimeError:
                            self._camera = DummyTeaxGrabber(self._logging_handlers)
                    else:
                        self._camera_type = value
                    self._cmd_pipe.send(self._camera_type)
                elif cmd == const.CAMERA_PARAMETERS:
                    self._camera.set_params_by_dict(value)
                    self._cmd_pipe.send(True)
                elif cmd == const.DIM:
                    if value == const.HEIGHT:
                        self._cmd_pipe.send(self._camera.height)
                    elif value == const.WIDTH:
                        self._cmd_pipe.send(self._camera.width)
