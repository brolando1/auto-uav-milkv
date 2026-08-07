# This code is implemented on the top of the crazyflie python library and enables easy logging for unlimited variables.
# Author: Vlad Niculescu, vladn@iis.ee.ethz.ch

from threading import Thread
import math
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie import Crazyflie
import cflib.crtp
from datetime import datetime
import time
import numpy as np


class CrazyFlieCommander(Thread):
    def __init__(self, cf, log_list, sampling_period, time0, filename):
        Thread.__init__(self)
        self.period = sampling_period
        self.data_log = np.array([])
        self.data_logging_en = False
        self.log_list = log_list
        self.text = " "
        self.cf = cf
        self.is_connected = cf.is_connected()
        self.start()
        self.t0 = time0
        self.filename = filename
        self.current_log = dict([])

    def run(self):
        self.logging()
        # self.config()

    def logging(self):
        N = len(self.log_list)
        logs_nr = math.ceil(N / 6.0)

        logs = []
        for i in range(logs_nr):
            logs.append(LogConfig(name="log" + str(i), period_in_ms=self.period))
        print("Logs added: ", logs_nr)

        for i in range(N):
            logs[i//6].add_variable(self.log_list[i], 'float')

        try:
            for i in range(logs_nr):
                current_log = logs[i]
                self.cf.log.add_config(current_log)
                # This callback will receive the data
                current_log.data_received_cb.add_callback(self._stab_log_data)
                # Start the logging
                current_log.start()
        except KeyError as e:
            print('Could not start log configuration,'
                  '{} not found in TOC'.format(str(e)))
        except AttributeError:
            print('Could not add Stabilizer log config, bad configuration.')

    def config(self):
        time.sleep(0.2)
        self.cf.param.set_value('stabilizer.estimator', '2')
        # self.cf.param.set_value('locSrv.extQuatStdDev', 0.05)
        # self.cf.param.set_value('stabilizer.controller', '2')
        self.cf.param.set_value('commander.enHighLevel', '1')
        print("CF configured!")
        print("Reset estimator")
        self.cf.param.set_value('kalman.resetEstimation', '1')
        time.sleep(0.1)
        self.cf.param.set_value('kalman.resetEstimation', '0')

    def _stab_log_data(self, timestamp, data, logconf):
        t1 = datetime.now()
        out = np.fromiter(data.values(), dtype=float).reshape(1, -1)
        names = list(data.keys())
        if self.data_logging_en:    
            timestamp = round(1000 * (datetime.now() - self.t0).total_seconds(), 3)
            for i in range(len(names)):
                self.log(timestamp, names[i], out[0, i])
                self.current_log[names[i]] = out[0, i]

    def send_extpose(self, cf, pos, quat):
        x = pos[0]
        y = pos[1]
        z = pos[2]
        qw = quat[0]
        qx = quat[1]
        qy = quat[2]
        qz = quat[3]

        # cf.extpos.send_extpose(x, y, z, qx, qy, qz, qw)
        cf.extpos.send_extpos(x, y, z)

    def log(self, timestamp, id_var, value):
        data_row = np.array([timestamp, id_var, value]).reshape(1, -1)
        if self.data_log.shape[0] == 0:
            self.data_log = data_row
        else:
            self.data_log = np.append(self.data_log, data_row, axis=0)

    def save_log(self):
        np.savetxt(self.filename + "_cf.csv", self.data_log, fmt='%s', delimiter=',')

    def logging_enabled(self, val):
        if val == 0:
            self.data_logging_en = False
        else:
            self.data_logging_en = True



