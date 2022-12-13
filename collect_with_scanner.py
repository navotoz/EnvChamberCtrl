import tkinter as tk
from datetime import datetime
from functools import partial
from pathlib import Path
from threading import Event, Thread
from time import time_ns

from PIL import ImageTk, ImageDraw, ImageFont
from tqdm import tqdm

from devices.Camera import INIT_CAMERA_PARAMETERS, T_FPA, T_HOUSING
from devices.Camera.CameraProcess import CameraCtrl
from devices.Scanner.ScannerCtrl import Scanner
from utils.common import save_results
from utils.misc import normalize_image

HEIGHT_VIEWER = int(2 * 336)
WIDTH_VIEWER = int(2 * 256)


def closer():
    try:
        root.destroy()
    except tk.TclError:
        pass


def save_key(event) -> None:
    if event_run.is_set():
        print('Stopping acquisition, and saving data', flush=True)
        event_run.clear()
    else:
        print('Starting acquisition', flush=True)
        event_run.set()


def th_saver():
    path_to_save = Path.cwd() / 'measurements'
    if not path_to_save.is_dir():
        path_to_save.mkdir()
    while True:
        event_run.wait()
        now = datetime.now().strftime("%Y%m%d_h%Hm%Ms%S")
        dict_meas = {}
        with tqdm() as progressbar:
            while event_run.is_set():
                fpa = camera.fpa
                dict_meas.setdefault('frames', []).append(camera.image)
                dict_meas.setdefault('blackbody', []).append(-1)  # compatibility with save_results()
                dict_meas.setdefault(T_FPA, []).append(fpa)
                dict_meas.setdefault(T_HOUSING, []).append(camera.housing)
                dict_meas.setdefault('time_ns', []).append(time_ns())
                progressbar.update()
            progressbar.set_postfix_str(f'FPA {fpa / 100:.1f}C')
            save_results(path_to_save=path_to_save, filename=f'{now}.npz', dict_meas=dict_meas)


def th_viewer():
    image = camera.image
    size_root = (root.winfo_height(), root.winfo_width())
    size_canvas = (lmain.winfo_height(), lmain.winfo_width())
    if size_canvas != size_root:
        lmain.config(width=root.winfo_width(), height=root.winfo_height())
    image = normalize_image(image).resize(reversed(size_canvas))

    # add text to the upper-left corner with ImageDraw
    fnt = ImageFont.truetype("Pillow/Tests/fonts/FreeMono.ttf", 24)
    drawer = partial(ImageDraw.Draw(image).text, fill='red', font=fnt, stroke_width=1)
    drawer((2, 1), f'FPA {camera.fpa / 100:.1f}C')
    drawer((root.winfo_width() - 5 * fnt.size, root.winfo_height() - fnt.size - 2),
           'Sampling' if event_run.is_set() else '')
    image_tk = ImageTk.PhotoImage(image)
    lmain.image_tk = image_tk
    lmain.configure(image=image_tk)
    lmain.after(ms=1000 // 30, func=th_viewer)


def left_key(event):
    scanner.move(-1)


def right_key(event):
    scanner.move(1)


def right_limit(event):
    scanner.set_limit('right')


def left_limit(event):
    scanner.set_limit('left')


if __name__ == "__main__":
    event_run = Event()
    event_run.clear()
    th_save = Thread(target=th_saver, daemon=True)
    th_save.start()
    scanner = Scanner()
    scanner.start()

    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = 0
    params['ffc_mode'] = 'auto'
    params['ffc_period'] = 1800
    params['lens_number'] = 1
    # camera = CameraCtrl(camera_parameters=params)
    camera = CameraCtrl(camera_parameters=None)
    camera.start()

    # init GUI
    root = tk.Tk()
    root.protocol('WM_DELETE_WINDOW', closer)
    root.title("Tau2 Images collector")
    root.option_add("*Font", "TkDefaultFont 14")
    root.geometry(f"{HEIGHT_VIEWER}x{WIDTH_VIEWER}")
    # root.pack_propagate(0)  is it needed?

    app = tk.Frame(root, bg='white')
    root.bind('<Left>', left_key)
    root.bind('<Right>', right_key)
    print('\nPress left and right arrow to move the scanner.\n'
          'Go to the left-most limit and press "z".\n'
          'Go to the right-most limit and press "x".\n'
          'Press "m" to start moving between limits.\n'
          'Then, press "s" to start acquiring the images and then to stop and save.\n', flush=True)
    root.bind('<z>', left_limit)
    root.bind('<x>', right_limit)
    root.bind('<m>', scanner.move_between_limits)
    root.bind('<s>', save_key)
    app.grid()
    lmain = tk.Label(app)
    lmain.grid()
    th_viewer()
    root.mainloop()
