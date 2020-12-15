import numpy as np
import usb.core
import usb.util
import struct
from usb.util import ENDPOINT_IN, ENDPOINT_OUT
from utils.tools import show_image

TIMEOUT_IN_NSEC = 1e9  # 1 seconds
MAGIC_IMAGE_ENDING = 0x0ff0


def make_header(endian:str):
    return struct.pack(endian + 26 * 'H',
    0xa5a5,
    0xa5a5,
    0xa5a5,
    0xa5d5,
    0x0000,
    0x0120,
    0x0180,
    0x0120,
    0x0180,
    0x0019,
    0x0000,
     0x075c,
    0x0b85,
    0x05f4,
    0x0800,
    0x0b85,
    0x0b85,
     0x0000,
    0x0570,
    0x0b85,
    0x0040,
    0x0000,
    0x0050,
    0x0003,
    0x0000,
    0x0fff    )


class Thermapp:
    def __init__(self, vid=0x1772, pid=0x0002):
        device = usb.core.find(idVendor=vid, idProduct=pid)
        if not device:
            raise RuntimeError

        if device.is_kernel_driver_active(0):
            device.detach_kernel_driver(0)

        device.reset()
        for cfg in device:
            for intf in cfg:
                if device.is_kernel_driver_active(intf.bInterfaceNumber):
                    try:
                        device.detach_kernel_driver(intf.bInterfaceNumber)
                    except usb.core.USBError as e:
                        print(f"Could not detach kernel driver from interface({intf.bInterfaceNumber}): {e}")
        device.set_configuration(1)
        usb.util.claim_interface(device, 0)
        endpoint = device[0][(0, 0)][0]

        header = make_header('<')
        device.write(endpoint=ENDPOINT_OUT | 2, data=header)
        in_val = struct.unpack(26 * 'H', header)
        f_string = ''
        for i in in_val:
            f_string += f'{i:5d} '
        print(f_string)



        # cup = np.load('with_cup.npy').astype('float32')
        # no_cup = np.load('without_cup.npy').astype('float32')
        #
        #
        # exit()



        while True:
            preabmle_bytes = struct.pack('HHHH', 0xa5a5, 0xa5a5, 0xa5a5, 0xa5d5)
            val = b''
            while (idx:=val.rfind(preabmle_bytes)) < 0:
                val += device.read(endpoint.bEndpointAddress, endpoint.wMaxPacketSize)

            val = val[idx:]
            while len(val) <= 64:
                val += device.read(endpoint.bEndpointAddress, endpoint.wMaxPacketSize)
            res = struct.unpack('<' + len(val) // 2 * 'H', val)
            serial_number  = np.array(res[5]).astype('uint32') | np.array(res[6] << 16).astype('uint32')
            height = res[11]
            width = res[12]
            image_id  = np.array(res[26]).astype('uint32') | np.array(res[27] << 16).astype('uint32')
            temperature = int(res[16])    # ????????
            # while (idx:=val.find(b'\xff\xff'))<0:
            while len(val) < 64 + 2 * width * height:
                val += device.read(endpoint.bEndpointAddress, endpoint.wMaxPacketSize)
            val = val[64:2 * width * height+64]
            raw_image_8bit = np.frombuffer(val, dtype='uint8').reshape(-1, 2 * width)
            image = 0x3FFF & raw_image_8bit.view('uint16')
            show_image(image)

        # np.save('without_cup.npy', image)
        # np.save('with_cup.npy', image)
        exit()


        val_out = np.array(struct.unpack('<' + len(val)//2 * 'H', val))
        val_out.reshape(-1, width)
        image = val_out[:height * width].reshape(height, width)

        f_string = ''
        for i in val:
            f_string += f'{i:5d} '
        print(f_string)
        a=1
