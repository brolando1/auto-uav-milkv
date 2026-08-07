import cflib.crtp  # noqa
import numpy as np
from logger.custom_logger import Logger
import time
import cv2
from logger.configs import *
import matplotlib.pyplot as plt
import os

def save_tof_to_pdf(data, output_pdf_path):
    # Mask invalid values (your code uses -1 for invalid in display_matrix)
    plot_data = np.where(data < 0.0, np.nan, data)

    fig, ax = plt.subplots(figsize=(4, 4))
    
    cmap = plt.cm.gray.copy()
    cmap.set_bad(color="#FF0000")

    # vmin/vmax ensures consistent color mapping
    im = ax.imshow(plot_data, cmap=cmap, vmin=0.0, vmax=3.0, interpolation='nearest')
    
    ax.set_title("ToF Frame")
    ax.axis('off') # Cleaner look for snapshots
    
    plt.tight_layout()
    plt.savefig(output_pdf_path, format='pdf', dpi=150)
    plt.close(fig) # Essential to prevent memor

tof_data = np.zeros(4*64, dtype=np.float32)
distances = np.zeros((8, 8), dtype=np.float32)
status = np.zeros((8, 8), dtype=np.float32)
display_matrix = np.zeros((8, 8), dtype=np.float32)
save_matrix = np.zeros((8, 8), dtype=np.float32)
save_matrix_validity = np.full((save_matrix.shape[0], save_matrix.shape[1]), True)

tof_data_log = Logger(8, 8)
startup_time = time.time()
current_tof_package = None
tof_lock = None
last_frame_time = time.time()
tof_frame_count = 0
tof_start_time = None
current_fps = 0
fps_avg = 0

def new_packet_received(packet):
    global startup_time, tof_lock, last_frame_time, save_matrix, save_matrix_validity, tof_start_time, tof_frame_count, current_tof_package

    # Safe escape if tof_lock not initialised
    if tof_lock is None: 
        return

    # Delay needed for multiprocessing
    if (time.time() - startup_time) < 3.0:
        return

    data = packet._get_data_l()
    if data[0] == 68:
        idx = data[1]
        for i in range(len(data) - 2):
            tof_data[idx*28 + i] = data[i+2]
            
        if idx == 6:
            # print("[TOF] receiving tof frame")
            if tof_start_time is None:
                tof_start_time = time.time()

            # Get FPS
            now = time.time()
            dt = now - last_frame_time
            last_frame_time = now
            tof_frame_count += 1
            total_elapsed = now - tof_start_time
            current_fps = 1.0/dt if dt > 0 else 0.0
            fps_avg = tof_frame_count / total_elapsed if total_elapsed > 0 else 0.0

            if tof_frame_count % 50 == 0: # Save once every 50 frames to keep it performant
                os.makedirs("captured_frames", exist_ok=True)
                filename = f"captured_frames/frame_{tof_frame_count}.pdf"
                save_tof_to_pdf(display_matrix, filename)
                print(f"Saved snapshot: {filename}")

            for i in range(8):
                for j in range(8):
                    distances[i, j] = int(tof_data[2*(j+8*i)] + 256*tof_data[2*(j+8*i)+1])
                    status[i, j] = int(tof_data[j+8*i+128])

                    if (status[i, j] != 5 and status[i, j] != 9):
                        display_matrix[i, j] = -1
                        save_matrix[i, j] = 3000  # Set invalid pixels to max range (we defined max range = 3.0m)
                        save_matrix_validity[i, j] = False
                    else:
                        display_matrix[i, j] = distances[i, j] / 1000.0
                        save_matrix[i, j] = distances[i, j]
                        save_matrix_validity[i, j] = True

            metadata = {
                'seq': idx, 
                'fps_inst': current_fps, 
                'fps_avg': fps_avg, 
                't_mon': time.monotonic()}
            
            latest_tof_package = {
                'matrix': save_matrix.copy(),
                'validity_matrix': save_matrix_validity.copy(),
                'metadata': metadata
            }

            current_tof_package = latest_tof_package
            # file_name = round(1000 * (time.time() - time0))
            # save_frame_pair(file_name, save_matrix)

        show_tof_frame(display_matrix)


def show_tof_frame(tof):
    # Make invalid pixels red
    tof_show = tof.copy()
    tof_show = cv2.cvtColor(tof, cv2.COLOR_GRAY2RGB)
    for row in range(0, tof_show.shape[0]):
        for col in range(0, tof_show.shape[1]):
            if tof[row, col] < 0.0:
                tof_show[row, col, 0] = 0
                tof_show[row, col, 1] = 0
                tof_show[row, col, 2] = 255

    # Scale to uint8 range
    tof_show = (tof_show * 255 / 3.0).astype(np.uint8)

    # For visibility of output only
    tof_show = cv2.resize(tof_show, dsize=[168, 168], interpolation=cv2.INTER_NEAREST)
    cv2.imshow('ToF image', tof_show)
    cv2.waitKey(1)


def crazyflie_data_logger(time_ref, lock):
    global time0, tof_lock
    time0 = time_ref
    tof_lock = lock

    while True:
        time.sleep(1)

