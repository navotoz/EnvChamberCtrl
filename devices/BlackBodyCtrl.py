import logging
import socket
import threading as th
from pathlib import Path
from queue import SimpleQueue, Empty
from time import time_ns, sleep
from typing import Union

import utils.constants as const
from utils.logger import make_logger, make_logging_handlers
from utils.misc import SyncFlag

TIMEOUT_IN_SECONDS = 3
DATAGRAM_MAX_SIZE = 1024


class BlackBody:
    def __init__(self, client_ip: str = '188.51.1.2', host_port: int = 5100, client_port: int = 5200,
                 logging_handlers: tuple = (), logging_level: int = logging.INFO):
        super().__init__()
        self._log = make_logger('BlackBody', logging_handlers, logging_level)
        self._host_port = host_port  # port to receive data
        self._client_ip = client_ip  # blackbody IP
        self._client_port = client_port  # port to send data

        self._recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._recv_socket.bind(('', self._host_port))

        self._send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._send_socket.connect((self._client_ip, self._client_port))

            self._recv_msg_queue = SimpleQueue()
            self._recv_thread = th.Thread(target=self._recv_thread_func, daemon=True, name='th_recv_blackbody')
            self._recv_thread.start()
            sleep(0.1)

            self.echo(verbose=False)
        except (OSError, RuntimeError):
            raise RuntimeError

        self.echo("Initial Check".upper(), verbose=True)
        self._check_bit()
        self._set_mode_absolute()
        self._log.info('Ready.')

    def __del__(self):
        try:
            self._recv_socket.close()
        except (RuntimeError, OSError, ValueError, IOError, AttributeError):
            pass
        try:
            self._send_socket.close()
        except (RuntimeError, OSError, ValueError, IOError, AttributeError):
            pass

    def _send(self, msg: str) -> None:
        msg = msg.upper()
        try:
            self._send_socket.send(msg.encode('utf-8'))
        except (OSError, RuntimeError, AttributeError, ValueError, IOError):
            self._log.error('Cannot send on BlackBody socket.')
            return
        self._log.debug(f"Send: {msg}")

    def _recv(self, verbose: bool = True) -> (str, None):
        msg = None
        try:
            msg = self._recv_msg_queue.get(block=True, timeout=TIMEOUT_IN_SECONDS)
            self._log.debug(f"Recv: {msg}") if verbose else None
        except (Empty, OSError):
            self._log.warning('Timeout on _recv.') if verbose else None
        return msg

    def echo(self, msg: str = 'ECHO', verbose: bool = True):
        """
        Sends an echo to the BlackBody. Expects the result to be the same as msg.
        If successful, logged as debug.
        If fails, raises ConnectionError.
        """
        self._send('Echo ' + msg)
        recv_msg = self._recv(verbose)
        if not recv_msg or msg.lower() not in recv_msg.lower():
            msg = 'Echo test failed. Exiting.'
            self._log.critical(msg) if verbose else None
            raise RuntimeError(msg)
        self._log.debug('Echo succeed.') if verbose else None

    def _recv_thread_func(self):
        """
        A receiver thread.
        """
        try:
            while True:
                self._recv_msg_queue.put(self._recv_socket.recv(DATAGRAM_MAX_SIZE).decode())
        except (OSError, RuntimeError, AttributeError, ValueError, IOError):
            return

    @property
    def temperature(self) -> (float, None):
        """
        Returns:
            float: The current temperature of the BlackBody.
        """
        self._send('GetTemperature')
        res = self._recv()
        return float(res) if res else None

    @property
    def is_stable(self) -> bool:
        sleep(1)  # defined in p.118, sec.6.2.25 of the BB manual
        self._send('IsTemperatureStable')
        return bool(int(self._recv()))

    def _wait_for_stable_temperature(self) -> None:
        """
        A busy-waiting loop for the temperature in the BlackBody to settle.
        Repeatedly pools the BB until "Stable" is received.
        Upon receiving the "Stable" signal, logs the results and finishes the function without returning a value.
        """
        t = time_ns()
        while not self.is_stable:
            continue
        t = (time_ns() - t) * 1e-9
        t = f"in {t / 60:.1f} minutes." if t > 60 else f"in {t:.1f} seconds."
        self._log.info(f"Reached stable temperature of {self.temperature}C {t}")

    def _set_mode_absolute(self):
        """
        Sets the temperature mode to 'absolute' in the BlackBody.
        """
        self._send('SetMode 1')

    @property
    def bit(self) -> bool:
        """
        Return BIT results for the BlackBody.

        Returns:
            bool: True if BIT successful, else raises RuntimeError.
        """
        msg = self._check_bit()
        if 'OK' in msg:
            return True
        msg = f"Error in BIT: {msg}."
        self._log.warning(msg)
        raise RuntimeError(msg)

    def _check_bit(self) -> str:
        """
        Private method for checking BIT in the BlackBody.

        Returns:
            str: 'OK' if BIT successful, else fail message.
        """
        self._send('GetBitError')
        return self._recv()

    def __call__(self, temperature_to_set: Union[float, int], *, wait_for_stable_temperature: bool = True):
        """
        Temperature setter. Sends the given temperature to the BlackBody,
        and waits until the BlackBody stabilizes to it.
        Function is finished when the BlackBody is stable.
        """
        self._send(f'SetTemperature {temperature_to_set}')
        msg = f"Set temperature to {temperature_to_set}C."
        self._log.info(msg + ' Waiting for stable temperature.' if wait_for_stable_temperature else '')
        if wait_for_stable_temperature:
            self._wait_for_stable_temperature()
            self._log.info(f"Temperature {temperature_to_set}C is set.")

    @property
    def is_dummy(self):
        return False


class BlackBodyThread(th.Thread):
    _blackbody: Union[BlackBody, None] = None
    _workers_dict = {}

    def __init__(self, logfile_path: Union[str, Path, None], output_folder_path: Union[str, Path]):
        super(BlackBodyThread, self).__init__()
        self._lock_access = th.Lock()
        self._event_is_connected = th.Event()
        self._event_is_connected.clear()
        self._flag_run = SyncFlag(init_state=True)

        self._logging_handlers = make_logging_handlers(logfile_path=logfile_path)
        self._log_temperature = make_logger(f'{const.BLACKBODY_NAME}Temperatures',
                                            make_logging_handlers(output_folder_path / 'temperatures.txt', False))

    def run(self):
        self._workers_dict['conn'] = th.Thread(target=self._th_conn, name='bb_conn')
        self._workers_dict['conn'].start()
        self._workers_dict['logger'] = th.Thread(target=self._th_logger, name='bb_log')
        self._workers_dict['logger'].start()

    def _th_conn(self):
        while self._flag_run:
            try:
                self._blackbody = BlackBody(logging_handlers=self._logging_handlers)
                self._event_is_connected.set()
                return
            except (RuntimeError, BrokenPipeError):
                pass
            sleep(3)

    def _th_logger(self):
        self._event_is_connected.wait()
        while self._flag_run:
            if self._event_is_connected.is_set():
                self._log_temperature.info(self.temperature)
            sleep(10)

    @property
    def temperature(self) -> Union[float, int]:
        with self._lock_access:
            return self._blackbody.temperature if self._event_is_connected.is_set() else None

    @temperature.setter
    def temperature(self, temperature_to_set: Union[float, int]):
        if self._event_is_connected.is_set():
            with self._lock_access:
                self._blackbody(temperature_to_set=temperature_to_set, wait_for_stable_temperature=True)

    def set_temperature_non_blocking(self, temperature_to_set: Union[int, float]):
        if self._event_is_connected.is_set():
            with self._lock_access:
                if self._blackbody.is_stable and abs(temperature_to_set - self._blackbody.temperature) <= 0.01:
                    return
                self._blackbody(temperature_to_set=temperature_to_set, wait_for_stable_temperature=False)

    @property
    def is_connected(self) -> bool:
        return self._event_is_connected.is_set()

    def terminate(self):
        try:
            self._flag_run.set(False)
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
            pass
        try:
            self._event_is_connected.clear()
        except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
            pass
        try:
            self._blackbody.__del__()
        except (RuntimeError, OSError, ValueError, IOError, AttributeError):
            pass


class BlackBodyDummyThread:
    def __init__(self) -> None:
        super().__init__()
        self._lock_access = th.Lock()
        self._temperature = 0.0

    @property
    def temperature(self) -> Union[float, int]:
        with self._lock_access:
            return self._temperature

    @temperature.setter
    def temperature(self, temperature_to_set: Union[float, int]):
        with self._lock_access:
            self._temperature = temperature_to_set

    @property
    def is_connected(self) -> bool:
        return True

    def terminate(self):
        pass
