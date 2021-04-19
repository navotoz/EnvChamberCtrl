import multiprocessing as mp
import threading as th

from devices.Camera import CameraAbstract
from devices.Camera.Tau.DummyTau2Grabber import TeaxGrabber as DummyTeaxGrabber
from devices.Camera.Tau.Tau2Grabber import TeaxGrabber
from devices.Camera.Thermapp.ThermappCtrl import ThermappGrabber
from utils.tools import wait_for_time, DuplexPipe
import utils.constants as const
from devices import DeviceAbstract


class CameraCtrl(DeviceAbstract):
    _workers_dict = dict()
    _camera: (CameraAbstract, None)
    _image = None

    def __init__(self,
                 logging_handlers: (tuple, list),
                 event_stop: mp.Event,
                 image_pipe: DuplexPipe,
                 cmd_pipe: DuplexPipe,
                 values_dict: dict):
        super(CameraCtrl, self).__init__(event_stop, logging_handlers, values_dict)
        self._image_pipe = image_pipe
        self._cmd_pipe = cmd_pipe
        self._flags_pipes_list = [self._image_pipe.flag_run, self._cmd_pipe.flag_run]
        self._camera_type = const.DEVICE_DUMMY
        self._lock_camera = th.Lock()
        self._event_get_temperatures = th.Event()
        self._event_get_temperatures.set()

    def _terminate_device_specifics(self):
        self._event_get_temperatures.set()

    def _run(self):
        self._camera = DummyTeaxGrabber(logging_handlers=self._logging_handlers)
        self._camera_type = const.DEVICE_DUMMY

        self._workers_dict['t_collector'] = th.Thread(target=self._th_get_temperatures, name='t_collector')
        self._workers_dict['t_collector'].start()

        self._workers_dict['img_sender'] = th.Thread(target=self._th_image_sender, name='img_sender')
        self._workers_dict['img_sender'].start()

    def _th_get_temperatures(self) -> None:
        def get() -> None:
            for t_type in [const.T_FPA, const.T_HOUSING]:
                with self._lock_camera:
                    t = self._camera.get_inner_temperature(t_type) if self._camera else None
                if t and t != -float('inf'):
                    try:
                        self._values_dict[t_type] = t
                    except BrokenPipeError:
                        pass

        getter = wait_for_time(get, const.FREQ_INNER_TEMPERATURE_SECONDS)
        while self._flag_run:
            self._event_get_temperatures.wait(timeout=60*10)
            getter()

    def _th_image_sender(self):
        def get() -> None:
            with self._lock_camera:
                return self._camera.grab() if self._camera else None

        getter = wait_for_time(get, const.CAMERA_TAU_HERTZ)  # ~50Hz
        while self._flag_run:
            n_images_to_grab = self._image_pipe.recv()
            if not n_images_to_grab or n_images_to_grab <= 0:
                self._image_pipe.send(None)
            else:
                self._image_pipe.send(True)

            self._event_get_temperatures.clear()
            images = {}
            for n_image in range(1, n_images_to_grab+1):
                t_fpa = round(round(self._values_dict[const.T_FPA] * 100), -1)  # precision for the fpa is 0.1C
                t_housing = round(self._values_dict[const.T_HOUSING] * 100)  # precision of the housing is 0.01C
                images[(t_fpa, t_housing, n_image)] = getter()
            self._event_get_temperatures.set()
            self._image_pipe.send(images)

    def _th_cmd_parser(self):
        while self._flag_run:
            if (cmd := self._cmd_pipe.recv()) is not None:
                cmd, value = cmd
                if cmd == const.CAMERA_NAME:
                    if value is True:
                        self._cmd_pipe.send(self._camera_type)
                        continue
                    with self._lock_camera:
                        if value != self._camera_type:
                            self._camera = None
                            self._camera_type = const.DEVICE_DUMMY
                            try:
                                if value == const.CAMERA_TAU:
                                    self._camera = TeaxGrabber(logging_handlers=self._logging_handlers,
                                                               flag_run=self._flag_run)
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
                    with self._lock_camera:
                        self._camera.set_params_by_dict(value)
                    self._cmd_pipe.send(True)
                elif cmd == const.DIM:
                    if value == const.HEIGHT:
                        self._cmd_pipe.send(self._camera.height)
                    elif value == const.WIDTH:
                        self._cmd_pipe.send(self._camera.width)
                elif cmd == const.FFC:
                    with self._lock_camera:
                        self._camera.ffc()
