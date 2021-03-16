FAILURE_PROBABILITY_FOR_DUMMIES = .00
PLOTS_PATH = 'plots'
FMT_TIME = "%Y%m%d_h%Hm%Ms%S"

# PID parameters
Kp = 1.0
Ki = 3.0
Kd = 500.0
LOW_VOLT_LIMIT = 1  # the time constant of the LOW_VOLT is around 30minutes/Degree
MID_VOLT_LIMIT = 3  # keep distance between LOW, MID, HIGH > 1
HIGH_VOLT_LIMIT = 40
OVEN_LOG_TIME_SECONDS = 30
MAX_FLOOR_TEMPERATURE = 120.0
PID_FREQ_SEC = 10
OVEN_RECORDS_FILENAME = 'oven_records.csv'
PAKBUS_HEADER_LENGTH = 8
MAX_TEMPERATURE_LINEAR_RISE = 75

# CRBasic terms
OVEN_TABLE_NAME = 'recordData'
PID_SIGNAL_AVG = 'inputAvg'
T_FLOOR = 'T_floor'
SIGNALERROR = 'signalErr'
CTRLSIGNAL = 'ctrlSignal'
T_INSULATION = 'T_insulation'
SETPOINT = 'setPoint'
DATETIME = 'Datetime'
T_FPA = 'fpa'
T_HOUSING = 'housing'
T_CAMERA = 'T_camera'  # thermo-caple attached to the camera inside the oven

# dimensions
HEIGHT_VIEWER = 400
WIDTH_VIEWER = 400
HEIGHT_IMAGE_TAU2 = 256
WIDTH_IMAGE_TAU2 = 336

# devices dict entries
CAMERA_NAME = "camera"
BLACKBODY_NAME = "blackbody"
FOCUS_NAME = "focus"
SCANNER_NAME = "scanner"
OVEN_NAME = "oven"
DEVICE_NAMES = [CAMERA_NAME, BLACKBODY_NAME, FOCUS_NAME, SCANNER_NAME, OVEN_NAME]

# gui
MIN_STRING = " min"
MAX_STRING = " max"
INC_STRING = " increment"
INIT_MIN = "init min"
INIT_MAX = "init max"
INIT_INC = "init increment"
SP_PREFIX = 'sp '
ITERATIONS_IN_TEMPERATURE = 'iterations_in_each_temperature'
ITERATIONS_IN_TEMPERATURE_INIT_VAL = 2
SETTLING_TIME_MINUTES = 'settling_time_minutes'
SETTLING_TIME_MINUTES_INIT_VAL = 3
DELTA_TEMPERATURE = 'delta_temperature'
# large delta means that the system is only relevant for INCREASING temperatures,
# because only the max temperature condition can be true
DELTA_TEMPERATURE_INIT_VAL = 8e-2
USE_CAM_INNER_TEMPS = 'use_cam_inner_temps'
USE_CAM_INNER_TEMPS_INIT_VAL = '1'
RESOLUTION_STRING = " resolution"
IMAGES_TO_RUN_LABEL = 'images_to_run'
EXPERIMENT_SAVE_PATH = 'experiment_save_path'
FREQ_INNER_TEMPERATURE_SECONDS = 2

# rate of climb for the camera is approx. 1C / 8.5min ~= 0.12C / 1min ~= 8.3min / 1C
# rate of climb for the floor is approx. 10C / 9min ~= 1C / 1min ~= 1min / 1C
# rate of decay for the floor is approx. 3C / 6.5min ~= 0.46C / 1min ~= 2.17min / 1C
# for the settling time of the floor and the camera to be equal:
# max temperature of floor above desired camera temperature = 2.3 * desired temperature of the camera
DELAY_FLOOR2CAMERA_CONST = 2.3

# holds limits and resolutions of all peripherals
LIMIT_DICT = {OVEN_NAME: {MIN_STRING: 20, MAX_STRING: 90, RESOLUTION_STRING: 1,
                          INIT_MIN: 20, INIT_MAX: 50, INIT_INC: 5},  # [Celsius]
              BLACKBODY_NAME: {MIN_STRING: 10., MAX_STRING: 70., RESOLUTION_STRING: .01,
                               INIT_MIN: 20.0, INIT_MAX: 50.0, INIT_INC: 5.0},  # [Celsius]
              CAMERA_NAME: {MIN_STRING: 1, MAX_STRING: 5000, RESOLUTION_STRING: 1,
                            INIT_INC: 50},  # [number of images]
              SCANNER_NAME: {MIN_STRING: 0., MAX_STRING: 180., RESOLUTION_STRING: 0.01},  # [Degrees]
              FOCUS_NAME: {MIN_STRING: 0., MAX_STRING: 12., RESOLUTION_STRING: 0.01}}  # [mm]
METRICS_DICT = {OVEN_NAME: 'C',
                FOCUS_NAME: 'mm',
                SCANNER_NAME: 'deg',
                BLACKBODY_NAME: 'C'}
INIT_VALUES = {}

# statuses/msg types:
OFF = -float('inf')
READY = "READY"
WORKING = "WORKING"

# widgets names
EXPERIMENT_NAME = 'exp_name'

# status color dict:
STATUS_COLORS = {READY: '#245e22', "ERROR": '#ed0c0c', "STANDBY": 'white', WORKING: '#ff9323'}

# button names
BUTTON_BROWSE = 'btn_browse'
BUTTON_STOP = 'btn_stop'
BUTTON_START = 'btn_start'
BUTTON_VIEWER = 'btn_viewer'
BUTTON_UPLOAD = 'btn_upload'
BUTTON_OVEN_PROG = 'btn_make_oven_program'
BUTTON_PLOT = 'btn_plot'

# frame names
FRAME_HEAD = 'frame_head'
FRAME_PARAMS = 'frame_parameters'
FRAME_TEMPERATURES = 'frame_temperatures'
FRAME_BUTTONS = 'frame_buttons'
FRAME_PATH = 'frame_path'
FRAME_STATUS = 'frame_status'
FRAME_PROGRESSBAR = 'frame_progressbar'
PROGRESSBAR = 'progressbar'
FRAME_TERMINAL = 'frame_text'

# device status
DEVICE_OFF = 0
DEVICE_DUMMY = 10
DEVICE_REAL = 100

# camera status
CAMERA_TAU = 20
CAMERA_THERMAPP = 30

# plots
TEMPERATURE_LABEL = 'Temperature [$C^\circ$]'

INIT_CAMERA_PARAMETERS = dict(
    ffc_mode='manual',
    isotherm=0x0000,
    dde=0x0000,
    tlinear=0x0000,
    gain='high',
    agc='manual',
    sso=0,
    contrast=0,
    brightness=0,
    brightness_bias=0,
    lvds=0x0000,  # disabled
    lvds_depth=0x0000,  # 14bit
    xp=0x0002,  # 14bit w/ 1 discrete
    cmos_depth=0x0000,  # 14bit pre AGC
    # corr_mask=0  # off
)
