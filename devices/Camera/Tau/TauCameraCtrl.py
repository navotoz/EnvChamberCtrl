import binascii
import logging
import struct
from pathlib import Path

import numpy as np
import serial
from serial.tools.list_ports import comports

from devices.Camera import CameraAbstract
from devices.Camera.Tau import tau2_config as ptc
from devices.Camera.Tau.tau2_config import ARGUMENT_FPA, ARGUMENT_HOUSING
from utils.constants import WIDTH_IMAGE_TAU2, HEIGHT_IMAGE_TAU2, CAMERA_TAU, T_FPA, T_HOUSING
from utils.logger import make_logging_handlers, make_device_logging_handler, make_logger


class Tau(CameraAbstract):
    conn = None

    def __init__(self, port=None, vid: int = 0x10C4, pid: int = 0xEA60,
                 baud=921600, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO, logger: (logging.Logger, None) = None):
        if not logger:
            logging_handlers = make_device_logging_handler('Tau2', logging_handlers)
            logger = make_logger('Tau2', logging_handlers, logging_level)
        super().__init__(logger)
        self._log.info("Connecting to camera.")
        self._width = WIDTH_IMAGE_TAU2
        self._height = HEIGHT_IMAGE_TAU2

        if not port:
            port = list(filter(lambda x: x.vid == vid and x.pid == pid, comports()))
            port = port[0].device if port else None
        if not port:
            raise IOError('Tau2 with VPC is not connected via a serial connection.')
        self.conn = serial.Serial(port=port, baudrate=baud)

        if self.conn.is_open:
            self._log.info("Connected to camera at {}.".format(port))

            self.conn.flushInput()
            self.conn.flushOutput()
            self.conn.timeout = 1

            self.conn.read(self.conn.in_waiting)
        else:
            self._log.critical("Couldn't connect to camera!")
            raise RuntimeError

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

    def _get_values_without_arguments(self, command: ptc.Code) -> int:
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
        if prev_flag := (self.ffc_mode == ptc.FFC_MODE_CODE_DICT['external']):
            self.ffc_mode = ptc.FFC_MODE_CODE_DICT['manual']
        res = self._send_and_recv_threaded(ptc.DO_FFC, length)
        if prev_flag:
            self.ffc_mode = ptc.FFC_MODE_CODE_DICT['external']
        if res and struct.unpack('H', res)[0] == 0xffff:
            t_fpa = self.get_inner_temperature(T_FPA)
            t_housing = self.get_inner_temperature(T_HOUSING)
            f_log = 'FFC.'
            if t_fpa:
                f_log += f' FPA {t_fpa:.2f}C'
            if t_housing:
                f_log += f', Housing {t_housing:.2f}'
            self._log.info(f_log)
            return True
        else:
            self._log.info('FFC Failed')
            return False

    @property
    def correction_mask(self):
        """ the default value is 2111 (decimal). 0 (decimal) is all off """
        return self._get_values_without_arguments(ptc.GET_CORRECTION_MASK)

    @correction_mask.setter
    def correction_mask(self, mode: str):
        self._mode_setter(mode, self.correction_mask, ptc.SET_CORRECTION_MASK, ptc.FFC_MODE_CODE_DICT, 'FCC')

    @property
    def ffc_mode(self):
        return self._get_values_without_arguments(ptc.GET_FFC_MODE)

    @ffc_mode.setter
    def ffc_mode(self, mode: str):
        self._mode_setter(mode, self.ffc_mode, ptc.SET_FFC_MODE, ptc.FFC_MODE_CODE_DICT, 'FCC')

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

    def reset(self):
        return self._send_and_recv_threaded(ptc.CAMERA_RESET, None)


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