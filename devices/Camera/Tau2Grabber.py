import binascii
import logging
import math
import struct
from time import sleep

import numpy as np
import serial
import tqdm
import usb.core
import usb.util
from pyftdi.ftdi import Ftdi

import devices.Camera.tau2_config as ptc
from devices.Camera.ThreadedFtdi import FtdiIO
from utils.constants import *
from utils.logger import make_logger, make_logging_handlers, make_device_logging_handler

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


class Tau:
    def __init__(self, port=None, baud=921600, logging_handlers: tuple = make_logging_handlers(None, True),
                 logging_level: int = logging.INFO):
        super().__init__()
        logging_handlers = make_device_logging_handler('Tau2', logging_handlers)
        self._log = make_logger('Tau2', logging_handlers, logging_level)
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

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self.conn:
            self.conn.close()
        self._log.info("Disconnecting from camera.")

    def ping(self):
        function = ptc.NO_OP

        self._send_packet(function)
        res = self._read_packet(function)

        return res

    def get_serial(self):
        function = ptc.SERIAL_NUMBER

        self._send_packet(function)
        res = self._read_packet(function)

        self._log.info("Camera serial: {}".format(int.from_bytes(res[7][:4], byteorder='big', signed=False)))
        self._log.info("Sensor serial: {}".format(int.from_bytes(res[7][4:], byteorder='big', signed=False)))

    def shutter_open(self):
        function = ptc.GET_SHUTTER_POSITION
        self._send_packet(function, "")
        res = self._read_packet(function)

        if int.from_bytes(res[7], byteorder='big', signed=False) == 0:
            return True
        else:
            return False

    def shutter_closed(self):
        return not self.shutter_open()

    def enable_test_pattern(self, mode=1):
        function = ptc.SET_TEST_PATTERN
        argument = struct.pack(">h", mode)
        self._send_packet(function, argument)
        sleep(0.2)
        res = self._read_packet(function)

    def disable_test_pattern(self):
        function = ptc.SET_TEST_PATTERN
        argument = struct.pack(">h", 0x00)
        self._send_packet(function, argument)
        sleep(0.2)
        res = self._read_packet(function)

    def get_core_status(self):
        function = ptc.READ_SENSOR_STATUS
        argument = struct.pack(">H", 0x0011)

        self._send_packet(function, argument)
        res = self._read_packet(function)

        status = struct.unpack(">H", res[7])[0]

        overtemp = status & (1 << 0)
        need_ffc = status & (1 << 2)
        gain_switch = status & (1 << 3)
        nuc_switch = status & (1 << 5)
        ffc = status & (1 << 6)

        if overtemp != 0:
            self._log.critical("Core overtemperature warning! Remove power immediately!")

        if need_ffc != 0:
            self._log.warning("Core desires a new flat field correction (FFC).")

        if gain_switch != 0:
            self._log.warning("Core suggests that the gain be switched (check for over/underexposure).")

        if nuc_switch != 0:
            self._log.warning("Core suggests that the NUC be switched.")

        if ffc != 0:
            self._log.info("FFC is in progress.")

    def get_acceleration(self):
        function = ptc.READ_SENSOR_ACCELEROMETER
        argument = struct.pack(">H", 0x000B)

        self._send_packet(function, argument)
        res = self._read_packet(function)

        x, y, z = struct.unpack(">HHHxx", res[7])

        x *= 0.1
        y *= 0.1
        z *= 0.1

        self._log.info("Acceleration: ({}, {}, {}) g".format(x, y, z))

        return x, y, z

    def get_inner_temperature(self, temperature_type: str):
        if T_FPA in temperature_type:
            arg_hex = ARGUMENT_FPA
        elif T_HOUSING in temperature_type:
            arg_hex = ARGUMENT_HOUSING
        else:
            raise TypeError(f'{temperature_type} was not implemented as an inner temperature of TAU2.')
        command = ptc.READ_SENSOR_TEMPERATURE
        argument = struct.pack(">h", arg_hex)
        res = self._send_and_recv_threaded(command, argument)
        if res:
            res = struct.unpack(">H", res)[0]
            res /= 10.0 if arg_hex == ARGUMENT_FPA else 100.0
            if not 8.0 <= res <= 99.0:  # camera temperature cannot be > 99C or < 8C, returns None.
                return None
        return res

    def _send_and_recv_threaded(self, data, command):
        pass

    def close_shutter(self):
        function = ptc.SET_SHUTTER_POSITION
        argument = struct.pack(">h", 1)
        self._send_packet(function, argument)
        res = self._read_packet(function)
        return

    def open_shutter(self):
        function = ptc.SET_SHUTTER_POSITION
        argument = struct.pack(">h", 0)
        self._send_packet(function, argument)
        res = self._read_packet(function)
        return

    def digital_output_enabled(self):
        function = ptc.GET_DIGITAL_OUTPUT_MODE

        self._send_packet(function, "")
        res = self._read_packet(function)

        if int.from_bytes(res[7], byteorder='big', signed=False) == 0:
            return True
        else:
            return False

    def enable_digital_output(self):
        """
        Enables both LVDS and XP interfaces. Call this, then set the XP mode.
        """
        function = ptc.SET_DIGITAL_OUTPUT_MODE

        argument = struct.pack(">h", 0x0000)
        self._send_packet(function, argument)
        res = self._read_packet(function)

        if int.from_bytes(res[7], byteorder='big', signed=False) == 0:
            return True
        else:
            return False

    def disable_digital_output(self):
        function = ptc.SET_DIGITAL_OUTPUT_MODE
        argument = struct.pack(">h", 0x0002)

        self._send_packet(function, argument)
        res = self._read_packet(function)

        if int.from_bytes(res[7], byteorder='big', signed=False) == 2:
            return True
        else:
            return False

    def get_xp_mode(self):
        function = ptc.GET_DIGITAL_OUTPUT_MODE
        argument = struct.pack(">h", 0x0200)

        self._send_packet(function, argument)
        res = self._read_packet(function)

        mode = int.from_bytes(res[7], byteorder='big', signed=False)
        return mode

    def set_xp_mode(self, mode=0x02):
        function = ptc.SET_DIGITAL_OUTPUT_MODE
        argument = struct.pack(">h", 0x0300 & mode)

        self._send_packet(function, argument)
        res = self._read_packet(function)

        if int.from_bytes(res[7], byteorder='big', signed=False) == 0x0300 & mode:
            return True
        else:
            return False

    def get_lvds_mode(self):
        pass

    def set_lvds_mode(self):
        pass

    def set_cmos_mode(self, fourteen_bit=True):

        function = ptc.SET_DIGITAL_OUTPUT_MODE

        if fourteen_bit:
            mode = 0x00
        else:
            mode = 0x01

        argument = struct.pack(">h", 0x0600 & mode)

        self._send_packet(function, argument)
        res = self._read_packet(function)

        if int.from_bytes(res[7], byteorder='big', signed=False) == 0x0600 & mode:
            return True
        else:
            return False

    def enable_tlinear(self):
        pass

    def _make_packet(self, command: ptc.Code, argument: (bytes, None) = None) -> bytes:
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

    def _check_header(self, data):

        res = struct.unpack(">BBxBBB", data)

        if res[0] != 0x6E:
            self._log.warning("Initial packet byte incorrect. Byte was: {}".format(res[0]))
            return False

        if not self.check_status(res[1]):
            return False

        return True

    def _read_packet(self, function, post_delay=0.1):
        argument_length = function.reply_bytes
        data = self._receive_data(10 + argument_length)

        self._log.debug("Received: {}".format(data))

        if self._check_header(data[:6]) and len(data) > 0:
            if argument_length == 0:
                res = struct.unpack(">ccxcccccxx", data)
            else:
                res = struct.unpack(">ccxccccc{}scc".format(argument_length), data)
                # check_data_crc(res[7])
        else:
            res = None
            self._log.warning("Error reply from camera. Try re-sending command, or check parameters.")

        if post_delay > 0:
            sleep(post_delay)

        return res

    def check_status(self, code):

        if code == CAM_OK:
            self._log.debug("Response OK")
            return True
        elif code == CAM_BYTE_COUNT_ERROR:
            self._log.warning("Byte count error.")
        elif code == CAM_FEATURE_NOT_ENABLED:
            self._log.warning("Feature not enabled.")
        elif code == CAM_NOT_READY:
            self._log.warning("Camera not ready.")
        elif code == CAM_RANGE_ERROR:
            self._log.warning("Camera range error.")
        elif code == CAM_TIMEOUT_ERROR:
            self._log.warning("Camera timeout error.")
        elif code == CAM_UNDEFINED_ERROR:
            self._log.warning("Camera returned an undefined error.")
        elif code == CAM_UNDEFINED_FUNCTION_ERROR:
            self._log.warning("Camera function undefined. Check the function code.")
        elif code == CAM_UNDEFINED_PROCESS_ERROR:
            self._log.warning("Camera process undefined.")

        return False

    def get_num_snapshots(self):
        self._log.debug("Query snapshot status")
        function = ptc.GET_MEMORY_ADDRESS
        argument = struct.pack('>HH', 0xFFFE, 0x13)

        self._send_packet(function, argument)
        res = self._read_packet(function)
        snapshot_size, num_snapshots = struct.unpack(">ii", res[7])

        self._log.info("Used snapshot memory: {} Bytes".format(snapshot_size))
        self._log.info("Num snapshots: {}".format(num_snapshots))

        return num_snapshots, snapshot_size

    def erase_snapshots(self, frame_id=1):
        self._log.info("Erasing snapshots")

        num_snapshots, snapshot_used_memory = self.get_num_snapshots()

        if num_snapshots == 0:
            return

        # Get snapshot base address
        self._log.debug("Get capture address")
        function = ptc.GET_MEMORY_ADDRESS
        argument = struct.pack('>HH', 0xFFFF, 0x13)

        self._send_packet(function, argument)
        res = self._read_packet(function)
        snapshot_address, snapshot_area_size = struct.unpack(">ii", res[7])

        self._log.debug("Snapshot area size: {} Bytes".format(snapshot_area_size))

        # Get non-volatile memory base address
        function = ptc.GET_NV_MEMORY_SIZE
        argument = struct.pack('>H', 0xFFFF)

        self._send_packet(function, argument)
        res = self._read_packet(function)
        base_address, block_size = struct.unpack(">ii", res[7])

        # Compute the starting block
        starting_block = int((snapshot_address - base_address) / block_size)

        self._log.debug("Base address: {}".format(base_address))
        self._log.debug("Snapshot address: {}".format(snapshot_address))
        self._log.debug("Block size: {}".format(block_size))
        self._log.debug("Starting block: {}".format(starting_block))

        blocks_to_erase = math.ceil((snapshot_used_memory / block_size))

        self._log.debug("Number of blocks to erase: {}".format(blocks_to_erase))

        for i in range(blocks_to_erase):
            function = ptc.ERASE_BLOCK
            block_id = starting_block + i

            self._log.debug("Erasing block: {}".format(block_id))

            argument = struct.pack('>H', block_id)
            self._send_packet(function, argument)
            res = self._read_packet(function, post_delay=0.2)

    def snapshot(self, frame_id=0):
        self._log.info("Capturing frame")

        self.get_core_status()

        if self.shutter_closed():
            self._log.warning("Shutter reports that it's closed. This frame may be corrupt!")

        function = ptc.TRANSFER_FRAME
        frame_code = 0x16
        argument = struct.pack('>BBH', frame_code, frame_id, 1)

        self._send_packet(function, argument)
        self._read_packet(function, post_delay=1)

        bytes_remaining = self.get_memory_status()
        self._log.info("{} bytes remaining to write.".format(bytes_remaining))

    def retrieve_snapshot(self, frame_id):
        # Get snapshot address
        self._log.info("Get capture address")
        function = ptc.GET_MEMORY_ADDRESS
        snapshot_memory = 0x13
        argument = struct.pack('>HH', frame_id, snapshot_memory)

        self._send_packet(function, argument)
        res = self._read_packet(function)
        snapshot_address, snapshot_size = struct.unpack(">ii", res[7])

        self._log.info("Snapshot size: {}".format(snapshot_size))

        n_transfers = math.ceil(snapshot_size / 256)
        function = ptc.READ_MEMORY_256

        self._log.info("Reading frame {} ({} bytes)".format(frame_id, snapshot_size))
        # For N reads, read data
        data = []
        remaining = snapshot_size
        for i in tqdm.tqdm(range(n_transfers)):
            n_bytes = min(remaining, 256)
            function.reply_bytes = n_bytes

            argument = struct.pack('>iH', snapshot_address + i * 256, n_bytes)
            self._send_packet(function, argument)
            res = self._read_packet(function, post_delay=0)

            data += struct.unpack(">{}B".format(int(n_bytes)), res[7])
            remaining -= n_bytes

        image = np.array(data, dtype='uint8')

        return image

    def get_memory_status(self):
        function = ptc.MEMORY_STATUS

        self._send_packet(function)
        res = self._read_packet(function)

        remaining_bytes = struct.unpack(">H", res[7])[0]

        if remaining_bytes == 0xFFFF:
            self._log.warning("Erase error")
        elif remaining_bytes == 0xFFFE:
            self._log.warning("Write error")
        else:
            return remaining_bytes

    def ffc_mode_select(self, mode: str = 'ext') -> bool:
        command = ptc.SET_FFC_MODE
        if 'auto' in mode.lower():
            argument = struct.pack('>H', 0)
        elif 'man' in mode.lower():
            argument = struct.pack('>H', 1)
        elif 'ext' in mode.lower():
            argument = struct.pack('>H', 2)
        else:
            raise NotImplementedError(f"FFC mode {mode} is not implemented.")

        res = self._send_and_recv_threaded(command, argument)
        if res:
            self._log.info(f'Set FFC mode to {mode.capitalize()}.')
            return True
        self._log.warning(f'Setting FFC mode to {mode.capitalize()} failed.')
        return False

    def ffc(self, length: bytes = ptc.FFC_LONG) -> None:
        res = self._send_and_recv_threaded(ptc.DO_FFC, length)
        if res and struct.unpack('H', res)[0] == 0xffff:
            self._log.debug('FFC')
        else:
            self._log.debug('FFC Failed')

    def get_last_image(self):
        num_snapshots, _ = self.get_num_snapshots()

        if num_snapshots > 0:
            return self.retrieve_snapshot(num_snapshots - 1)
        else:
            return None

    def _send_data(self, data: bytes) -> None:
        n_bytes = self.conn.write(data)
        self.conn.flush()
        return

    def _receive_data(self, n_bytes):
        return self.conn.read(n_bytes)

    @property
    def gain(self):
        res = self._send_and_recv_threaded(ptc.GET_GAIN_MODE, None)
        return struct.unpack('>h', res)[0] if res else 0xffff

    @gain.setter
    def gain(self, mode: str):
        if not (mode := ptc.GAIN_CODE_DICT[mode.lower()]):
            raise NotImplementedError(f"Gain mode {mode} is not implemented.")
        if mode == self.gain:
            self._log.info(f'Set Gain mode to {mode}')
            return
        for _ in range(9):
            res = self._send_and_recv_threaded(ptc.SET_GAIN_MODE, struct.pack('>h', mode))
            if res and struct.unpack('>h', res)[0] == mode:
                self._log.info(f'Set Gain mode to {mode}')
                return
        self._log.warning(f'Setting Gain mode to {mode} failed.')

    @property
    def agc(self):
        res = self._send_and_recv_threaded(ptc.GET_AGC_ALGORITHM, None)   # todo: does this function even works????
        return struct.unpack('>h', res)[0] if res else 0xffff

    @agc.setter
    def agc(self, mode: str):
        if not (mode := ptc.AGC_CODE_DICT[mode.lower()]):
            raise NotImplementedError(f"AGC mode {mode} is not implemented.")
        if mode == self.agc:
            self._log.info(f'Set AGC mode to {mode}')
            return
        for _ in range(9):
            res = self._send_and_recv_threaded(ptc.SET_AGC_ALGORITHM, struct.pack('>h', mode))
            if res and struct.unpack('>h', res)[0] == mode:
                self._log.info(f'Set AGC mode to {mode}')
                return
        self._log.warning(f'Setting AGC mode to {mode} failed.')

    @property
    def sso(self) -> float:
        res = self._send_and_recv_threaded(ptc.GET_AGC_THRESHOLD, struct.pack('>h', 0x0400))
        return struct.unpack('>e', res)[0] if res else 0xffff

    @sso.setter
    def sso(self, percentage: float):
        if percentage == self.sso:
            self._log.info(f'Set SSO to {percentage:.2f}')
            return
        for _ in range(9):
            res = self._send_and_recv_threaded(ptc.SET_AGC_THRESHOLD, struct.pack('>he', 0x0400, percentage))
            if res:  # todo: there should be no response.. check this issue and maybe compare to the self.sso
                break
        self._log.warning(f'Setting SSO to {percentage:.2f} failed.')

    def _get_agc_values(self, command):
        res = self._send_and_recv_threaded(command, None)
        return struct.unpack('>h', res)[0] if res else 0xffff

    def _set_agc_values(self, value: int, current_value: int, command: ptc.Code) -> bool:
        if value == current_value:
            return True
        for _ in range(9):
            res = self._send_and_recv_threaded(command, struct.pack('>h', value))
            if res and struct.unpack('>h', res)[0] == value:
                return True
        return False

    def _log_agc_value_set(self, value: int, result: bool, agc_value_name: str) -> None:
        if result:
            self._log.info(f'Set AGC {agc_value_name} to {value}.')
        else:
            self._log.warning(f'Setting AGC {agc_value_name} to {value} failed.')

    @property
    def contrast(self) -> int:
        return self._get_agc_values(ptc.GET_CONTRAST)

    @contrast.setter
    def contrast(self, value: int):
        self._log_agc_value_set(value, self._set_agc_values(value, self.contrast, ptc.SET_CONTRAST), 'contrast')

    @property
    def brightness(self) -> int:
        return self._get_agc_values(ptc.GET_BRIGHTNESS)

    @brightness.setter
    def brightness(self, value: int):
        self._log_agc_value_set(value, self._set_agc_values(value, self.brightness, ptc.SET_BRIGHTNESS), 'brightness')

    @property
    def brightness_bias(self) -> int:
        return self._get_agc_values(ptc.GET_BRIGHTNESS_BIAS)

    @brightness_bias.setter
    def brightness_bias(self, value: int):
        result = self._set_agc_values(value, self.brightness_bias, ptc.SET_BRIGHTNESS_BIAS)
        self._log_agc_value_set(value, result, 'brightness_bias')


class TeaxGrabber(Tau):
    """
    Data acquisition class for the Teax ThermalCapture Grabber USB

    """

    def __init__(self, vid=0x0403, pid=0x6010, width=WIDTH_IMAGE, height=HEIGHT_IMAGE,
                 logging_handlers: tuple = make_logging_handlers(None, True), logging_level: int = logging.INFO):
        super().__init__(logging_handlers=logging_handlers, logging_level=logging_level)
        logging_handlers = make_device_logging_handler('TeaxGrabber', logging_handlers)
        self._log = make_logger('TeaxGrabber', logging_handlers, logging_level)
        self._dev = usb.core.find(idVendor=vid, idProduct=pid)

        self.ftdi_ = None
        self.frame_size = 2 * height * width + 10 + 4 * height  # 10 byte header, 4 bytes pad per row
        self._width = width
        self._height = height

        if self._dev:
            self._connect()
            # Check for UART and TEAX magic strings, but
            # it's OK if we timeout here
            # using threads for FtdiIO
            self.io = FtdiIO(self.ftdi_, self.frame_size, logging_handlers, logging_level)
        else:
            raise RuntimeError('Could not connect to the Tau2 camera.')

    def _connect(self) -> None:
        if self._dev.is_kernel_driver_active(0):
            self._dev.detach_kernel_driver(0)

        self._claim_dev()

        self.ftdi_ = Ftdi()
        self.ftdi_.open_from_device(self._dev)

        self.ftdi_.set_bitmode(0xFF, Ftdi.BitMode.RESET)
        self.ftdi_.set_bitmode(0xFF, Ftdi.BitMode.SYNCFF)

    def _claim_dev(self):
        self._dev.reset()
        self._release()

        self._dev.set_configuration(1)

        usb.util.claim_interface(self._dev, 0)
        usb.util.claim_interface(self._dev, 1)

    def _release(self):
        for cfg in self._dev:
            for intf in cfg:
                if self._dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    try:
                        self._dev.detach_kernel_driver(intf.bInterfaceNumber)
                    except usb.core.USBError as e:
                        print("Could not detach kernel driver from interface({0}): {1}".format(intf.bInterfaceNumber,
                                                                                               str(e)))

    def _send_and_recv_threaded(self, command: ptc.Code, argument: (bytes, None)) -> list:
        data = self._make_packet(command, argument)
        return self.io.parse(data, command)

    def grab(self, to_temperature: bool = False, width: int = 336):
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
        # data = idx = None
        while True:
            data = self.io.get_image()
            if data:
                if struct.unpack('H', data[10:12])[0] != 0x4000:  # a magic word
                    continue
                frame_width = np.frombuffer(data[5:7], dtype='uint16')[0] - 2
                if frame_width != width:
                    self._log.debug(f"Received frame has width of {frame_width} - different than expected {width}.")
                    continue
                raw_image_8bit = np.frombuffer(data[10:], dtype='uint8').reshape((-1, 2 * (width + 2)))
                if not self._is_8bit_image_borders_valid(raw_image_8bit):
                    continue
                raw_image_16bit = 0x3FFF & raw_image_8bit.view('uint16')[:, 1:-1]

                # results should be within [0,100] Celsius
                if (6825 >= raw_image_16bit).all() or (raw_image_16bit >= 9325).all():
                    continue
                if to_temperature:
                    raw_image_16bit = 0.04 * raw_image_16bit - 273
                return raw_image_16bit

    def __exit__(self, type, value, traceback):
        self._log.info("Disconnecting from camera.")

    @property
    def is_dummy(self):
        return False

    def _is_8bit_image_borders_valid(self, raw_image_8bit: np.ndarray) -> bool:
        if np.nonzero(raw_image_8bit[:, 0] != 0)[0]:
            return False
        valid_idx = np.nonzero(raw_image_8bit[:, -1] != BORDER_VALUE)
        if len(valid_idx) != 1:
            return False
        valid_idx = int(valid_idx[0])
        if valid_idx != self._height - 1:  # the different value should be in the bottom of the border
            return False
        return True
