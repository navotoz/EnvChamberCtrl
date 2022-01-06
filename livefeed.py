import pyftdi.ftdi
from PIL import ImageTk

from devices.Camera.Tau.Tau2Grabber import Tau2Grabber
import tkinter as tk

from utils.misc import normalize_image

HEIGHT_VIEWER = int(2.5*336)
WIDTH_VIEWER = int(2.5*256)


def closer():
    try:
        camera.__del__()
    except (RuntimeError, ValueError, NameError, KeyError, TypeError, AttributeError):
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


def th_viewer():
    try:
        image = camera.grab()
    except (RuntimeError, ValueError, NameError, pyftdi.ftdi.FtdiError):
        return
    if image is not None:
        size_root = (root.winfo_height(), root.winfo_width())
        size_canvas = (lmain.winfo_height(), lmain.winfo_width())
        if size_canvas != size_root:
            lmain.config(width=root.winfo_width(), height=root.winfo_height())
        image_tk = ImageTk.PhotoImage(normalize_image(image).resize(reversed(size_canvas)))
        lmain.image_tk = image_tk
        lmain.configure(image=image_tk)
    lmain.after(ms=1000//30, func=th_viewer)


camera = Tau2Grabber()
camera.ffc_mode = 'auto'
if camera.ffc:
    print('FCC')
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
