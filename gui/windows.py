import tkinter as tk
from pathlib import Path
from threading import Thread
from time import sleep
from tkinter import filedialog

import numpy as np
from PIL import ImageTk

from gui.tools import func_thread_grabber
from utils.constants import HEIGHT_VIEWER, WIDTH_VIEWER
from utils.misc import normalize_image


def open_upload_window():
    global viewer_window
    if not viewer_window:
        viewer_window = tk.Toplevel()
        viewer_window.title("Show a saved image")
        viewer_window.geometry(f"{HEIGHT_VIEWER}x{WIDTH_VIEWER}")
        canvas = tk.Canvas(viewer_window, width=WIDTH_VIEWER, height=HEIGHT_VIEWER)
        canvas.pack()
        filename = filedialog.askopenfilename(initialdir=Path.cwd().parent / 'experiments',
                                              title='Choose an image ending with npy.',
                                              filetypes=(('numpy', '*.npy'), ('numpy', '*.npz')))
        if not filename:
            viewer_window.destroy()
            viewer_window = None
            return
        image = ImageTk.PhotoImage(normalize_image(np.load(filename)))
        th = Thread(target=func_upload, args=(image, canvas,), daemon=True, name=f'th_uploader_{str(Path(filename).stem)}')
        th.start()
    else:
        viewer_window = None
        open_upload_window()


def func_upload(image, canvas):
    while canvas.winfo_exists():
        canvas.create_image(0, 0, image=image, anchor=tk.NW) if canvas.winfo_exists() else None
        canvas.update_idletasks() if canvas.winfo_exists() else None
        canvas.update_idletasks()
        sleep(0.5)


# noinspection PyUnresolvedReferences
def open_viewer_window(camera_grabber, name):
    global viewer_window
    if not viewer_window:
        viewer_window = tk.Toplevel()
        viewer_window.title("Camera Viewer")
        viewer_window.geometry(f"{HEIGHT_VIEWER}x{WIDTH_VIEWER}")
        canvas = tk.Canvas(viewer_window, width=WIDTH_VIEWER, height=HEIGHT_VIEWER)
        canvas.pack()
        thread_camera = Thread(target=func_thread_viewer, args=(camera_grabber, canvas,), name='th_viewer', daemon=True)
        thread_camera.start()
    elif viewer_window.winfo_exists():
        viewer_window.focus()
        viewer_window.lift()
    elif not viewer_window.winfo_exists():
        viewer_window = None
        open_viewer_window(devices_dict, name)


def func_thread_viewer(device, canvas: tk.Canvas):
    while canvas.winfo_exists():
        image = ImageTk.PhotoImage(image=func_thread_grabber(device))
        canvas.create_image((0, 0), anchor=tk.NW, image=image) if canvas.winfo_exists() else None
        canvas.update_idletasks() if canvas.winfo_exists() else None
        sleep(0.01)


viewer_window = None
