 
# Copyright 2020 LifeMech  Inc
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute, 
# sublicense, and/or sell copies of the Software, and to permit persons to whom the Software
# is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
# BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#


import logging
import time
from enum import Enum
from queue import PriorityQueue
from typing import List
from PyQt5.QtCore import pyqtSignal
from PyQt5 import QtCore
from threading import RLock

'''
  Encode the alarms in the enum in bit order according to v0.35
'''
class AlarmType(Enum):
    AC_POWER_LOSS = 0
    LOW_BATTERY  = 1
    BAD_PRESSURE_SENSOR = 2
    BAD_FLOW_SENSOR = 3
    ECU_COMMS_FAILURE = 4
    ECU_HARDWARE_FAILURE = 5
    ESTOP_PRESSED = 6
    HIGH_PRESSURE = 8
    LOW_PRESSURE = 9
    HIGH_VOLUME = 10
    LOW_VOLUME = 11
    HIGH_RESP_RATE = 12
    LOW_RESP_RATE = 13
    CONTINUOUS_PRESSURE = 14
    UI_COMMS_FAILURE = 16
    UI_HARDWARE_FAILURE = 17
    SETPOINT_MISMATCH = 24

class Alarm():
    messages : dict = {
        AlarmType.AC_POWER_LOSS: "AC Power is disconnected",
        AlarmType.LOW_BATTERY: "Battery reaches 20% or less",
        AlarmType.BAD_PRESSURE_SENSOR: "A problem has been detected in the pressure sensing circuit",
        AlarmType.BAD_FLOW_SENSOR: "A problem has been detected in the flow sensing circuit",
        AlarmType.ECU_COMMS_FAILURE: "Communications are too unreliable to operate",
        AlarmType.ECU_HARDWARE_FAILURE: "A hardware failure has been detected",
        AlarmType.ESTOP_PRESSED: "Emergency stop button has been pressed",
        AlarmType.HIGH_PRESSURE: "Pressure exceeded the high pressure limit",
        AlarmType.LOW_PRESSURE: "Pressure is below the low pressure limit",
        AlarmType.HIGH_VOLUME: "Volume IN detected exceeding the high volume limit",
        AlarmType.LOW_VOLUME: "Volume IN detected exceeding the low volume limit",
        AlarmType.HIGH_RESP_RATE: "Respiratory rate exceeded the high rate limit",
        AlarmType.LOW_RESP_RATE: "Respiratory rate below the low rate limit",
        AlarmType.CONTINUOUS_PRESSURE: "Pressure difference lower than 10cmH2O for more than 15s",
        AlarmType.UI_COMMS_FAILURE: "Communications are too unreliable to operate",
        AlarmType.UI_HARDWARE_FAILURE: "A hardware failure has been detected",
        AlarmType.SETPOINT_MISMATCH: "One or more setpoints does not match between UI and ECU"
    }

    def __init__(self, alarm_type: AlarmType):
        self.time = time.time()
        self.alarm_type = alarm_type

    def get_message(self) -> str:
        return self.messages.get(self.alarm_type, "")

    def __lt__(self, other):
        return self.time < other.time
    
    def __eq__(self, other):
        if self.time == other.time and self.alarm_type == other.alarm_type:
            return True
        return False

    def isSamePrior(self, other):
        if self.alarm_type == other.alarm_type:
            return True
        return False

class AlarmQueue(List): 
    priorities : dict = {
        AlarmType.AC_POWER_LOSS: 0,
        AlarmType.LOW_BATTERY : 1,
        AlarmType.BAD_PRESSURE_SENSOR: 2,
        AlarmType.BAD_FLOW_SENSOR: 3,
        AlarmType.ECU_COMMS_FAILURE: 4,
        AlarmType.ECU_HARDWARE_FAILURE: 5,
        AlarmType.ESTOP_PRESSED: 6,
        AlarmType.HIGH_PRESSURE: 7,
        AlarmType.LOW_PRESSURE: 8,
        AlarmType.CONTINUOUS_PRESSURE: 9,
        AlarmType.HIGH_VOLUME: 10,
        AlarmType.LOW_VOLUME: 11,
        AlarmType.HIGH_RESP_RATE: 12,
        AlarmType.LOW_RESP_RATE: 13,
        AlarmType.UI_COMMS_FAILURE: 14,
        AlarmType.UI_HARDWARE_FAILURE: 15,
        AlarmType.SETPOINT_MISMATCH: 16,
    }

    def __init__(self) -> None:
        super().__init__()
 
    
    def alarm_type_in_queue(self, alarm_type: AlarmType) -> bool:
        for item in self:
            if item[1].alarm_type == alarm_type:
                return True
        return False

    def put(self, alarm: Alarm):
        priority = self.priorities.get(alarm.alarm_type)
        super().append((priority, alarm))
        super().sort()

    def peek(self) -> Alarm:
        if len(self) > 0:
            tup = self[0]
            return tup[1]
        else:
            return None

    def get(self) -> Alarm:
        tup = super().get()
        return tup[1]

    def index(self, alarm) -> int:
        priority = self.priorities.get(alarm.alarm_type)
        return super().index((priority, alarm))

    def remove(self, alarm):
        priority = self.priorities.get(alarm.alarm_type)
        super().remove((priority, alarm))

    def num_pending(self) -> int:
        return len(self)
        
class AlarmHandler(QtCore.QObject):
    acknowledge_alarm_signal = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger()
        self._active_alarmbits = 0
        self._ack_alarmbits = 0
        self._alarm_queue = AlarmQueue()
        self._lock = RLock()
        

    '''
     This function should be connected to a signal emitted
     by the comms handler when alarm bits are received
    '''
    def set_active_alarms(self, alarmbits: int) -> None:
        self.logger.debug("Got alarm signal " + str(bin(alarmbits)))
        self._lock.acquire()
    
        self._active_alarmbits = alarmbits
 
        # Zero the ack bits that are no longer active
        self._ack_alarmbits &= self._active_alarmbits
 
        # Iterate through the bits and set all active alarms
        # If we've already acked the alarm, do not put another
        # copy into the queue
        ackbits = self._ack_alarmbits
        pos = 0
        while (pos < 32):
            alarmbit = alarmbits & 1
            ackbit = ackbits & 1
            if alarmbit == 1 and ackbit == 0:
                try:
                    alarmtype = AlarmType(pos)
                    self._set_alarm(alarmtype)
                except ValueError:
                    self.logger.debug("Got invalid alarm bit at pos " + str(pos))
            alarmbits = alarmbits >> 1
            ackbits = ackbits >> 1
            pos += 1
      
        self._lock.release()
    
    '''
      This function is called by the UI to retrieve highest
      priority unacknowledged alarm
    '''
    def get_highest_priority_alarm(self) -> Alarm:
        self._lock.acquire()
        alarm = self._alarm_queue.peek()
        self._lock.release()
        return alarm

    '''
     This function should be called by the UI when it
     acknowledges the current alarm.  
    '''
    def acknowledge_alarm(self, alarm) -> None:
        self._lock.acquire()
        try:
            # Make sure the alarm is in the queue
            self._alarm_queue.index(alarm)
            self._alarm_queue.remove(alarm)
            alarmbit = alarm.alarm_type.value
            self._ack_alarmbits |= 1 << alarmbit
            self.acknowledge_alarm_signal.emit(self._ack_alarmbits)
        except:
            self.logger.debug("Error acknowledging alarm: " + str(alarm))
       
        self._lock.release()
        

    def alarms_pending(self) -> int:
        self._lock.acquire()
        num_pending = self._alarm_queue.num_pending()
        self._lock.release()
        return num_pending


    def _set_alarm(self, alarm_type: AlarmType) -> None:
        self._lock.acquire()
        alarm = Alarm(alarm_type)
        #  If the alarm is already in the queue, do nothing
        if not self._alarm_queue.alarm_type_in_queue(alarm.alarm_type):
            self._alarm_queue.put(alarm)
        self._lock.release()

