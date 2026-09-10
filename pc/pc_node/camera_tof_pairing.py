# Camera/ToF pairing seam on the PC (same rule as duos_node/pairing.py: every
# camera frame is matched with the most recent ToF frame). The link client
# stores each relayed ToF package in current_tof_package and calls
# frame_pairing() for each relayed jpeg; the viewer takes the newest
# (camera, tof_mm, tof_metadata) triple from paired_buffer.

import threading
from collections import deque

paired_buffer = deque(maxlen=100)
buffer_lock = threading.Lock()
current_tof_package = None


def frame_pairing(img_decoded):
    tof_package = current_tof_package
    if tof_package is None:
        return
    if img_decoded is None:
        print("[PAIRING] img is None")
        return
    with buffer_lock:
        paired_buffer.append((img_decoded, tof_package['matrix'], tof_package['metadata']))
