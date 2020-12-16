from unittest import TestCase

import numpy as np

from devices.Camera.Tau2Grabber import TeaxGrabber
import devices.Camera.tau2_config as ptc

class TestTeaxGrabber(TestCase):
    def test_ffc(self):
        camera.ffc()

    def test_grab(self):
        image = camera.grab(to_temperature=False)
        self.assertEqual(image.dtype, np.uint16)

    def test_agc(self):
        camera.agc = ptc.AGC_CODE_DICT['linear']
        self.assertEqual( camera.agc , ptc.AGC_CODE_DICT['linear'])
        camera.agc = 'manual'
        self.assertEqual( camera.agc , ptc.AGC_CODE_DICT['manual'])

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
        camera.ffc_mode = ptc.FCC_MODE_CODE_DICT['auto']
        self.assertEqual( camera.ffc_mode , ptc.FCC_MODE_CODE_DICT['auto'])
        camera.ffc_mode = ptc.FCC_MODE_CODE_DICT['auto']
        self.assertEqual( camera.ffc_mode , ptc.FCC_MODE_CODE_DICT['auto'])

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

    def test_cmos_depth(self):
        camera.cmos_depth = 0x0001
        self.assertEqual( camera.cmos_depth , 0x0001)
        camera.cmos_depth = 0x0000
        self.assertEqual( camera.cmos_depth , 0x0000)


camera = TeaxGrabber()