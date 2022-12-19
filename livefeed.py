import tkinter as tk
from functools import partial

import pyftdi.ftdi
from PIL import ImageTk, ImageFont, ImageDraw

from devices.Camera.CameraProcess import CameraCtrl
from devices.Camera.Tau.Tau2Grabber import Tau2Grabber
from utils.misc import normalize_image

HEIGHT_VIEWER = int(2.5 * 336)
WIDTH_VIEWER = int(2.5 * 256)


def closer():
    try:
        camera.kill()
    except (RuntimeError, ValueError, NameError, KeyError, TypeError, AttributeError):
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


def th_viewer():
    try:
        image = camera.image
    except (RuntimeError, ValueError, NameError, pyftdi.ftdi.FtdiError):
        return
    if image is not None:
        size_root = (root.winfo_height(), root.winfo_width())
        size_canvas = (lmain.winfo_height(), lmain.winfo_width())
        if size_canvas != size_root:
            lmain.config(width=root.winfo_width(), height=root.winfo_height())
        image = normalize_image(image).resize(reversed(size_canvas))
        fnt = ImageFont.truetype("Pillow/Tests/fonts/FreeMono.ttf", 24)
        drawer = partial(ImageDraw.Draw(image).text, fill='red', font=fnt, stroke_width=1)
        drawer((2, 1), f'FPA {camera.fpa / 100:.1f}C')
        image_tk = ImageTk.PhotoImage(image)
        lmain.image_tk = image_tk
        lmain.configure(image=image_tk)
    lmain.after(ms=1000 // 30, func=th_viewer)


camera = CameraCtrl(camera_parameters=None)
camera.start()
root = tk.Tk()
root.protocol('WM_DELETE_WINDOW', closer)
root.title("Tau2 Livefeed")
root.option_add("*Font", "TkDefaultFont 14")
root.geometry(f"{HEIGHT_VIEWER}x{WIDTH_VIEWER}")
app = tk.Frame(root, bg='white')
app.grid()
lmain = tk.Label(app)
lmain.grid()
th_viewer()

root.mainloop()
