from pathlib import Path
from constants import *


def make_oven_basic_prog(path: Path = Path.cwd()):
    prog = f"""
Const PORT_MAIN = 1
Const PORT_VENTILATION  = 2
Const PORT_LAMP = 3
Const PORT_LOW_VOLT  = 5
Const PORT_MID_VOLT  = 6
Const PORT_HIGH_VOLT  = 7
Const PORT_VOLT  = 8
Const PORT_CTRL_ENABLE = 9

Const PID_FREQ_SEC = {PID_FREQ_SEC}
Const N_SENSORS_CAMERA = 4
Const kp = {Kp}
Const ki = {Ki}
Const kd = {Kd}  ' penalizes high rate of change

Const MULT = 1.0
Const OFFSET = 0.0
Const F_N1 = 50
Const SECONDS = Sec

'--- Error bounds for different Power levels ---
Const LOW_VOLT_LIMIT = {LOW_VOLT_LIMIT}
Const MID_VOLT_LIMIT = {MID_VOLT_LIMIT}
Const HIGH_VOLT_LIMIT = {HIGH_VOLT_LIMIT}

Const LOWEST_CTRL_BOUND = 0.0
Const HIGHEST_CTRL_BOUND = 50.0  ' the bound aim to make plotting look good

Public PTemp, VoltBattery, {T_FLOOR}, {T_INSULATION}
Public T_ceiling, T_out, {T_CAMERA}
Public {SETPOINT}, {SIGNALERROR}, sumErr, dInput, inputSignal
Public {SIGNALERROR}Kp, sumErrKi, dInputKd
Public {CTRLSIGNAL}, prevInput,  Ventilation, Lamp, flag(9)

Function CheckIfValInBounds(signal, low, high)
    If signal >= low AND signal < high Then
        Return True
    Else
        Return False
    EndIf
EndFunction
    
Function Clip(signal, low, high)
    If signal > high Then Return high
    If signal < low Then Return low
    Return signal
EndFunction

Function SetPortVolt()
    If flag(PORT_LOW_VOLT) OR flag(PORT_MID_VOLT) OR flag(PORT_HIGH_VOLT) Then
        flag(PORT_VOLT) = True
        PortSet (PORT_VOLT, 1)
    Else
        flag(PORT_VOLT) = False
        PortSet (PORT_VOLT, 0)
    EndIf
EndFunction

Sub SetMainPort(condition)
    If condition <> 0 Then
        If flag(PORT_MAIN) = False Then
            PortSet (PORT_MAIN, 1)
            flag(PORT_MAIN) = True
            PortSet (PORT_CTRL_ENABLE,1)
            flag(PORT_CTRL_ENABLE) = True
        EndIf
    Else
        PortSet (PORT_MAIN, 0)
        flag(PORT_MAIN) = False
        PortSet (PORT_CTRL_ENABLE,0)
        flag(PORT_CTRL_ENABLE) = False
    EndIf
EndSub

DataTable ({OVEN_TABLE_NAME},1,1000)
    DataInterval (0,{OVEN_LOG_TIME_SECONDS},SECONDS,10)
    Average (1,{T_FLOOR},FP2,False)
    Average (1,{T_INSULATION},FP2,False)
    Average (1,{T_CAMERA},   FP2,False)
    Average (1,{CTRLSIGNAL}, FP2,False)
    Average (1,dInputKd, FP2,False)
    Average (1,sumErrKi, FP2,False)
    Average (1,{SIGNALERROR}Kp, FP2,False)
    Average (1,dInput, FP2,False)
    Average (1,sumErr, FP2,False)
    Average (1,{SIGNALERROR}, FP2,False)
    Sample  (1,{SETPOINT},   FP2)
EndTable

DataTable ({PID_SIGNAL_AVG},1,PID_FREQ_SEC)
    DataInterval (0,PID_FREQ_SEC,SECONDS,PID_FREQ_SEC)  ' ring buffer of length PID_FREQ_SEC
    Average(1,{T_FLOOR},FP2,False)
    Average(1,{SIGNALERROR},FP2,False)
EndTable

SequentialMode
BeginProg
    Scan (1,SECONDS,3,0)  ' endless loop every 1 sec
    Battery (VoltBattery)  ' battery temp of CR1000
    PanelTemp (PTemp, F_N1) ' inner temp of CR1000
    
    '--- T-thermocapel uses inner CR temp for ref ---
    TCDiff ({T_FLOOR}, 1,AutorangeC,1,TypeT,PTemp,True,0,F_N1,MULT,OFFSET)  ' Is this the correct way to use a buffer?
    TCDiff ({T_INSULATION},  1,AutorangeC,2,TypeT,PTemp,True,0,F_N1,MULT,OFFSET)
    TCDiff ({T_CAMERA},1,AutorangeC,3,TypeT,PTemp,True,0,F_N1,MULT,OFFSET)
    
    '--- Guards against over-heating ---
    If {T_FLOOR}<{MAX_FLOOR_TEMPERATURE} Then
        SetMainPort({SETPOINT})
    Else
        SetMainPort(0)
    EndIf
    
    '---  Calculate error in regards to T_floor ---
    inputSignal = {PID_SIGNAL_AVG}.{T_FLOOR}_Avg
    
    '--- p ---
    {SIGNALERROR} = {SETPOINT} - inputSignal
    {SIGNALERROR}Kp = {SIGNALERROR} * kp
    {SIGNALERROR}Kp = Clip({SIGNALERROR}Kp, 0, {MAX_FLOOR_TEMPERATURE})  ' when negative, only prevents the heating element
    '--- i ---
    sumErr = PID_FREQ_SEC * {PID_SIGNAL_AVG}.{SIGNALERROR}_Avg
    sumErrKi = sumErr * ki
    
    '--- d ---
    If TimeIntoInterval(0, PID_FREQ_SEC, SECONDS) Then
        dInput = prevInput - {PID_SIGNAL_AVG}.{T_FLOOR}_Avg
        dInputKd = dInput * kd
        prevInput = {PID_SIGNAL_AVG}.{T_FLOOR}_Avg ' only update prevInput once every PID_FREQ iterations
    EndIf
    
    '--- PID control signal ---
    {CTRLSIGNAL} = {SIGNALERROR}Kp
    {CTRLSIGNAL} += sumErrKi
    {CTRLSIGNAL} += dInputKd
    
    '--- Clip {CTRLSIGNAL} ---
    {CTRLSIGNAL} = Clip({CTRLSIGNAL}, LOWEST_CTRL_BOUND, HIGHEST_CTRL_BOUND)
    
    '--- control  ---
    PortsConfig (&B00111111,&B00111111)
    
    flag(PORT_LOW_VOLT) =	CheckIfValInBounds({CTRLSIGNAL}, LOW_VOLT_LIMIT, MID_VOLT_LIMIT)
    If flag(PORT_LOW_VOLT) Then
        PortSet (PORT_LOW_VOLT, 1)
    Else
        PortSet (PORT_LOW_VOLT, 0)
    EndIf
    
    flag(PORT_MID_VOLT) =	CheckIfValInBounds({CTRLSIGNAL}, MID_VOLT_LIMIT, HIGH_VOLT_LIMIT)
    If flag(PORT_MID_VOLT) Then
        PortSet (PORT_MID_VOLT, 1)
    Else
        PortSet (PORT_MID_VOLT, 0)
    EndIf
    
    flag(PORT_HIGH_VOLT) =	CheckIfValInBounds({CTRLSIGNAL}, HIGH_VOLT_LIMIT, HIGHEST_CTRL_BOUND+1)
    If flag(PORT_HIGH_VOLT) Then
        PortSet (PORT_HIGH_VOLT, 1)
    Else
        PortSet (PORT_HIGH_VOLT, 0)
    EndIf
    
    SetPortVolt()
    
    If flag(PORT_VENTILATION) Then
        PortSet (PORT_VENTILATION, 1)
        Ventilation=1
    Else
        PortSet (PORT_VENTILATION, 0)
        Ventilation=0
    EndIf
    
    If flag(PORT_LAMP) Then
        PortSet (PORT_LAMP, 1)
        Lamp=1
    Else
        PortSet (PORT_LAMP, 0)
        Lamp=0
    EndIf
    
    CallTable({OVEN_TABLE_NAME})
    CallTable({PID_SIGNAL_AVG})
    NextScan
    EndSequence
EndProg
"""

    with open(path / 'ovenCtrl_CRbasic.CR1', 'w') as fp:
        fp.write(prog)


make_oven_basic_prog()