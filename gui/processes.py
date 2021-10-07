import logging
import multiprocessing as mp
from pathlib import Path

from utils.logger import make_logging_handlers, make_logger

log_path = Path('log')
handlers = make_logging_handlers(logfile_path=log_path / 'log.txt', verbose=True)
logger = make_logger('GUI', handlers=handlers, level=logging.INFO)
semaphore_plot_proc = mp.Semaphore(0)

# init hardware
# oven = OvenCtrl(logfile_path=log_path, output_path=None)
# oven.start()
#
# camera = CameraCtrl(camera_parameters=,
#                     is_dummy=False)
# camera.start()
#
# blackbody = BlackBodyThread(logging_handlers=handlers)
# blackbody.start()
