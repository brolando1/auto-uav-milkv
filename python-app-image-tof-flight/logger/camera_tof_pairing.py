import numpy as np
import logger.crazyflie_manager as cfm
import os
from collections import deque
import threading

MAX_FRAMES = 270
saved_filenames = deque()
paired_buffer = deque(maxlen=100)
buffer_lock = threading.Lock()
control_pair_buffer = deque(maxlen = 100)
control_pair_buffer_lock = threading.Lock()


def save_frame_pair(filename, savematrix, nparr):
    if (nparr is None):
        return
    
    cam_path = f"/home/phheld/project/tof-camera-logger/python-app-image-tof-logger/logger/data/camera_frames/"
    tof_path = f"/home/phheld/project/tof-camera-logger/python-app-image-tof-logger/logger/data/tof_frames/"

    cfm.tof_lock.acquire()

    np.save(cam_path + 'cam'+ str(filename) + '.npy', nparr)
    np.save(tof_path + 'tof' + str(filename) + '.npy', savematrix)

    saved_filenames.append(filename)

    if len(saved_filenames) > MAX_FRAMES:

        oldest_filename = saved_filenames.popleft()
        old_cam_path = f"{cam_path}cam{oldest_filename}.npy"
        old_tof_path = f"{tof_path}tof{oldest_filename}.npy"

        if os.path.exists(old_cam_path):
            os.remove(old_cam_path)
        if os.path.exists(old_tof_path):
            os.remove(old_tof_path)

    cfm.tof_lock.release()

def frame_pairing(img_decoded):

     if cfm.current_tof_package is None:
         return
     
     tof = cfm.current_tof_package['matrix']
     tof_validity = cfm.current_tof_package['validity_matrix']
     meta = cfm.current_tof_package['metadata']

     if img_decoded is not None and tof is not None and tof_validity is not None:
         with buffer_lock:
             paired_buffer.append((img_decoded, tof, meta))
         with control_pair_buffer_lock:
             control_pair_buffer.append((img_decoded, tof, tof_validity))
     if img_decoded is None:
         print("[PAIRING] img is None")
     if tof is None:
         print("[PAIRING] tof is none")


