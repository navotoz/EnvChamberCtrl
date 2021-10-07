import multiprocessing as mp



class PlotterProc(mp.Process):
    def __init__(self, flag_run, event_timer, output_path: (str, Path)):
        super(PlotterProc, self).__init__()
        self._event_timer = event_timer
        self._event_timer.set()
        self._flag_run = flag_run
        self._output_path = Path(output_path) / PLOTS_PATH / 'oven'
        self._records_path = Path(output_path) / const.OVEN_RECORDS_FILENAME

    def run(self) -> None:
        th_timer = th.Thread(target=self._timer, name='th_proc_plotter_timer', daemon=True)
        th_timer.start()
        while self._flag_run:
            try:
                self._event_timer.wait()
                check_and_make_path(self._output_path)
                plot_oven_records_in_path(self._records_path, self._output_path)
            except Exception as err:
                print(f'Records collection failed - {err}')
                pass
            self._event_timer.clear()
        try:
            th_timer.join()
        except (RuntimeError, AssertionError, AttributeError):
            pass

    def __del__(self):
        self.terminate()

    def terminate(self) -> None:
        if hasattr(self, '_flag_run'):
            self._flag_run.set(False)
        try:
            self._event_timer.set()
        except (RuntimeError, AssertionError, AttributeError, TypeError):
            pass
        try:
            self.kill()
        except (RuntimeError, AssertionError, AttributeError, TypeError):
            pass

    def _timer(self):
        while self._flag_run:
            self._event_timer.set()
            sleep(OVEN_LOG_TIME_SECONDS)
        self._event_timer.set()


def _th_temperature_setter(self) -> None:
    next_temperature, fin_msg = 0, 'Finished waiting due to '
    handlers = make_logging_handlers('log/oven/temperature_differences.txt')
    logger_waiting = make_logger('OvenTempDiff', handlers, False)

    # handle dummy oven
    if self._event_connected.is_set() == const.DEVICE_REAL:
        get_error = wait_for_time(partial(self._oven_temperatures.get, SIGNALERROR), wait_time_in_sec=PID_FREQ_SEC)
        initial_wait_time = PID_FREQ_SEC + OVEN_LOG_TIME_SECONDS * 4  # to let the average ErrSignal settle
    else:
        get_error = lambda: 0
        initial_wait_time = 1

    # thread loop
    while self._flag_run:
        self._semaphore_setpoint.acquire()
        next_temperature = self.setpoint
        if not self._flag_run or not next_temperature or next_temperature <= 0:
            return

        # creates a round-robin queue of differences (dt_camera) to wait until t_camera settles
        queue_temperatures = VariableLengthDeque(maxlen=max(1, self._make_maxlength()))
        queue_temperatures.append(-float('inf'))  # -inf so that the diff always returns +inf
        offset = _make_temperature_offset(t_next=next_temperature,
                                          t_oven=self._oven_temperatures.get(T_FLOOR).value,
                                          t_cam=get_inner_temperature())
        self._set_oven_temperature(next_temperature, offset=offset, verbose=True)

        # wait until signal error reaches within 1.5deg of setPoint
        tqdm_waiting(initial_wait_time, 'Waiting for PID to settle', self._flag_run)
        while self._flag_run and get_error() >= 1.5:
            pass
        self._set_oven_temperature(next_temperature, offset=0, verbose=True)

        self._oven.log.info(f'Waiting for the Camera to settle near {next_temperature:.2f}C')
        logger_waiting.info(f'#######   {next_temperature}   #######')
        while msg := self._flag_run:
            if queue_temperatures.is_full:
                msg = f'{fin_msg}{self.settling_time_minutes}Min without change in temperature.'
                break
            queue_temperatures.maxlength = self._make_maxlength()
            queue_temperatures.append(get_inner_temperature())
            n_minutes_settled = self._samples_to_minutes(len(queue_temperatures))
            logger_waiting.info(f"FPA{queue_temperatures[0]:.1f} "
                                f"{self.settling_time_minutes:3d}|{n_minutes_settled:.2f}Min")
        logger_waiting.info(msg) if isinstance(msg, str) else None
        self._oven.log.info(msg) if isinstance(msg, str) else None
        self._temperature_pipe.send(next_temperature)
        self._oven.log.info(f'Camera reached temperature {queue_temperatures[0]:.2f}C '
                            f'and settled for {self.settling_time_minutes} minutes.')
