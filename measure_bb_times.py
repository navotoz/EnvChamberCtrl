import signal
import sys
from pathlib import Path
from time import sleep

import numpy as np
from tqdm import tqdm

from devices.BlackBodyCtrl import BlackBodyThread
from utils.misc import args_meas_bb_times

sys.path.append(str(Path().cwd().parent))


def _stop(a, b, **kwargs) -> None:
    try:
        blackbody.terminate()
        print('BlackBody terminated.', flush=True)
    except (ValueError, TypeError, AttributeError, RuntimeError, NameError, KeyError, AssertionError):
        pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    args = args_meas_bb_times()
    if not 0.1 <= args.blackbody_increments <= 10:
        raise ValueError(f'blackbody_increments must be in [0.1, 10], got {args.blackbody_increments}')
    if args.n_samples <= 0:
        raise ValueError(f'n_samples must be > 0, got {args.n_samples}')
    if not 10 < args.blackbody_max <= 70:
        raise ValueError(f'blackbody_max must be in [10, 70], got {args.blackbody_max}')
    if not 10 <= args.blackbody_min < 70:
        raise ValueError(f'blackbody_min must be in [0.1, 10], got {args.blackbody_min}')
    if args.blackbody_max <= args.blackbody_min:
        raise ValueError(
            f'blackbody_min ({args.blackbody_min}) must be smaller than blackbody_max ({args.blackbody_max}.')
    if args.blackbody_increments >= (args.blackbody_max - args.blackbody_min):
        raise ValueError(f'blackbody_increments must be bigger than abs(max-min) of the Blackbody.')

    blackbody = BlackBodyThread(logfile_path=None, output_folder_path=path_to_save)
    blackbody.start()

    # wait for the devices to start
    sleep(1)
    with tqdm(desc="Waiting for devices to connect.") as progressbar:
        while not blackbody.is_connected:
            progressbar.set_postfix_str(f"Blackbody {'Connected' if blackbody.is_connected else 'Waiting'}")
            progressbar.update()
            sleep(1)
    print('Devices Connected.', flush=True)

    # measurements
    bb_min = args.blackbody_min
    bb_max = args.blackbody_max
    bb_inc = args.blackbody_increments
    bb_temperatures = np.linspace(bb_min, bb_max, int((bb_max - bb_min) / bb_inc)).round(2)

    for bb in tqdm(bb_temperatures, desc="Rise"):
        blackbody.temperature = bb
        sleep(60 * args.n_samples)  # wait for the frames to be captured at 60Hz

    sleep(5)  # clear the tqdm buffers

    for bb in tqdm(np.flip(bb_temperatures), desc="Descent"):
        blackbody.temperature = bb
        sleep(60 * args.n_samples)  # wait for the frames to be captured at 60Hz