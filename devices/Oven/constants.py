# PID parameters
Kp = 1.0
Ki = 3.0
Kd = 500.0
LOW_VOLT_LIMIT = 1  # the time constant of the LOW_VOLT is around 30minutes/Degree
MID_VOLT_LIMIT = 3  # keep distance between LOW, MID, HIGH > 1
HIGH_VOLT_LIMIT = 40
MAX_FLOOR_TEMPERATURE = 120.0
PID_FREQ_SEC = 10
OVEN_LOG_TIME_SECONDS = 30
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
T_BLACKBODY = 'T_blackbody'
T_CAMERA = 'T_camera'  # thermo-caple attached to the camera inside the oven
DELAY_FLOOR2CAMERA_CONST = 1.5
