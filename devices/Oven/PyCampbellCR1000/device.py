# -*- coding: utf-8 -*-
'''
    PyCampbellCR1000.client
    -----------------------

    Allows data query of Campbell CR1000-type devices.

    :copyright: Copyright 2012 Salem Harrache and contributors, see AUTHORS.
    :license: GNU GPL v3.

'''
from __future__ import division, unicode_literals
import time
from functools import wraps
from pathlib import Path
from multiprocessing import RLock, Lock

from utils.constants import DATETIME, SETPOINT
from utils.logger import make_logger, make_logging_handlers, make_device_logging_handler

from datetime import datetime, timedelta
from pylink import link_from_url

from .pakbus import PakBus
from .exceptions import NoDeviceException
# noinspection PyUnresolvedReferences
from .compat import xrange, is_py3
# noinspection PyUnresolvedReferences
from .utils import cached_property, ListDict, Dict, nsec_to_time, time_to_nsec, bytes_to_hex, \
    STOP_AND_DELETE_RUNNING_PROGRAM, PAKBUS_MAX_PACKET, COMPILE_NEW_PROGRAM_AND_SET_ON_POWERUP


# _lock_ = RLock()
# def lock(func):
#     @wraps(func)
#     def wrapper(*args, **kw):
#         with _lock_:
#             return func(*args, **kw)
#     return wrapper
#
#
# def decorate_all_functions(function_decorator):
#     def decorator(cls):
#         for name, obj in vars(cls).items():
#             if callable(obj):
#                 setattr(cls, name, function_decorator(obj))
#         return cls
#     return decorator
#
#
# @decorate_all_functions(lock)
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
    _lock_send = Lock()

    def __init__(self, link, dest_addr=None, dest=0x001, src_addr=None,
                 src=0x802, security_code=0x0000,
                 logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = 20):
        link.open()
        self._log = make_logger('Oven', make_device_logging_handler('Oven', logging_handlers), logging_level)
        self.pakbus = PakBus(link, dest_addr, dest, src_addr, src, security_code)
        self.pakbus.wait_packet()
        for _ in range(20):
            try:
                if self.ping_node():
                    self.connected = True
                    break
            except NoDeviceException:
                self.pakbus.link.close()
                self.pakbus.link.open()
        self._log.info('Connected.')
        self.set_value('Public', SETPOINT, 0.0)
        if not self.connected:
            raise NoDeviceException()

    @property
    def log(self):
        return self._log

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
        link = link_from_url(url)
        link.settimeout(timeout)
        return cls(link, dest_addr, dest, src_addr, src, security_code,
                   logging_handlers=logging_handlers, logging_level=logging_level)     #EGC Add security code to the constructor call

    def send_wait(self, cmd):
        '''Send command and wait for response packet.'''
        with self._lock_send:
            packet, transac_id = cmd
            begin = time.time()
            self.pakbus.write(packet)
            # wait response packet
            response = self.pakbus.wait_packet(transac_id)
            end = time.time()
            send_time = timedelta(seconds=int((end - begin) / 2))
            return response[0], response[1], send_time

    def ping_node(self):

        '''Check if remote host is available.'''
        # send hello command and wait for response packet
        hdr, msg, send_time = self.send_wait(self.pakbus.get_hello_cmd())
        if not (hdr and msg):
            raise NoDeviceException()
        return True

    def gettime(self):
        '''Return the current datetime.'''
        self.ping_node()
        self._log.debug('gettime')
        # send clock command and wait for response packet
        hdr, msg, send_time = self.send_wait(self.pakbus.get_clock_cmd())
        # remove transmission time
        return nsec_to_time(msg['Time']) - send_time

    def settime(self, dtime):
        '''Sets the given `dtime` and returns the new current datetime'''
        self._log.debug('settime')
        current_time = self.gettime()
        self.ping_node()
        diff = dtime - current_time
        diff = int(diff.total_seconds())
        # settime (OldTime in response)
        hdr, msg, sdt1 = self.send_wait(self.pakbus.get_clock_cmd((diff, 0)))
        # gettime (NewTime in response)
        hdr, msg, sdt2 = self.send_wait(self.pakbus.get_clock_cmd())
        # remove transmission time

        return nsec_to_time(msg['Time']) - (sdt1 + sdt2)

    @cached_property
    def settings(self):
        '''Get device settings as ListDict'''
        self._log.debug('get settings')
        self.ping_node()
        # send getsettings command and wait for response packet
        hdr, msg, send_time = self.send_wait(self.pakbus.get_getsettings_cmd())
        # remove transmission time
        settings = ListDict()
        for item in msg["Settings"]:
            settings.append(Dict(dict(item)))
        return settings

    def getfile(self, filename):
        '''Get the file content from the dataself._log.'''
        self._log.debug('getfile')
        self.ping_node()
        data = []
        # Send file upload command packets until no more data is returned
        offset = 0x00000000
        transac_id = None
        while True:
            # Upload chunk from file starting at offset
            cmd = self.pakbus.get_fileupload_cmd(filename,
                                                 offset=offset,
                                                 closeflag=0x00,
                                                 transac_id=transac_id)
            transac_id = cmd[1]
            hdr, msg, send_time = self.send_wait(cmd)
            try:
                if msg['RespCode'] == 1:
                    raise ValueError("Permission denied")
                # End loop if no more data is returned
                if not msg['FileData']:
                    break
                # Append file data
                data.append(msg['FileData'])
                offset += len(msg['FileData'])
            except KeyError:
                break
        return b"".join(data)

    def sendfile(self, data, filename):
        '''Upload a file to the dataself._log.'''
        self._log.debug('sendfile')
        raise NotImplementedError('Filedownload transaction is not implemented'
                                  ' yet')

    def list_files(self):
        '''List the files available in the dataself._log.'''
        data = self.getfile('.DIR')
        # List files in directory
        filedir = self.pakbus.parse_filedir(data)
        return [item['FileName'] for item in filedir['files']]

    @cached_property
    def table_def(self):
        '''Return table definition.'''
        while True:
            try:
                data = self.getfile('.TDF')
            except NoDeviceException:
                continue
            # List tables
            tabledef = self.pakbus.parse_tabledef(data)
            return tabledef

    def list_tables(self):
        '''List the tables available in the dataself._log.'''
        return [item['Header']['TableName'] for item in self.table_def]

    def _collect_data(self, tablename, start_date=None, stop_date=None):
        '''Collect fragment data from `tablename` from `start_date` to
        `stop_date` as ListDict.'''
        self._log.debug('Send collect_data cmd')
        if start_date is not None:
            mode = 0x07  # collect from p1 to p2 (nsec)
            p1 = time_to_nsec(start_date)
            p2 = time_to_nsec(stop_date or datetime.now())
        else:
            mode = 0x03  # collect all
            p1 = 0
            p2 = 0

        tabledef = self.table_def
        # Get table number
        tablenbr = None
        if is_py3:
            tablename = bytes(tablename, encoding="utf-8")
        for i, item in enumerate(tabledef):
            if item['Header']['TableName'] == tablename:
                tablenbr = i + 1
                break
        if tablenbr is None:
            # noinspection PyUnresolvedReferences
            raise StandardError('table %s not found' % tablename)
        # Get table definition signature
        tabledefsig = tabledef[tablenbr - 1]['Signature']

        # Send collect data request
        cmd = self.pakbus.get_collectdata_cmd(tablenbr, tabledefsig, mode,
                                              p1, p2)
        hdr, msg, send_time = self.send_wait(cmd)
        more = True
        data, more = self.pakbus.parse_collectdata(msg['RecData'], tabledef)
        # Return parsed record data and flag if more records exist
        return data, more

    def get_data(self, tablename, start_date=None, stop_date=None):
        '''Get all data from `tablename` from `start_date` to `stop_date` as
        ListDict. By default the entire contents of the data will be
        downloaded.

        :param tablename: Table name that contains the data.
        :param start_date: The beginning datetime record.
        :param stop_date: The stopping datetime record.'''
        records = ListDict()
        for items in self.get_data_generator(tablename, start_date, stop_date):
            records.extend(items)
        return records

    def get_data_generator(self, tablename, start_date=None, stop_date=None):
        '''Get all data from `tablename` from `start_date` to `stop_date` as
        generator. The data can be fragmented into multiple packets, this
        generator can return parsed data from each packet before receiving
        the next one.

        :param tablename: Table name that contains the data.
        :param start_date: The beginning datetime record.
        :param stop_date: The stopping datetime record.
        '''
        self.ping_node()
        start_date = start_date or datetime(1990, 1, 1, 0, 0, 1)
        stop_date = stop_date or datetime.now()
        more = True
        while more:
            records = ListDict()
            data, more = self._collect_data(tablename, start_date, stop_date)
            for i, rec in enumerate(data):
                if not rec["NbrOfRecs"]:
                    more = False
                    break
                for j, item in enumerate(rec['RecFrag']):
                    if start_date <= item['TimeOfRec'] <= stop_date:
                        start_date = item['TimeOfRec']
                        # for no duplicate record
                        if more and ((j == (len(rec['RecFrag']) - 1))
                                     and (i == (len(data) - 1))):
                            break
                        new_rec = Dict()
                        new_rec[DATETIME] = item['TimeOfRec']
                        new_rec["RecNbr"] = item['RecNbr']
                        for key in item['Fields']:
                            new_rec["%s" % key] = item['Fields'][key]
                        records.append(new_rec)

            if records:
                records = records.sorted_by(DATETIME)
                yield records.sorted_by(DATETIME)
            else:
                more = False

    def get_raw_packets(self, tablename):
        '''Get all raw packets from table `tablename`.

        :param tablename: Table name that contains the data.
        '''
        self.ping_node()
        more = True
        records = ListDict()
        while more:
            packets, more = self._collect_data(tablename)
            for rec in packets:
                records.append(rec)
        return records

    def getprogstat(self):
        '''Get programming statistics as dict.'''
        self._log.debug('get programming statistics')
        self.ping_node()
        hdr, msg, send_time = self.send_wait(self.pakbus.get_getprogstat_cmd())
        # remove transmission time
        data = Dict(dict(msg['Stats']))
        if data:
            data['CompTime'] = nsec_to_time(data['CompTime'])
        return data

    def bye(self):
        '''Send a bye command.'''
        self._log.debug("Send bye command")
        if self.connected:
            packet, transac_id = self.pakbus.get_bye_cmd()
            self.pakbus.write(packet)
            self.connected = False

    def __del__(self):
        '''Send bye cmd when object is deleted.'''
        self.bye()

    def get_value(self, table_name:str, field_name:str)->float:
        ''' Set variable value in dataself._log '''
        try:
            self.ping_node()
            while True:
                cmd = self.pakbus.get_values_cmd(table_name, field_name)
                self._log.debug(f"get_value cmd: {cmd}")
                hdr, msg, send_time = self.send_wait(cmd)
                if msg['MsgType'] != 0x9a:
                    raise ValueError(f"get_value() MsgType {msg['MsgType']} is different than {0x9a}.")
                value = msg['raw'][3:-1]
                value_float = float(value) if value != '' else -float('inf')
                self._log.debug(f"get_value: {value}, {value_float:.2f}")
                return value_float
        except (NoDeviceException, KeyError):
            raise ValueError('Could not access oven.')

    def set_value(self, table_name: str, field_name: str, value: float)->bool:
        ''' Set variable value in dataself._log '''
        try:
            if self.get_value(table_name, field_name) == value:
                self._log.debug(f'Current value equal given value - {value}.')
                return False
            self.ping_node()
            cmd = self.pakbus.set_values_cmd(table_name, field_name, value)
            self._log.debug(f"set_value: {cmd}")
            hdr, msg, send_time = self.send_wait(cmd)
            response_code = msg['raw'][-1]
        except (NoDeviceException, KeyError) as err:
            msg= f'Could not access oven with error {err}.'
            self._log.debug(msg)
            raise ValueError(msg)
        if msg['MsgType'] != 0x9b:
            msg = f"get_value() MsgType {msg['MsgType']} is different than {0x9b}."
            self._log.error(msg)
            raise ValueError(msg)
        if not response_code == 0x00:
            err = 'Permission denied'
            if response_code == 0x10:
                err = 'Invalid table or field'
            elif response_code == 0x11:
                err = 'Data type conversion not supported'
            elif response_code == 0x12:
                err = 'Memory bounds violation'
            msg = f'set_value() returned error {response_code} meaning {err}.'
            self._log.error(msg)
            raise ValueError(msg)
        self._log.debug(f'Set temperature to {value}C.')
        return True

    def send_new_program(self, filename:Path):
        if not filename.is_file():
            raise FileNotFoundError(f"{filename} was not found.")
        try:
            self.ping_node()
        except NoDeviceException:
            raise ValueError

        # stop the running program
        while True:
            try:
                # noinspection PyUnresolvedReferences
                cmd = self.pakbus.get_filecontrol_cmd(STOP_AND_DELETE_RUNNING_PROGRAM)
                self._log.debug(f"get_filecontrol_cmd: {cmd}")
                hdr, msg, send_time = self.send_wait(cmd)
                ... # parse response
                break
            except (NoDeviceException, KeyError):
                ...

        # send new program
        with open(filename, 'r') as fp:
            program =fp.read().encode()
        chunked_bytes = {i: program[i:i + PAKBUS_MAX_PACKET] for i in range(0, len(program), PAKBUS_MAX_PACKET)}
        for offset, pckt in chunked_bytes.items():
            # noinspection PyUnresolvedReferences
            if last:
                # noinspection PyUnresolvedReferences
                cmd = self.pakbus.get_filedownload_cmd(offset, pckt, is_last)
            else:
                # noinspection PyUnresolvedReferences
                cmd = self.pakbus.get_filedownload_cmd(offset, pckt, is_last)
            while True:
                try:
                    # noinspection PyUnresolvedReferences
                    send()
                    break
                except:
                    # noinspection PyUnresolvedReferences
                    fucked

        # complie new program
        while True:
            try:
                # noinspection PyUnresolvedReferences
                cmd = self.pakbus.get_filecontrol_cmd(COMPILE_NEW_PROGRAM_AND_SET_ON_POWERUP)
                self._log.debug(f"get_filecontrol_cmd: {cmd}")
                hdr, msg, send_time = self.send_wait(cmd)
                ... # parse response
                break
            except (NoDeviceException, KeyError):
                ...

        # check compile status
        while True:
            try:
                cmd = self.pakbus.get_getprogstat_cmd()
                self._log.debug(f"get_programstats: {cmd}")
                hdr, msg, send_time = self.send_wait(cmd)
                ... # parse response
                break
            except (NoDeviceException, KeyError):
                ...

        self._log.info('Set new program.')

    @property
    def is_dummy(self):
        return False
