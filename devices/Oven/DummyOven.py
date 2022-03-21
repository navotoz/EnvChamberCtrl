import utils.constants as const


class DummyOven:
    def __init__(self, *args):
        super(DummyOven, self).__init__()
        pass

    @property
    def setpoint(self):
        return 25

    @setpoint.setter
    def setpoint(self, value: float):
        pass

    def set_camera_temperatures(self, fpa: float, housing: float):
        pass

    @property
    def is_connected(self):
        return True

    def temperature(self, name: str) -> int:
        return 5000

    def terminate(self):
        pass

    def join(self):
        pass