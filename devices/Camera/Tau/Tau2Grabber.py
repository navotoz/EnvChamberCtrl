import numpy as np
import binascii
import logging
import multiprocessing as mp
import struct
from pathlib import Path

import serial
import yaml

import devices.Camera.Tau.tau2_config as ptc
from devices.Camera.Tau.FtdiProcess import FtdiIO

from devices.Camera import CameraAbstract
from utils.constants import *
from utils.logger import make_logger, make_logging_handlers, make_device_logging_handler
from utils.tools import SyncFlag, DuplexPipe, make_duplex_pipe
from datetime import datetime
# Tau Status codes
CAM_OK = 0x00
CAM_NOT_READY = 0x02
CAM_RANGE_ERROR = 0x03
CAM_UNDEFINED_ERROR = 0x04
CAM_UNDEFINED_PROCESS_ERROR = 0x05
CAM_UNDEFINED_FUNCTION_ERROR = 0x06
CAM_TIMEOUT_ERROR = 0x07
CAM_BYTE_COUNT_ERROR = 0x09
CAM_FEATURE_NOT_ENABLED = 0x0A
ARGUMENT_FPA = 0x00
ARGUMENT_HOUSING = 0x0A
TIMEOUT_IN_NSEC = 1e9  # 1 seconds
MAGIC_IMAGE_ENDING = 0x0ff0


def _make_packet(command: ptc.Code, argument: (bytes, None) = None) -> bytes:
    if argument is None:
        argument = []

    # Refer to Tau 2 Software IDD
    # Packet Protocol (Table 3.2)
    packet_size = len(argument)
    assert (packet_size == command.cmd_bytes)

    process_code = int(0x6E).to_bytes(1, 'big')
    status = int(0x00).to_bytes(1, 'big')
    function = command.code.to_bytes(1, 'big')

    # First CRC is the first 6 bytes of the packet
    # 1 - Process code
    # 2 - Status code
    # 3 - Reserved
    # 4 - Function
    # 5 - N Bytes MSB
    # 6 - N Bytes LSB

    packet = [process_code,
              status,
              function,
              ((packet_size & 0xFF00) >> 8).to_bytes(1, 'big'),
              (packet_size & 0x00FF).to_bytes(1, 'big')]
    crc_1 = binascii.crc_hqx(struct.pack("ccxccc", *packet), 0)

    packet.append(((crc_1 & 0xFF00) >> 8).to_bytes(1, 'big'))
    packet.append((crc_1 & 0x00FF).to_bytes(1, 'big'))

    if packet_size > 0:

        # Second CRC is the CRC of the data (if any)
        crc_2 = binascii.crc_hqx(argument, 0)
        packet.append(argument)
        packet.append(((crc_2 & 0xFF00) >> 8).to_bytes(1, 'big'))
        packet.append((crc_2 & 0x00FF).to_bytes(1, 'big'))

        fmt = ">cxcccccc{}scc".format(packet_size)

    else:
        fmt = ">cxccccccxxx"

    data = struct.pack(fmt, *packet)
    return data


class Tau(CameraAbstract):
    def __init__(self, port=None, baud=921600, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO, logger: (logging.Logger, None) = None):
        if not logger:
            logging_handlers = make_device_logging_handler('Tau2', logging_handlers)
            logger = make_logger('Tau2', logging_handlers, logging_level)
        super().__init__(logger)
        self._log.info("Connecting to camera.")

        if port:
            self.conn = serial.Serial(port=port, baudrate=baud)

            if self.conn.is_open:
                self._log.info("Connected to camera at {}.".format(port))

                self.conn.flushInput()
                self.conn.flushOutput()
                self.conn.timeout = 1

                self.conn.read(self.conn.in_waiting)
            else:
                self._log.critical("Couldn't connect to camera!")
                raise IOError
        else:
            self.conn = None
        self._width = WIDTH_IMAGE_TAU2
        self._height = HEIGHT_IMAGE_TAU2

    def __del__(self):
        if self.conn:
            self.conn.close()

    def _reset(self):
        self._send_and_recv_threaded(ptc.CAMERA_RESET, None)

    @property
    def type(self) -> int:
        return CAMERA_TAU

    # def ping(self):
    #     function = ptc.NO_OP
    #
    #     self._send_packet(function)
    #     res = self._read_packet(function)
    #
    #     return res
    #
    # def get_serial(self):
    #     function = ptc.SERIAL_NUMBER
    #
    #     self._send_packet(function)
    #     res = self._read_packet(function)
    #
    #     self._log.info("Camera serial: {}".format(int.from_bytes(res[7][:4], byteorder='big', signed=False)))
    #     self._log.info("Sensor serial: {}".format(int.from_bytes(res[7][4:], byteorder='big', signed=False)))
    #
    # def shutter_open(self):
    #     function = ptc.GET_SHUTTER_POSITION
    #     self._send_packet(function, "")
    #     res = self._read_packet(function)
    #
    #     if int.from_bytes(res[7], byteorder='big', signed=False) == 0:
    #         return True
    #     else:
    #         return False
    #
    # def shutter_closed(self):
    #     return not self.shutter_open()
    #
    # def enable_test_pattern(self, mode=1):
    #     function = ptc.SET_TEST_PATTERN
    #     argument = struct.pack(">h", mode)
    #     self._send_packet(function, argument)
    #     sleep(0.2)
    #     res = self._read_packet(function)
    #
    # def disable_test_pattern(self):
    #     function = ptc.SET_TEST_PATTERN
    #     argument = struct.pack(">h", 0x00)
    #     self._send_packet(function, argument)
    #     sleep(0.2)
    #     res = self._read_packet(function)
    #
    # def get_core_status(self):
    #     function = ptc.READ_SENSOR_STATUS
    #     argument = struct.pack(">H", 0x0011)
    #
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #
    #     status = struct.unpack(">H", res[7])[0]
    #
    #     overtemp = status & (1 << 0)
    #     need_ffc = status & (1 << 2)
    #     gain_switch = status & (1 << 3)
    #     nuc_switch = status & (1 << 5)
    #     ffc = status & (1 << 6)
    #
    #     if overtemp != 0:
    #         self._log.critical("Core over temperature warning! Remove power immediately!")
    #
    #     if need_ffc != 0:
    #         self._log.warning("Core desires a new flat field correction (FFC).")
    #
    #     if gain_switch != 0:
    #         self._log.warning("Core suggests that the gain be switched (check for over/underexposure).")
    #
    #     if nuc_switch != 0:
    #         self._log.warning("Core suggests that the NUC be switched.")
    #
    #     if ffc != 0:
    #         self._log.info("FFC is in progress.")
    #
    # def get_acceleration(self):
    #     function = ptc.READ_SENSOR_ACCELEROMETER
    #     argument = struct.pack(">H", 0x000B)
    #
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #
    #     x, y, z = struct.unpack(">HHHxx", res[7])
    #
    #     x *= 0.1
    #     y *= 0.1
    #     z *= 0.1
    #
    #     self._log.info("Acceleration: ({}, {}, {}) g".format(x, y, z))
    #
    #     return x, y, z

    def get_inner_temperature(self, temperature_type: str):
        if T_FPA in temperature_type:
            arg_hex = ARGUMENT_FPA
        elif T_HOUSING in temperature_type:
            arg_hex = ARGUMENT_HOUSING
        else:
            raise TypeError(f'{temperature_type} was not implemented as an inner temperature of TAU2.')
        command = ptc.READ_SENSOR_TEMPERATURE
        argument = struct.pack(">h", arg_hex)
        res = self._send_and_recv_threaded(command, argument, n_retry=1)
        if res:
            res = struct.unpack(">H", res)[0]
            res /= 10.0 if temperature_type == T_FPA else 100.0
            if not 8.0 <= res <= 99.0:  # camera temperature cannot be > 99C or < 8C, returns None.
                self._log.debug(f'Error when recv {temperature_type} - got {res}C')
                return None
        return res

    def _send_and_recv_threaded(self, command: ptc.Code, argument: (bytes, None), n_retry: int = 3):
        pass

    #
    # def close_shutter(self):
    #     function = ptc.SET_SHUTTER_POSITION
    #     argument = struct.pack(">h", 1)
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #     return
    #
    # def open_shutter(self):
    #     function = ptc.SET_SHUTTER_POSITION
    #     argument = struct.pack(">h", 0)
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #     return

    # def _check_header(self, data):
    #
    #     res = struct.unpack(">BBxBBB", data)
    #
    #     if res[0] != 0x6E:
    #         self._log.warning("Initial packet byte incorrect. Byte was: {}".format(res[0]))
    #         return False
    #
    #     if not self.check_status(res[1]):
    #         return False
    #
    #     return True
    #
    # def _read_packet(self, function, post_delay=0.1):
    #     argument_length = function.reply_bytes
    #     data = self._receive_data(10 + argument_length)
    #
    #     self._log.debug("Received: {}".format(data))
    #
    #     if self._check_header(data[:6]) and len(data) > 0:
    #         if argument_length == 0:
    #             res = struct.unpack(">ccxcccccxx", data)
    #         else:
    #             res = struct.unpack(">ccxccccc{}scc".format(argument_length), data)
    #             # check_data_crc(res[7])
    #     else:
    #         res = None
    #         self._log.warning("Error reply from camera. Try re-sending command, or check parameters.")
    #
    #     if post_delay > 0:
    #         sleep(post_delay)
    #
    #     return res
    #
    # def check_status(self, code):
    #
    #     if code == CAM_OK:
    #         self._log.debug("Response OK")
    #         return True
    #     elif code == CAM_BYTE_COUNT_ERROR:
    #         self._log.warning("Byte count error.")
    #     elif code == CAM_FEATURE_NOT_ENABLED:
    #         self._log.warning("Feature not enabled.")
    #     elif code == CAM_NOT_READY:
    #         self._log.warning("Camera not ready.")
    #     elif code == CAM_RANGE_ERROR:
    #         self._log.warning("Camera range error.")
    #     elif code == CAM_TIMEOUT_ERROR:
    #         self._log.warning("Camera timeout error.")
    #     elif code == CAM_UNDEFINED_ERROR:
    #         self._log.warning("Camera returned an undefined error.")
    #     elif code == CAM_UNDEFINED_FUNCTION_ERROR:
    #         self._log.warning("Camera function undefined. Check the function code.")
    #     elif code == CAM_UNDEFINED_PROCESS_ERROR:
    #         self._log.warning("Camera process undefined.")
    #
    #     return False
    #
    # def get_num_snapshots(self):
    #     self._log.debug("Query snapshot status")
    #     function = ptc.GET_MEMORY_ADDRESS
    #     argument = struct.pack('>HH', 0xFFFE, 0x13)
    #
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #     snapshot_size, num_snapshots = struct.unpack(">ii", res[7])
    #
    #     self._log.info("Used snapshot memory: {} Bytes".format(snapshot_size))
    #     self._log.info("Num snapshots: {}".format(num_snapshots))
    #
    #     return num_snapshots, snapshot_size
    #
    # def erase_snapshots(self, frame_id=1):
    #     self._log.info("Erasing snapshots")
    #
    #     num_snapshots, snapshot_used_memory = self.get_num_snapshots()
    #
    #     if num_snapshots == 0:
    #         return
    #
    #     # Get snapshot base address
    #     self._log.debug("Get capture address")
    #     function = ptc.GET_MEMORY_ADDRESS
    #     argument = struct.pack('>HH', 0xFFFF, 0x13)
    #
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #     snapshot_address, snapshot_area_size = struct.unpack(">ii", res[7])
    #
    #     self._log.debug("Snapshot area size: {} Bytes".format(snapshot_area_size))
    #
    #     # Get non-volatile memory base address
    #     function = ptc.GET_NV_MEMORY_SIZE
    #     argument = struct.pack('>H', 0xFFFF)
    #
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #     base_address, block_size = struct.unpack(">ii", res[7])
    #
    #     # Compute the starting block
    #     starting_block = int((snapshot_address - base_address) / block_size)
    #
    #     self._log.debug("Base address: {}".format(base_address))
    #     self._log.debug("Snapshot address: {}".format(snapshot_address))
    #     self._log.debug("Block size: {}".format(block_size))
    #     self._log.debug("Starting block: {}".format(starting_block))
    #
    #     blocks_to_erase = math.ceil((snapshot_used_memory / block_size))
    #
    #     self._log.debug("Number of blocks to erase: {}".format(blocks_to_erase))
    #
    #     for i in range(blocks_to_erase):
    #         function = ptc.ERASE_BLOCK
    #         block_id = starting_block + i
    #
    #         self._log.debug("Erasing block: {}".format(block_id))
    #
    #         argument = struct.pack('>H', block_id)
    #         self._send_packet(function, argument)
    #         res = self._read_packet(function, post_delay=0.2)
    #
    # def snapshot(self, frame_id=0):
    #     self._log.info("Capturing frame")
    #
    #     self.get_core_status()
    #
    #     if self.shutter_closed():
    #         self._log.warning("Shutter reports that it's closed. This frame may be corrupt!")
    #
    #     function = ptc.TRANSFER_FRAME
    #     frame_code = 0x16
    #     argument = struct.pack('>BBH', frame_code, frame_id, 1)
    #
    #     self._send_packet(function, argument)
    #     self._read_packet(function, post_delay=1)
    #
    #     bytes_remaining = self.get_memory_status()
    #     self._log.info("{} bytes remaining to write.".format(bytes_remaining))
    #
    # def retrieve_snapshot(self, frame_id):
    #     # Get snapshot address
    #     self._log.info("Get capture address")
    #     function = ptc.GET_MEMORY_ADDRESS
    #     snapshot_memory = 0x13
    #     argument = struct.pack('>HH', frame_id, snapshot_memory)
    #
    #     self._send_packet(function, argument)
    #     res = self._read_packet(function)
    #     snapshot_address, snapshot_size = struct.unpack(">ii", res[7])
    #
    #     self._log.info("Snapshot size: {}".format(snapshot_size))
    #
    #     n_transfers = math.ceil(snapshot_size / 256)
    #     function = ptc.READ_MEMORY_256
    #
    #     self._log.info("Reading frame {} ({} bytes)".format(frame_id, snapshot_size))
    #     # For N reads, read data
    #     data = []
    #     remaining = snapshot_size
    #     for i in tqdm.tqdm(range(n_transfers)):
    #         n_bytes = min(remaining, 256)
    #         function.reply_bytes = n_bytes
    #
    #         argument = struct.pack('>iH', snapshot_address + i * 256, n_bytes)
    #         self._send_packet(function, argument)
    #         res = self._read_packet(function, post_delay=0)
    #
    #         data += struct.unpack(">{}B".format(int(n_bytes)), res[7])
    #         remaining -= n_bytes
    #
    #     image = np.array(data, dtype='uint8')
    #
    #     return image
    #
    # def get_memory_status(self):
    #     function = ptc.MEMORY_STATUS
    #
    #     self._send_packet(function)
    #     res = self._read_packet(function)
    #
    #     remaining_bytes = struct.unpack(">H", res[7])[0]
    #
    #     if remaining_bytes == 0xFFFF:
    #         self._log.warning("Erase error")
    #     elif remaining_bytes == 0xFFFE:
    #         self._log.warning("Write error")
    #     else:
    #         return remaining_bytes
    #
    # def get_last_image(self):
    #     num_snapshots, _ = self.get_num_snapshots()
    #
    #     if num_snapshots > 0:
    #         return self.retrieve_snapshot(num_snapshots - 1)
    #     else:
    #         return None
    #
    # def _send_data(self, data: bytes) -> None:
    #     n_bytes = self.conn.write(data)
    #     self.conn.flush()
    #     return
    #
    # def _receive_data(self, n_bytes):
    #     return self.conn.read(n_bytes)

    def _get_values_without_arguments(self, command):
        res = self._send_and_recv_threaded(command, None)
        return struct.unpack('>h', res)[0] if res else 0xffff

    def _set_values_with_2bytes_send_recv(self, value: int, current_value: int, command: ptc.Code) -> bool:
        if value == current_value:
            return True
        res = self._send_and_recv_threaded(command, struct.pack('>h', value))
        if res and struct.unpack('>h', res)[0] == value:
            return True
        return False

    def _log_set_values(self, value: int, result: bool, value_name: str) -> None:
        if result:
            self._log.info(f'Set {value_name} to {value}.')
        else:
            self._log.warning(f'Setting {value_name} to {value} failed.')

    def _mode_setter(self, mode: str, current_value: int, setter_code: ptc.Code, code_dict: dict, name: str):
        if isinstance(mode, str):
            if not mode.lower() in code_dict:
                raise NotImplementedError(f"{name} mode {mode} is not implemented.")
            mode = code_dict[mode.lower()]
        elif isinstance(mode, int) and mode not in code_dict.values():
            raise NotImplementedError(f"{name} mode {mode} is not implemented.")
        res = self._set_values_with_2bytes_send_recv(mode, current_value, setter_code)
        self._log_set_values(mode, res, f'{name} mode')

    def set_params_by_dict(self, yaml_or_dict: (Path, dict)):
        pass

    @property
    def is_dummy(self) -> bool:
        return False

    def grab(self) -> np.ndarray:
        pass

    def ffc(self, length: bytes = ptc.FFC_LONG) -> bool:
        res = self._send_and_recv_threaded(ptc.DO_FFC, length)
        if res and struct.unpack('H', res)[0] == 0xffff:
            self._log.debug('FFC')
            return True
        else:
            self._log.debug('FFC Failed')
            return False

    @property
    def correction_mask(self):
        """ the default value is 2111 (decimal). 0 (decimal) is all off """
        return self._get_values_without_arguments(ptc.GET_CORRECTION_MASK)

    @correction_mask.setter
    def correction_mask(self, mode: str):
        self._mode_setter(mode, self.correction_mask, ptc.SET_CORRECTION_MASK, ptc.FCC_MODE_CODE_DICT, 'FCC')

    @property
    def ffc_mode(self):
        return self._get_values_without_arguments(ptc.GET_FFC_MODE)

    @ffc_mode.setter
    def ffc_mode(self, mode: str):
        self._mode_setter(mode, self.ffc_mode, ptc.SET_FFC_MODE, ptc.FCC_MODE_CODE_DICT, 'FCC')

    @property
    def gain(self):
        return self._get_values_without_arguments(ptc.GET_GAIN_MODE)

    @gain.setter
    def gain(self, mode: str):
        self._mode_setter(mode, self.gain, ptc.SET_GAIN_MODE, ptc.GAIN_CODE_DICT, 'Gain')

    @property
    def agc(self):
        return self._get_values_without_arguments(ptc.GET_AGC_ALGORITHM)  # todo: does this function even works????

    @agc.setter
    def agc(self, mode: str):
        self._mode_setter(mode, self.agc, ptc.SET_AGC_ALGORITHM, ptc.AGC_CODE_DICT, 'AGC')

    @property
    def sso(self) -> int:
        res = self._send_and_recv_threaded(ptc.GET_AGC_THRESHOLD, struct.pack('>h', 0x0400))
        return struct.unpack('>h', res)[0] if res else 0xffff

    @sso.setter
    def sso(self, percentage: (int, tuple)):
        if percentage == self.sso:
            self._log.info(f'Set SSO to {percentage}')
            return
        self._send_and_recv_threaded(ptc.SET_AGC_THRESHOLD, struct.pack('>hh', 0x0400, percentage))
        if self.sso == percentage:
            self._log.info(f'Set SSO to {percentage}%')
            return
        self._log.warning(f'Setting SSO to {percentage}% failed.')

    @property
    def contrast(self) -> int:
        return self._get_values_without_arguments(ptc.GET_CONTRAST)

    @contrast.setter
    def contrast(self, value: int):
        self._log_set_values(value, self._set_values_with_2bytes_send_recv(value, self.contrast, ptc.SET_CONTRAST),
                             'AGC contrast')

    @property
    def brightness(self) -> int:
        return self._get_values_without_arguments(ptc.GET_BRIGHTNESS)

    @brightness.setter
    def brightness(self, value: int):
        self._log_set_values(value, self._set_values_with_2bytes_send_recv(value, self.brightness, ptc.SET_BRIGHTNESS),
                             'AGC brightness')

    @property
    def brightness_bias(self) -> int:
        return self._get_values_without_arguments(ptc.GET_BRIGHTNESS_BIAS)

    @brightness_bias.setter
    def brightness_bias(self, value: int):
        result = self._set_values_with_2bytes_send_recv(value, self.brightness_bias, ptc.SET_BRIGHTNESS_BIAS)
        self._log_set_values(value, result, 'AGC brightness_bias')

    @property
    def isotherm(self) -> int:
        return self._get_values_without_arguments(ptc.GET_ISOTHERM)

    @isotherm.setter
    def isotherm(self, value: int):
        result = self._set_values_with_2bytes_send_recv(value, self.isotherm, ptc.SET_ISOTHERM)
        self._log_set_values(value, result, 'IsoTherm')

    @property
    def dde(self) -> int:
        return self._get_values_without_arguments(ptc.GET_SPATIAL_THRESHOLD)

    @dde.setter
    def dde(self, value: int):
        result = self._set_values_with_2bytes_send_recv(value, self.dde, ptc.SET_SPATIAL_THRESHOLD)
        self._log_set_values(value, result, 'DDE')

    @property
    def tlinear(self):
        res = self._send_and_recv_threaded(ptc.GET_TLINEAR_MODE, struct.pack('>h', 0x0040))
        return struct.unpack('>h', res)[0] if res else 0xffff

    @tlinear.setter
    def tlinear(self, value: int):
        if value == self.tlinear:
            return
        self._send_and_recv_threaded(ptc.SET_TLINEAR_MODE, struct.pack('>hh', 0x0040, value))
        if value == self.tlinear:
            self._log_set_values(value, True, 'tlinear mode')
            return
        self._log_set_values(value, False, 'tlinear mode')

    def _digital_output_getter(self, command: ptc.Code, argument: bytes):
        res = self._send_and_recv_threaded(command, argument)
        return struct.unpack('>h', res)[0] if res else 0xffff

    def _digital_output_setter(self, mode: int, current_mode: int, command: ptc.Code, argument: int) -> bool:
        if mode == current_mode:
            return True
        res = self._send_and_recv_threaded(command, struct.pack('>bb', argument, mode))
        if res and struct.unpack('>bb', res)[-1] == mode:
            return True
        return False

    @property
    def lvds(self):
        return self._digital_output_getter(ptc.GET_LVDS_MODE, struct.pack('>h', 0x0400))

    @lvds.setter
    def lvds(self, mode: int):
        res = self._digital_output_setter(mode, self.lvds, ptc.SET_LVDS_MODE, 0x05)
        self._log_set_values(mode, res, 'lvds mode')

    @property
    def lvds_depth(self):
        return self._digital_output_getter(ptc.GET_LVDS_DEPTH, struct.pack('>h', 0x0900))

    @lvds_depth.setter
    def lvds_depth(self, mode: int):
        res = self._digital_output_setter(mode, self.lvds_depth, ptc.SET_LVDS_DEPTH, 0x07)
        self._log_set_values(mode, res, 'lvds depth')

    @property
    def xp(self):
        return self._digital_output_getter(ptc.GET_XP_MODE, struct.pack('>h', 0x0200))

    @xp.setter
    def xp(self, mode: int):
        res = self._digital_output_setter(mode, self.xp, ptc.SET_XP_MODE, 0x03)
        self._log_set_values(mode, res, 'xp mode')

    @property
    def cmos_depth(self):
        return self._digital_output_getter(ptc.GET_CMOS_DEPTH, struct.pack('>h', 0x0800))

    @cmos_depth.setter
    def cmos_depth(self, mode: int):
        res = self._digital_output_setter(mode, self.cmos_depth, ptc.SET_CMOS_DEPTH, 0x06)
        self._log_set_values(mode, res, 'CMOS Depth')

    @property
    def fps(self):
        return self._get_values_without_arguments(ptc.GET_FPS)

    @fps.setter
    def fps(self, mode: str):
        self._mode_setter(mode, self.fps, ptc.SET_FPS, ptc.FPS_CODE_DICT, 'FPS')



class TeaxGrabber(Tau):
    def __init__(self, vid=0x0403, pid=0x6010, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        logging_handlers = make_device_logging_handler('TeaxGrabber', logging_handlers)
        logger = make_logger('TeaxGrabber', logging_handlers, logging_level)
        super().__init__(logger=logger)
        self._n_retry = 3

        self._flag_run = SyncFlag(True)
        self._lock_cmd_send = mp.Lock()
        self._frame_size = 2 * self.height * self.width + 10 + 4 * self.height  # 10 byte header, 4 bytes pad per row
        self._width = self.width
        self._height = self.height

        cmd_pipe_proc, self._cmd_pipe = make_duplex_pipe(self._flag_run)
        image_pipe, self._image_pipe = make_duplex_pipe(self._flag_run)

        try:
            self._io = FtdiIO(vid=vid, pid=pid, cmd_pipe=cmd_pipe_proc, image_pipe=image_pipe,
                              frame_size=self._frame_size, width=self._width, height=self._height,
                              flag_run=self._flag_run, logging_handlers=logging_handlers, logging_level=logging_level)
        except RuntimeError:
            self._log.info('Could not connect to TeaxGrabber.')
            raise RuntimeError
        self._io.daemon = True
        self._io.start()
        # self.ffc()
        self._io.purge()

    def __del__(self) -> None:
        if hasattr(self, '_flag_run'):
            self._flag_run.set(False)
        try:
            self._log.critical('Exit.')
        except:
            pass
        try:
            self._cmd_pipe.send(None)
        except (BrokenPipeError, AttributeError):
            pass
        try:
            self._image_pipe.send(None)
        except (BrokenPipeError, AttributeError):
            pass
        if hasattr(self, '_io') and self._io:
            self._io.join()

    def _send_and_recv_threaded(self, command: ptc.Code, argument: (bytes, None), n_retry: int = 3):
        data, res = _make_packet(command, argument), None
        with self._lock_cmd_send:
            self._cmd_pipe.purge()
            self._cmd_pipe.send((data, command, n_retry if n_retry != self.n_retry else self.n_retry))
            res = self._cmd_pipe.recv()
            return res

    def grab(self, to_temperature: bool = False, n_retries: int = 3) -> (None, np.ndarray):
        # Note that in TeAx's official driver, they use a threaded loop
        # to read data as it streams from the camera and they simply
        # process images/commands as they come back. There isn't the same
        # sort of query/response structure that you'd normally see with
        # a serial device as the camera basically vomits data as soon as
        # the port opens.
        #
        # The current approach here aims to allow a more structured way of
        # interacting with the camera by synchronising with the stream whenever
        # some particular data is requested. However in the future it may be better
        # if this is moved to a threaded function that continually services the
        # serial stream and we have some kind of helper function which responds
        # to commands and waits to see the answer from the camera.
        idx = 0
        while self._flag_run and idx < n_retries:
            self._image_pipe.send(True)
            raw_image_8bit = self._image_pipe.recv()
            if raw_image_8bit is not None:
                raw_image_16bit = 0x3FFF & np.array(raw_image_8bit).view('uint16')[:, 1:-1]

                if to_temperature:
                    raw_image_16bit = 0.04 * raw_image_16bit - 273
                return raw_image_16bit
            idx += 1
        return None

    def set_params_by_dict(self, yaml_or_dict: (Path, dict)):
        if isinstance(yaml_or_dict, Path):
            params = yaml.safe_load(yaml_or_dict)
        else:
            params = yaml_or_dict.copy()
        default_n_retries = self.n_retry
        self.n_retry = 10
        self.ffc_mode = params.get('ffc_mode', 'manual')
        self.isotherm = params.get('isotherm', 0)
        self.dde = params.get('dde', 0)
        self.tlinear = params.get('tlinear', 0)
        self.gain = params.get('gain', 'high')
        self.agc = params.get('agc', 'manual')
        self.sso = params.get('sso', 0)
        self.contrast = params.get('contrast', 0)
        self.brightness = params.get('brightness', 0)
        self.brightness_bias = params.get('brightness_bias', 0)
        self.cmos_depth = params.get('cmos_depth', 0)  # 14bit pre AGC
        self.fps = params.get('fps', 4)  # 60Hz NTSC
        # self.correction_mask = params.get('corr_mask', 0)  # off
        self.n_retry = default_n_retries

    @property
    def n_retry(self) -> int:
        return self._n_retry

    @n_retry.setter
    def n_retry(self, n_retry: int):
        self._n_retry = n_retry
