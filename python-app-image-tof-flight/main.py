import threading
import argparse
import time
import cv2
import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from logger.crazyflie_manager import crazyflie_data_logger, new_packet_received
from crazyflie_control import crazyflie_keyboard_controller
from logger.camera_logger import crazy_camera_logger
from training_quantization.continual_learning.opencv_viewer import crazyflie_viewer

console_buffer = ''
def console_callback(char):
    global console_buffer
    console_buffer += char
    print("[CF]", console_buffer, end="")
    console_buffer = ''

stop_event = threading.Event()
shared_state = {'p_gate': 0.0,
                'lock': threading.Lock(),
                'crash': 0}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", action="store_true")
    parser.add_argument("--tof", action="store_true")
    parser.add_argument("--keyboard", action="store_true")
    parser.add_argument("--viewer", action="store_true")
    args, unknown = parser.parse_known_args()

    time0 = time.time()

    # Threading
    image_lock = threading.Lock()
    tof_lock = threading.Lock()
    

    # Set up drone radio connection
    cflib.crtp.init_drivers(enable_debug_driver=False)
    # drones = cflib.crtp.scan_interfaces()
    # uri = drones[0][0]
    uri = 'radio://0/120/2M/E7E7E7E714'

    cf = Crazyflie(rw_cache='./cache')
    cf.add_port_callback(1, new_packet_received)

    threads = []

    with SyncCrazyflie(uri, cf=cf) as scf:
        # Needed for multithreaded cv2.imshow
        scf.cf.console.receivedChar.add_callback(console_callback)
        cv2.namedWindow('Camera + ToF')

        #Start camera thread
        if args.camera:
            thread_1 = threading.Thread(name="CameraThread", target=crazy_camera_logger, args=(time0, image_lock))
            thread_1.start()
            threads.append(thread_1)

        
        #Start ToF thread
        if args.tof:
            thread_2 = threading.Thread(name="ToFThread", target=crazyflie_data_logger, args=(time0, tof_lock))
            print("[TOF] thread is about to start")
            thread_2.start()
            print("[TOF] thread started")
            threads.append(thread_2)

        # Start keyboard controller thread
        if args.keyboard:
            thread_3 = threading.Thread(name="Control thread", target=crazyflie_keyboard_controller, args=(scf, image_lock, tof_lock, shared_state))
            print("[CONTROLLER] thread about to start")
            thread_3.start()
            print("[CONTROLLER] thread started")
            threads.append(thread_3)

        # Start opencv-viewer thread
        if args.viewer:
            import sys
            sys.argv = [sys.argv[0]] + unknown
            thread_4 = threading.Thread(name="ViewerThread", target=crazyflie_viewer, args= (shared_state,))
            thread_4.start()
            threads.append(thread_4)

        #OpenCv
        # try:
        #     while not stop_event.is_set():
        #         time.sleep(0.5)
        # except KeyboardInterrupt:
        #     stop_event.set()
        cv2.waitKey(0)


    # Clean up
    cv2.destroyAllWindows()
    for t in threads:
        t.join()
