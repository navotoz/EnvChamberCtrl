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
from devices.Camera.utils import DuplexPipe
from utils.tools import SyncFlag, wait_for_time
import utils.constants as const


class CameraCtrl(mp.Process):
    _workers_dict = dict()
    _camera: CameraAbstract

    def __init__(self, logging_handlers: (tuple, list),
                 fpa_temperature: mp.Value, housing_temperature: mp.Value,
                 flag_run: SyncFlag,
                 image_pipe: DuplexPipe,
                 camera_type_pipe: DuplexPipe,
                 ):
        super(CameraCtrl, self).__init__()
        self._logging_handlers = logging_handlers
        self._flag_run = flag_run
        self._temperature = {const.T_FPA: fpa_temperature,
                             const.T_HOUSING: housing_temperature}
        self._image_pipe = image_pipe
        self._camera_type_pipe = camera_type_pipe
        self._camera_type = const.DEVICE_DUMMY

    def run(self):
        try:
            self._camera = TeaxGrabber(logging_handlers=self._logging_handlers)
            self._camera_type = const.CAMERA_TAU
        except RuntimeError:
            try:
                self._camera = ThermappGrabber(logging_handlers=self._logging_handlers)
                self._camera_type = const.CAMERA_THERMAPP
            except RuntimeError:
                self._camera = DummyTeaxGrabber(logging_handlers=self._logging_handlers)
                self._camera_type = const.DEVICE_DUMMY

        self._workers_dict['t_collector'] = th.Thread(target=self._th_get_temperatures, name='t_collector')
        self._workers_dict['t_collector'].start()

        self._workers_dict['img_collector'] = th.Thread(target=self._th_images, name='img_collector')
        self._workers_dict['img_collector'].start()

        self._workers_dict['cam_type'] = th.Thread(target=self._th_cam_type, name='cam_type')
        self._workers_dict['cam_type'].start()

        self._wait_for_threads_to_exit()

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
        self._wait_for_threads_to_exit()

    def __del__(self):
        self.terminate()

    def _th_get_temperatures(self) -> None:
        def get() -> None:
            for t_type in [const.T_FPA, const.T_HOUSING]:
                t = self._camera.get_inner_temperature(t_type) if self._camera else None
                if t and t != -float('inf'):
                    self._temperature[t_type].value = t

        getter = wait_for_time(get, const.FREQ_INNER_TEMPERATURE_SECONDS)
        while self._flag_run:
            getter()

    def _th_images(self):
        while self._flag_run:
            self._image_pipe.recv()
            self._image_pipe.send(self._camera.grab() if self._camera else None)

    def _th_cam_type(self):
        while self._flag_run:
            cam_type = self._camera_type_pipe.recv()
            if cam_type is True:
                self._camera_type_pipe.send(self._camera_type)
                continue
            if cam_type != self._camera_type:
                self._camera = None
                self._camera_type = const.DEVICE_DUMMY
                try:
                    if cam_type == const.CAMERA_TAU:
                        self._camera = TeaxGrabber(logging_handlers=self._logging_handlers)
                    elif cam_type == const.CAMERA_THERMAPP:
                        self._camera = ThermappGrabber(logging_handlers=self._logging_handlers)
                    elif cam_type == const.DEVICE_DUMMY:
                        self._camera = DummyTeaxGrabber(logging_handlers=self._logging_handlers)
                    self._camera_type = cam_type
                except RuntimeError:
                    self._camera = DummyTeaxGrabber(self._logging_handlers)
            else:
                self._camera_type = cam_type
            self._camera_type_pipe.send(self._camera_type)
