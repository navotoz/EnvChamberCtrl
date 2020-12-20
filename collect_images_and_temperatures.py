from threading import Thread
from time import sleep
import numpy as np
import utils.constants as const
from devices.Camera.Tau2Grabber import TeaxGrabber
from utils.tools import get_time, normalize_image


def thread_camera_temperatures(camera):
    def getter():
        for t_type in [const.T_FPA, const.T_HOUSING]:
            t = camera.get_inner_temperature()
            if t and t != -float('inf'):
                dict_variables[t_type] = int(t*100)

    while True:
        getter()
        sleep(const.FREQ_INNER_TEMPERATURE_SECONDS)


dict_variables = {}

camera = TeaxGrabber()

th_temperatures = Thread(target=thread_camera_temperatures, daemon=True, args=(camera,))
th_temperatures.start()
sleep(const.FREQ_INNER_TEMPERATURE_SECONDS)

while True:
    image = camera.grab(to_temperature=False)
    f_name = f'{get_time().strftime(const.FMT_TIME)}_'
    f_name += f"fpa_{dict_variables[const.T_FPA]:4d}_housing_{dict_variables[const.T_HOUSING]:4d}"
    np.save(f_name+'.npy', image)
    normalize_image(image).save(f_name + '.jpeg', format='jpeg')
    sleep(2)



