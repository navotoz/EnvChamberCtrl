from unittest import TestCase

import numpy as np

from devices.Camera.Tau2Grabber import TeaxGrabber


class TestTeaxGrabber(TestCase):
    def test_1_connect(self):
        self.camera = TeaxGrabber()

    def test_2_ffc(self):
        self.camera.ffc()

    def test_3_grab(self):
        image = self.camera.grab(to_temperature=False)
        self.assertEqual(image.dtype, np.uint16)

    def test_4_agc(self):
        self.camera.agc = 0x0001
        self.assertEqual( self.camera.agc , 0x0001)
        self.camera.agc = 0x0002
        self.assertEqual( self.camera.agc , 0x0002)

    def test_5_contrast(self):
        self.camera.contrast = 0x0001
        self.assertEqual( self.camera.contrast , 0x0001)
        self.camera.contrast = 0x0002
        self.assertEqual( self.camera.contrast , 0x0002)

    def test_6_contrast(self):
        self.camera.contrast = 0x0001
        self.assertEqual( self.camera.contrast , 0x0001)
        self.camera.contrast = 0x0002
        self.assertEqual( self.camera.contrast , 0x0002)

    def test_7_gain(self):
        self.camera.gain = 0x0001
        self.assertEqual( self.camera.gain , 0x0001)
        self.camera.gain = 0x0002
        self.assertEqual( self.camera.gain , 0x0002)

    def test_8_brightness(self):
        self.camera.brightness = 0x0001
        self.assertEqual( self.camera.brightness , 0x0001)
        self.camera.brightness = 0x0002
        self.assertEqual( self.camera.brightness , 0x0002)

    def test_9_ffc_mode(self):
        self.camera.ffc_mode = 0x0001
        self.assertEqual( self.camera.ffc_mode , 0x0001)
        self.camera.ffc_mode = 0x0002
        self.assertEqual( self.camera.ffc_mode , 0x0002)

    def test_10_brightness_bias(self):
        self.camera.brightness_bias = 0x0001
        self.assertEqual( self.camera.brightness_bias , 0x0001)
        self.camera.brightness_bias = 0x0002
        self.assertEqual( self.camera.brightness_bias , 0x0002)
