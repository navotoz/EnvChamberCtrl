# Environment Chamber Ctrl module #
## Introduction ##
The environment chamber is composed of **Six** modules:
- Oven - controlled via the Campbell controller.
- Camera TAU2 - connected to the PC via USB.
- Black Body - connected to the PC via Ethernet cable 
(The PC has two networking cards, thus allowing both the BB and the ARO network to work simultaneously)
- Focus Stage - a _Nanomotion inc._ stage, connected to a re-worked lens, that can change the focus of the camera.
- Scanning Mirror - _Arduino_ connected to a mirror via a stepper motor, to allow for wider photography angles.
- PC - connected to all of the above and running on Linux, 
and controlling all devices via a GUI written with python 3.8.

## Installation ##
#### Requirements ####
The server is run using python 3.8 with requirements detailed in requirements.txt.

#### Installation ####
1. Install Python with pip support, preferably using Anaconda package manager.
1. Create a virtual environment and install the requirements file using `python -m pip install -r requirements.txt`
1. Follow the next steps:
    1. Open the terminal (`Ctrl+D`)
    1. Write `sudo su` and enter the computer's root password.
    1. Write:
    `echo "SUBSYSTEM==\"usb\", ACTION==\"add\", ATTRS{idVendor}==\"0403\", ATTRS{idProduct}==\"6010\",  MODE=\"0666\"">/etc/udev/rules.d/99-taucamera.rules`
    1. Write:
    `sudo usermod -a -G dialout $USER`
    1. Write:
    `echo "SUBSYSTEM==\"usb\", ACTION==\"add\", ATTRS{idVendor}==\"067B\", ATTRS{idProduct}==\"2303\",  MODE=\"0666\"">/etc/udev/rules.d/99-nanomotionstage.rules`
    1. Write:
    `echo "SUBSYSTEM==\"usb\", ACTION==\"add\", ATTRS{idVendor}==\"1772\", ATTRS{idProduct}==\"0002\",  MODE=\"0666\"">/etc/udev/rules.d/99-thermapp.rules`
    1. If 1-5 doesn't work, check which USB the device is connected to via `lsusb` and write in terminal:
        `sudo chmod 666 #` Where # is the correct device address.
    1. **Reboot**
1. Install TkInter `sudo apt-get install python3-tk`
1. The IP of the BlackBody can be found on the controller of the BB in "Menu"->"About".
It is connected via ethernet to the secondary network card on the PC.
In order to use the BlackBody, both it and the PC should be on the same network *domain*, meaning that PC address should look like 
`[BlackBody].[BlackBody].[BlackBody].[DIFFERENT THAN THE BLACKBODY]`
The same digits for the first three blocks in the IP, and the last block **different** than the BlackBody.
Currently the Blackbody address is `10.26.91.56`, so set the IP of the PC to `10.26.91.55`.
1. The oven is controlled via *Loggernet*, a proprietary software by *Campbell scientific*.
Install **VirtualBox**, **VirtualBox Extension Pack** and load the image **win10_loggernet**.
These are all found in the Devices->Campbell->VirtualBoxInstallation
1. Enter in the terminal `sudo usermod -a -G vboxusers $USER`
1. Enter in the terminal `sudo usermod -a -G dialout $USER` (if you had not done so already)
1. Reboot.
1. Make sure the oven is connected to the electricity, the Campbell controller is ON and the USB2Serial is connected to the PC.
1. Make sure the ON switch on the front of the oven is ON, and the red light shines.
1. After starting the WIN10 VM, make sure there is a 'V' next to the USB2SERIAL name in the options of the VM.
1. Inside the WIN10 VM, check the COM port of the USB2SERIAL.
1. On the Loggernet->Setup make sure the COM port is the same as on the *device manager*.
1. **Important notice** - when the USB2SERIAL 'V' in the VM options is activated, the oven **CANNOT** be accessed from Python. 


## Usage ##
#### Test mode ####
Each device in the GUI window has a radiobox with "Real", "Dummy" and "Off" labels.
- To use a dummy move the radiobox to "Dummy".
- To prevent the use of the device, move the radiobox to "Off".
 
#### Take a photo ####
1. Connect the *Blackbody* to the secondary network card. Make sure all IP configs are on-par with step (4) in the setup.
 Turn it on.
1. Connect the *Camera* *Tau2 336* to the USB socket.
1. Run `main.py`.
1. Set which type of devices to use - either 'dummy', 'off' or 'real' if connected.
1. Set the experiment save directory with "Browse".
1. Parameters for un-detected of 'off' devices will be grayed-out.
1. The livefeed from the camera can be seen in "Viewer".
1. Previously taken images can be watched in "Upload".
1. To set a temperature for the oven:
    1. Start the Win10 VM, and LoggerNet.
    1. Turn on the controller and the oven itself.
    1. Connect the controller to the PC via the USB2SERIAL cable.
    1. Make sure there is a 'V' on the VM options for the USB2SERIAL.
    1. In the "Connect" screen of LoggerNet, press "connect".
    1. Set the **setPoint** in the *NumDisplay* to the desired temperature.
    1. **Notice** that the switch on the front of the oven must be ON to enable the heating.
    1. Wait for the settling of the temperatures.
1. Set the number of minimal minutes to wait between consecutive experiments on the top-left corner.
1. Press "Start".
1. After pressing "Start" you will be prompted to set a mask for the output. The mask will be created in the experiment folder.
1. A progress bar is updated throughout the experiment.


#### Photo name parse ####
The FPA and Housing temperatures are acquired from the internal camera sensors.
```
YYYYMMDD_hHHmMMsSS_<device name>_<device value>_..._fpa_<FPA temperature>_housing_<Housing temperature>_<number of image>of<total number of images for this combination>.npy
mask.npy
```
