# Every camera frame gets paired with the most recent ToF package.

import threading
from collections import deque


class Pairer:
    def __init__(self, maxlen=100):
        self._lock = threading.Lock()
        self._buffer = deque(maxlen=maxlen)
        self._current_tof = None

    def set_tof(self, package):
        with self._lock:
            self._current_tof = package

    def on_camera(self, img_decoded, jpeg_bytes=None, seq=None):
        with self._lock:
            tof = self._current_tof
            if img_decoded is None or tof is None:
                return
            self._buffer.append((img_decoded, tof['matrix'], tof['validity_matrix'], tof['metadata'], jpeg_bytes, seq))

    def latest(self):
        # newest pair or None, clears the buffer
        with self._lock:
            if len(self._buffer) == 0:
                return None
            pair = self._buffer[-1]
            self._buffer.clear()
            return pair
