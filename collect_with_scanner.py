import tkinter as tk
from datetime import datetime
from pathlib import Path
from threading import Thread
from time import sleep, time_ns

from PIL import ImageTk
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


def left_key(event):
    scanner(1)


def right_key(event):
    scanner(-1)


def th_mover():
    while True:
        scanner.move_between_limits()
        sleep(1)


def save_key(event):
    mover = Thread(target=th_mover, daemon=True, name='th_scanner_mover')
    mover.start()

    dict_meas = {}
    time_to_collect_ns = 1e10  # save every 10 seconds
    now = datetime.now().strftime("%Y%m%d_h%Hm%Ms%S")
    n_saves = 0
    with tqdm() as progressbar:
        while True:
            t_start_ns = time_ns()
            progressbar.set_description_str(f'Number of saves: {n_saves}')
            while 1e-9 * (time_to_collect_ns - (time_ns() - t_start_ns)) > 0:
                fpa = camera.fpa
                dict_meas.setdefault('frames', []).append(camera.image)
                dict_meas.setdefault('blackbody', []).append(-1)  # compatibility with save_results()
                dict_meas.setdefault(T_FPA, []).append(fpa)
                dict_meas.setdefault(T_HOUSING, []).append(camera.housing)
                dict_meas.setdefault('time_ns', []).append(time_ns())
                progressbar.update()
            progressbar.set_postfix_str(f'FPA {fpa / 100:.1f}C')
            save_results(path_to_save=Path.cwd() / 'meas', filename=f'{now}_{n_saves}.npz', dict_meas=dict_meas)


def th_viewer():
    image = camera.image
    size_root = (root.winfo_height(), root.winfo_width())
    size_canvas = (lmain.winfo_height(), lmain.winfo_width())
    if size_canvas != size_root:
        lmain.config(width=root.winfo_width(), height=root.winfo_height())
    image_tk = ImageTk.PhotoImage(normalize_image(image).resize(reversed(size_canvas)))
    lmain.image_tk = image_tk
    lmain.configure(image=image_tk)
    lmain.after(ms=1000 // 30, func=th_viewer)


def right_limit():
    scanner.set_right_limit()


def left_limit():
    scanner.set_left_limit()


if __name__ == "__main__":
    # init devices
    scanner = Scanner()
    params = INIT_CAMERA_PARAMETERS.copy()
    params['tlinear'] = 0
    params['ffc_mode'] = 'auto'
    params['ffc_period'] = 1800
    params['lens_number'] = 1
    camera = CameraCtrl(camera_parameters=params)
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
          'Then, press "s" to start saving the images.\n', flush=True)
    root.bind('<z>', right_limit)
    root.bind('<a>', left_limit)
    root.bind('<s>', save_key)
    app.grid()
    lmain = tk.Label(app)
    lmain.grid()
    th_viewer()
    root.mainloop()
