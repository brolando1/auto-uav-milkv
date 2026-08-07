import numpy as np

class Logger:
    def __init__(self, n, m):
        self.n = n
        self.m = m
        self.data = np.array([])

    def add(self, measurement):
        if len(self.data) == 0:
            self.data = measurement.reshape(-1, self.n, self.m)
        else:
            self.data = np.append(self.data, measurement.reshape(-1, self.n, self.m), axis=0)

    def getSize(self):
        return np.shape(self.data)

    def saveLog(self, log_name):
        np.save(log_name + "_tof.npy", self.data)
