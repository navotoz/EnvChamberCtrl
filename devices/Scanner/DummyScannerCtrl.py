# noinspection PyUnusedLocal
class Scanner:
    def __init__(self, *args, **kwrgs):
        super().__init__()

    def __repr__(self):
        return "DummyScanner"

    def move(self, *args, **kwargs) -> bool:
        return True

    def __set_zero_position(self):
        pass

    def __set_limits(self):
        pass

    def __call__(self, *args, **kwargs):
        return True
