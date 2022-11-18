from datetime import datetime

from ..constants import OVEN_TABLE_NAME
from utils.logger import make_logger, make_logging_handlers


class CR1000(object):
    '''Communicates with the dataself._log by sending commands, reads the binary
    data and parses it into usable scalar values.

    :param link: A `PyLink` connection.
    :param dest_addr: Destination physical address (12-bit int) (default dest)
    :param dest: Destination node ID (12-bit int) (default 0x001)
    :param src_addr: Source physical address (12-bit int) (default src)
    :param src: Source node ID (12-bit int) (default 0x802)
    :param security_code: 16-bit security code (default 0x0000)
    '''
    connected = False
    _temperature = float(25)
    def __init__(self, link, dest_addr=None, dest=0x001, src_addr=None,
                 src=0x802, security_code=0x0000,
                 logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = 20):
        self._log = make_logger('DummyOven', logging_handlers, logging_level)
        self._log.info('Connected.')

    @classmethod
    def from_url(cls, url, timeout=10, dest_addr=None, dest=0x001,
                 src_addr=None, src=0x802, security_code=0x0000,
                 logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = 20):
        ''' Get device from url.

        :param url: A `PyLink` connection URL.
        :param timeout: Set a read timeout value.
        :param dest_addr: Destination physical address (12-bit int) (default dest)
        :param dest: Destination node ID (12-bit int) (default 0x001)
        :param src_addr: Source physical address (12-bit int) (default src)
        :param src: Source node ID (12-bit int) (default 0x802)
        :param security_code: 16-bit security code (default 0x0000)
        '''
        return cls(None, dest_addr, dest, src_addr, src, security_code,
                   logging_handlers=logging_handlers, logging_level=logging_level)     #EGC Add security code to the constructor call

    def send_wait(self, cmd):
        pass

    def ping_node(self):
        pass

    def gettime(self):
        return datetime.now().replace(microsecond=0)

    def settime(self, dtime):
        pass

    def getprogstat(self):
        pass

    def bye(self):
        pass

    def get_value(self, table_name:str, field_name:str):
        return self._temperature

    def set_value(self, table_name: str, field_name: str, value: float):
        self._temperature = value
        return self._temperature

    @property
    def log(self):
        return self._log

    @property
    def is_dummy(self):
        return True

    @property
    def table_def(self):
        return dict(Header=dict(TableName=OVEN_TABLE_NAME))
