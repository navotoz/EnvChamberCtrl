from unittest import TestCase

import numpy as np

from devices.Camera.Tau2Grabber import TeaxGrabber


class TestTeaxGrabber(TestCase):
    def test_1_open_close(self):
        camera = TeaxGrabber()
        self.assertIsNotNone(camera.__dev, msg="ThermalGrabber not connected, skipping tests")
        camera.close()

    def test_2_ping(self):
        with TeaxGrabber() as camera:
            res = camera.ping()
            self.assertIsNotNone(res, 'Ping failed.')

    def test_3_grab(self):
        with TeaxGrabber() as camera:
            image = camera.grab()
            self.assertEqual(image.dtype, np.float64)

    def test_4_grab_raw(self):
        with TeaxGrabber() as camera:
            image = camera.grab(to_temperature=False)
            self.assertEqual(image.dtype, np.uint16)

    def test_5_image_and_uart(self):
        with TeaxGrabber() as camera:
            temp = camera.get_fpa_temperature()
            self.assertLess(0, temp, msg=f'Sensor temperature {temp} is false.')

            image = camera.grab()
            self.assertEqual(image.dtype, np.float64)
