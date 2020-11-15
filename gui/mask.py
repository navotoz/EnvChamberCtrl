import tkinter as tk
from pathlib import Path
from threading import Thread, Semaphore
from time import sleep

import numpy as np
from PIL import ImageTk
from matplotlib.path import Path as matplotlib_Path

from utils.constants import HEIGHT_VIEWER, WIDTH_VIEWER, WIDTH_IMAGE, HEIGHT_IMAGE
from gui.utils import func_thread_grabber


# noinspection PyTypeChecker
def _func_thread_mask(device, canvas: tk.Canvas, semaphore: Semaphore, output_path: (str, Path)):
    global top_left, top_right, bottom_left, bottom_right
    while canvas.winfo_exists():
        image = ImageTk.PhotoImage(image=func_thread_grabber(device))
        canvas.create_image((0, 0), anchor=tk.NW, image=image) if canvas.winfo_exists() else None
        canvas.config(scrollregion=canvas.bbox(tk.ALL)) if canvas.winfo_exists() else None
        canvas.create_polygon((*top_right, *top_left, *bottom_left, *bottom_right), width=2,
                              outline="green", fill="red", stipple="gray12") if canvas.winfo_exists() else None
        canvas.update_idletasks() if canvas.winfo_exists() else None
        sleep(0.5)
    semaphore.release()
    x, y = np.mgrid[:HEIGHT_IMAGE, :WIDTH_IMAGE]
    coors = np.hstack((y.reshape(-1, 1), x.reshape(-1, 1)))  # coors.shape is (4000000,2)
    top_right_, top_left_, bottom_left_, bottom_right_ = top_right(), top_left(), bottom_left(), bottom_right()
    pts = (top_right_[0] + 1, top_right_[1] - 1), (top_left_[0] - 1, top_left_[1] - 1), bottom_left_, bottom_right_
    path = matplotlib_Path(pts)
    mask = path.contains_points(coors).reshape(HEIGHT_IMAGE, WIDTH_IMAGE)
    np.save(output_path / 'mask', mask)


def _make_new_rect(x, y):
    global top_left, top_right, bottom_left, bottom_right
    idx = np.argmin(list(map(lambda point: point.distance(x, y), (top_left, top_right, bottom_left, bottom_right))))
    if idx == 0:
        top_left = _Point(x, y)
    if idx == 1:
        top_right = _Point(x, y)
    if idx == 2:
        bottom_left = _Point(x, y)
    if idx == 3:
        bottom_right = _Point(x, y)


class _Point:
    def __init__(self, x, y):
        self.coord = (int(x), int(y))

    def __repr__(self):
        return f"({self.coord[0]}, {self.coord[1]})"

    def __iter__(self):
        for coord in self.coord:
            yield coord

    def distance(self, x, y) -> float:
        return float(np.sqrt((x - self.coord[0]) ** 2 + (y - self.coord[1]) ** 2))

    def __call__(self):
        return self.coord


def make_mask_win_and_save(device, semaphore: Semaphore, output_path):
    window = tk.Toplevel()
    window.title("Camera Mask Creator")
    window.geometry(f"{HEIGHT_VIEWER}x{WIDTH_VIEWER}")
    frame = tk.Frame(window, bd=2, relief=tk.SUNKEN)
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(0, weight=1)
    x_scroll = tk.Scrollbar(frame, orient=tk.HORIZONTAL)
    x_scroll.grid(row=1, column=0, sticky=tk.E + tk.W)
    y_scroll = tk.Scrollbar(frame)
    y_scroll.grid(row=0, column=1, sticky=tk.N + tk.S)
    canvas = tk.Canvas(frame, bd=0, width=WIDTH_VIEWER, height=HEIGHT_VIEWER,
                       xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
    canvas.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W)
    x_scroll.config(command=canvas.xview)
    y_scroll.config(command=canvas.yview)
    frame.pack(fill=tk.BOTH, expand=1)

    def handle_mouseclick(event):
        click_x, click_y = canvas.canvasx(event.x), canvas.canvasx(event.y)
        _make_new_rect(min(click_x, WIDTH_IMAGE), min(click_y, HEIGHT_IMAGE))

    # mouseclick event
    canvas.bind("<ButtonPress-1>", handle_mouseclick)
    thread_camera = Thread(target=_func_thread_mask, args=(device, canvas, semaphore, output_path), name='th_mask', daemon=True)
    thread_camera.start()


top_left, top_right = _Point(0, 0), _Point(WIDTH_IMAGE, 0)
bottom_left, bottom_right = _Point(0, HEIGHT_IMAGE), _Point(WIDTH_IMAGE, HEIGHT_IMAGE)
