# Same pairing rule as logger/camera_tof_pairing.py: every camera frame gets
# matched with the most recent ToF package. Kept as a class here so the Duo S
# node doesn't have to import the logger package (which drags in cv2 windows).

import threading
import time
from collections import deque


class Pairer:
    def __init__(self, maxlen=100):
        self._lock = threading.Lock()
        self._buffer = deque(maxlen=maxlen)
        self._current_tof = None
        self.last_t_mon = None   # monotonic arrival time of the pair latest() returned

    def set_tof(self, package):
        with self._lock:
            self._current_tof = package

    def on_camera(self, img_decoded, jpeg_bytes=None, seq=None):
        with self._lock:
            tof = self._current_tof
            if img_decoded is None or tof is None:
                return
            self._buffer.append(((img_decoded, tof['matrix'], tof['validity_matrix'], tof['metadata'], jpeg_bytes, seq),
                                 time.monotonic()))

    def latest(self):
        # newest pair or None; clears the buffer like the viewer/control loop do
        with self._lock:
            if len(self._buffer) == 0:
                return None
            pair, self.last_t_mon = self._buffer[-1]
            self._buffer.clear()
            return pair
