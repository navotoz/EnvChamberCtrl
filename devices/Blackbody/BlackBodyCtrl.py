import logging
import socket
import threading as th
from queue import SimpleQueue, Empty
from time import time_ns, sleep

from devices.Blackbody import BlackBodyAbstract
from utils.logger import make_logger, make_device_logging_handler

TIMEOUT_IN_SECONDS = 3
DATAGRAM_MAX_SIZE = 1024


class BlackBody(BlackBodyAbstract):
    def __init__(self, client_ip: str = '10.26.91.56', host_port: int = 5100, client_port: int = 5200,
                 logging_handlers: tuple = (logging.StreamHandler(),), logging_level: int = logging.INFO):
        logging_handlers = make_device_logging_handler('blackbody', logging_handlers)
        super().__init__(make_logger('BlackBody', logging_handlers, logging_level))
        self.__host_port = host_port  # port to receive data
        self.__client_ip = client_ip  # blackbody IP
        self.__client_port = client_port  # port to send data

        self._recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._recv_socket.bind(('', self.__host_port))

        self._send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._send_socket.connect((self.__client_ip, self.__client_port))

        self.__recv_msg_queue = SimpleQueue()
        self.__recv_thread = th.Thread(target=self.__recv_thread_func, daemon=True, name='th_recv_blackbody')
        self.__recv_thread.start()

        self.__echo("Initial Check".upper())
        self.__check_bit()
        self.__set_mode_absolute()
        self._log.info('Ready.')

    def __del__(self):
        self._recv_socket.close()
        self._send_socket.close()

    def __send(self, msg):
        msg = msg.upper()
        self._send_socket.send(msg.encode('utf-8'))
        self._log.debug(f"Send: {msg}")

    def __recv(self) -> (str, None):
        msg = None
        try:
            msg = self.__recv_msg_queue.get(block=True, timeout=TIMEOUT_IN_SECONDS)
            self._log.debug(f"Recv: {msg}")
        except Empty:
            self._log.warning('Timeout on __recv.')
        return msg

    def __echo(self, msg: str):
        """
        Sends an echo to the BlackBody. Expects the result to be the same as msg.
        If successful, logged as debug.
        If fails, raises ConnectionError.
        """
        self.__send('Echo ' + msg)
        recv_msg = self.__recv()
        if not recv_msg or msg not in recv_msg:
            msg = 'Echo test failed. Exiting.'
            self._recv_socket.close()
            self._send_socket.close()
            self._log.critical(msg)
            raise RuntimeError(msg)
        self._log.debug('Echo succeed.')

    def __recv_thread_func(self):
        """
        A receiver thread.
        """
        while True:
            self.__recv_msg_queue.put(self._recv_socket.recv(DATAGRAM_MAX_SIZE).decode())

    @property
    def temperature(self) -> float:
        """
        Returns:
            float: The current temperature of the BlackBody.
        """
        self.__send('GetTemperature')
        return float(self.__recv())

    @temperature.setter
    def temperature(self, temperature_to_set: (float, int), wait_for_stable_temperature: bool = True):
        """
        Temperature setter. Sends the given temperature to the BlackBody,
        and waits until the BlackBody stabilizes to it.
        Function is finished when the BlackBody is stable.
        """
        self.__send(f'SetTemperature {temperature_to_set}')
        msg = f"Set temperature to {temperature_to_set}C."
        self._log.info(msg + ' Waiting for stable temperature.' if wait_for_stable_temperature else '')
        if wait_for_stable_temperature:
            self.__wait_for_stable_temperature()
            self._log.info(f"Temperature {temperature_to_set}C is set.")

    def __wait_for_stable_temperature(self):
        """
        An busy-waiting loop for the temperature in the BlackBody to settle.
        Repeatedly pools the BB until "Stable" is received.
        Upon receiving the "Stable" signal, logs the results and finishes the function without returning a value.
        """
        t, is_temperature_stable = time_ns(), False
        sleep(1)  # defined in p.118, sec.6.2.25 of the BB manual
        while not is_temperature_stable:
            self.__send('IsTemperatureStable')
            is_temperature_stable = bool(int(self.__recv()))
            sleep(1)
        t = (time_ns() - t) * 1e-9
        if t > 60:
            t = f"in {t / 60:.1f} minutes."
        else:
            t = f"in {t:.1f} seconds."
        self._log.info(f"Reached stable temperature of {self.temperature}C {t}")

    def __set_mode_absolute(self):
        """
        Sets the temperature mode to 'absolute' in the BlackBody.
        """
        self.__send('SetMode 1')

    @property
    def bit(self) -> bool:
        """
        Return BIT results for the BlackBody.

        Returns:
            bool: True if BIT successful, else raises RuntimeError.
        """
        msg = self.__check_bit()
        if 'OK' in msg:
            return True
        msg = f"Error in BIT: {msg}."
        self._log.warning(msg)
        raise RuntimeError(msg)

    def __check_bit(self) -> str:
        """
        Private method for checking BIT in the BlackBody.

        Returns:
            str: 'OK' if BIT successful, else fail message.
        """
        self.__send('GetBitError')
        return self.__recv()

    def __call__(self, temperature_to_set: (float, int)):
        """
        The temperature setter as a call function.
        """
        self.temperature = temperature_to_set

    @property
    def is_dummy(self):
        return False
