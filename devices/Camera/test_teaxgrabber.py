from unittest import TestCase

import numpy as np

from devices.Camera.Tau2Grabber import TeaxGrabber


class TestTeaxGrabber(TestCase):
    def test_ffc(self):
        camera.ffc()

    def test_grab(self):
        image = camera.grab(to_temperature=False)
        self.assertEqual(image.dtype, np.uint16)

    def test_agc(self):
        camera.agc = 0x0001
        self.assertEqual( camera.agc , 0x0001)
        camera.agc = 0x0002
        self.assertEqual( camera.agc , 0x0002)

    def test_contrast(self):
        camera.contrast = 0x0001
        self.assertEqual( camera.contrast , 0x0001)
        camera.contrast = 0x0002
        self.assertEqual( camera.contrast , 0x0002)

    def test_gain(self):
        camera.gain = 0x0001
        self.assertEqual( camera.gain , 0x0001)
        camera.gain = 0x0002
        self.assertEqual( camera.gain , 0x0002)

    def test_brightness(self):
        camera.brightness = 0x0001
        self.assertEqual( camera.brightness , 0x0001)
        camera.brightness = 0x0002
        self.assertEqual( camera.brightness , 0x0002)

    def test_ffc_mode(self):
        camera.ffc_mode = 0x0001
        self.assertEqual( camera.ffc_mode , 0x0001)
        camera.ffc_mode = 0x0002
        self.assertEqual( camera.ffc_mode , 0x0002)

    def test_brightness_bias(self):
        camera.brightness_bias = 0x0001
        self.assertEqual( camera.brightness_bias , 0x0001)
        camera.brightness_bias = 0x0002
        self.assertEqual( camera.brightness_bias , 0x0002)

    def test_sso(self):
        camera.sso = 0x0001
        self.assertEqual( camera.sso , 0x0001)
        camera.sso = 0x0002
        self.assertEqual( camera.sso , 0x0002)

    def test_isotherm(self):
        camera.isotherm = 0x0000
        self.assertEqual( camera.isotherm , 0x0000)
        camera.isotherm = 0x0001
        self.assertEqual( camera.isotherm , 0x0001)

    def test_dde(self):
        camera.dde = 0x0000
        self.assertEqual( camera.dde , 0x0000)
        camera.dde = 0x0001
        self.assertEqual( camera.dde , 0x0001)

    def test_tlinear(self):
        camera.tlinear = 0x0000
        self.assertEqual( camera.tlinear , 0x0000)
        camera.tlinear = 0x0001
        self.assertEqual( camera.tlinear , 0x0001)

    def test_lvds_mode(self):
        camera.lvds = 0x0000
        self.assertEqual( camera.lvds , 0x0000)
        camera.lvds = 0x0001
        self.assertEqual( camera.lvds , 0x0001)

    def test_lvds_depth(self):
        camera.lvds_depth = 0x0001
        self.assertEqual( camera.lvds_depth , 0x0001)
        camera.lvds_depth = 0x0000
        self.assertEqual( camera.lvds_depth , 0x0000)

    def test_xp(self):
        camera.xp = 0x0000
        self.assertEqual( camera.xp , 0x0000)
        camera.xp = 0x0001
        self.assertEqual( camera.xp , 0x0001)

    def test_cmos_depth(self):
        camera.cmos_depth = 0x0001
        self.assertEqual( camera.cmos_depth , 0x0001)
        camera.cmos_depth = 0x0000
        self.assertEqual( camera.cmos_depth , 0x0000)


camera = TeaxGrabber()