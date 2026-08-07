import keyboard
from cflib.crazyflie import Commander
from cflib.crazyflie.log import LogConfig
from crazyflie_commander import *
from training_quantization.inference_gate_navigator_in_loop import InferenceGateNavigatorInLoop
from tof_obstacle_avoidance import avoid_obstacles_tof
import time
import threading
# from training_quantization.continual_learning.opencv_viewer import shared_p_gate, p_gate_lock
from logger.camera_tof_pairing import control_pair_buffer, control_pair_buffer_lock

FAILSAFE_THRESHOLD = 150 #in mm
YAW_RATE_SCALE_CNN = 2.75
YAW_RATE_SCALE_TOA = 1.5


def failsafe_required(tof, failsafe_threshold):
    col_wise_sum = np.sum(tof, axis=0)
    left_fail_boundary = 2
    right_fail_boundary = 6
    for i in range(left_fail_boundary, right_fail_boundary):
        if (col_wise_sum[i] / 8.0 < failsafe_threshold):
            return True
    return False

def smooth_velocity(
    previous_command: float,
    target_command: float,
    alpha_filter: bool,
    alpha_acc: float = 0.2,
    alpha_dec: float = 0.4
)-> float:
    
    # NOTE: smooth forward velocity to avoid jerky movements
    run_command = 0.0
    if alpha_filter:
        if previous_command < target_command:
            run_command = alpha_acc * target_command + (1.0 - alpha_acc) * previous_command
        else:
            run_command = alpha_dec * target_command + (1.0 - alpha_dec) * previous_command
    else:
        if target_command > 0 and previous_command > 0:
            if target_command >= previous_command:
                run_command = min(target_command, previous_command * 1.1)
            else:
                run_command = max(target_command, previous_command * 0.6)
        elif target_command >= 0 and previous_command < 0:
            run_command = 0.0
        elif previous_command == 0:
            if target_command > 0:
                run_command = 0.10
            else:
                run_command = target_command
        else:
            run_command = target_command

    return run_command

def crazyflie_keyboard_controller(scf, image_lock, tof_lock, shared_state):
    # Motion params
    forward_step = 0.5      # [m/s]
    sideways_step = 0.5     # [m/s]
    angular_step = 57.3     # [deg/s]  57.3 deg/s == 1 rad/s
    height_step = 0.01      # [m]

    height = 0.4            # [m] Start height

    # Full pipeline params
    
    gate_threshold = 0.89
    forward_vel_multiplier = 1.25

    # CNN controller
    print("[CONTROLLER] gate nav model init before")
    inference_model = InferenceGateNavigatorInLoop(image_lock, tof_lock)
    print("gate nav inference init done")

    drone_telemetry={'z': 0.0,
                     'roll': 0.0,
                     'pitch': 0.0,
                     'yaw': 0.0,
                     'tumbled': 0}
    
    def log_callback(timestamp, data, logconf):
        drone_telemetry['z'] = data['stateEstimate.z']
        drone_telemetry['roll'] = data['stateEstimate.roll']
        drone_telemetry['pitch'] = data['stateEstimate.pitch']
        drone_telemetry['yaw'] = data['stateEstimate.yaw']
        drone_telemetry['tumbled'] = data['sys.isTumbled']

    log_conf = LogConfig(name='FlightState', period_in_ms=50)
    log_conf.add_variable('stateEstimate.z', 'float')
    log_conf.add_variable('stateEstimate.roll', 'float')
    log_conf.add_variable('stateEstimate.pitch', 'float')
    log_conf.add_variable('stateEstimate.yaw', 'float')
    log_conf.add_variable('sys.isTumbled', 'uint8_t')

    scf.cf.log.add_config(log_conf)
    print("[DEBUG] before adding callback keyboard")
    log_conf.data_received_cb.add_callback(log_callback)
    print("[DEBUG] after callback before start")
    log_conf.start()
    print("DEBUG after starting log")

    # Init
    commander = Commander(scf.cf)
    time.sleep(1)
    commander.send_setpoint(0.0, 0.0, 0.0, 0)
    print('Delaying takeoff by 10 seconds. Make sure to click onto terminal window. If OpenCv window is focused, a keypress will terminate programm.')
    time.sleep(10)

    # Slow takeoff to avoid high currents and camera feed cutoff
    current_height = 0.0
    for i in range(0, 100):
        current_height += height / 100
        commander.send_hover_setpoint(vx=0.0, vy=0.0, yawrate=0.0, zdistance=current_height)
        time.sleep(0.01)

    kill_flag = False
    keep_flying = True
    auto_mode = False #use only for non flying testing
    last_pred = None
    # last_yaw = 0.0
    last_forward_v = 0.0
    max_forward_vel = 0.5

    while keep_flying:
        forward_vel = 0.0
        sideways_vel = 0.0
        yaw_rate = 0.0

        if drone_telemetry['tumbled'] == 1:
            print("[CRASH DETECTED] drone crashed!! killing drone")
            kill_flag = True
            with shared_state['lock']:
                shared_state['crash'] = 1
        if abs(drone_telemetry['pitch']) > 70 or abs(drone_telemetry['roll']) > 70:
            print("[CRASH DETECTED] Extreme angle. killing drone!")
            kill_flag = True
            with shared_state['lock']:
                shared_state['crash'] = 1
        if kill_flag == True:
            print('kill')
            commander.send_stop_setpoint()
            log_conf.stop()
            return

        # # Uncomment to compute image standardizer values for scene
        # inference_model.compute_image_standardizer_values()
    
        if keyboard.is_pressed('i'):
            if not auto_mode:
                print("[CF CONTROL] AUTO MODE ENGAGED")
            auto_mode = True
        
        manual_keys = ['w', 'a', 's', 'd', 'q', 'e', 'o', 'p', 'k']
        if any(keyboard.is_pressed(key) for key in manual_keys):
            if auto_mode:
                print("[CF CONTROL] MANUAL OVERRIDE: AUTO MODE DISENGAGED\n")
            auto_mode = False 

        if auto_mode:
            # CNN CONTROLLED
            # Run inference pre step
            triplet = None
            with control_pair_buffer_lock:
                if len(control_pair_buffer) > 0:
                    triplet = control_pair_buffer[-1]
                    image_decoded, tof_frame, tof_validity = triplet
                    control_pair_buffer.clear()
            if triplet is None:
                time.sleep(0.03)
                continue

            inference_model._predict_pre_step(image_decoded, tof_frame)

            # Predict probability of seeing a gate & update crash variable

            with shared_state['lock']:
                gate_prob = shared_state['p_gate']

            # Run tof obstacle avoidance
            forward_obstacle_avoidance, _, yaw_rate_obstacle_avoidance = avoid_obstacles_tof(tof_lock, tof_frame, tof_validity)

            if gate_prob >= gate_threshold:  # If gate is seen use CNN navigation controller
                if last_pred != 'YES':
                    print('YES: ', round(gate_prob * 100, 3), "%")
                last_pred = 'YES'
                # Check for failsafe procedure need. If true, speed to zero and turn hard
                if failsafe_required(tof_frame, FAILSAFE_THRESHOLD):
                    print('FAILSAFE')
                    failsafe_start = time.time()
                    #fly backwards during one second if failsafe is required
                    while time.time() - failsafe_start < 1.0:
                        commander.send_hover_setpoint(vx = -0.5,
                                                      vy = 0.0,
                                                      yawrate = 0.0,
                                                      zdistance = height)
                        time.sleep(0.03)
                    continue
                else:
                    # Predict the yaw rate to fly towards gate
                    forward_vel = max(0.5, forward_obstacle_avoidance) * forward_vel_multiplier
                    yaw_rate_cnn = inference_model.predict_navigation()
                    yaw_rate_rad = yaw_rate_cnn[0]
                    # Scale yaw rate for slower/faster speeds than training (at 0.5 m/s). empirical scaling (*2.0) for better performance
                    # yaw_rate_rad = yaw_rate_cnn * (forward_vel / 0.5) * 1.0
            else:  # If gate is not seen use ToF obstacle avoidance
                if last_pred != 'NO':
                    print('NO: ', round(gate_prob * 100, 3), "%")
                last_pred = 'NO'
                forward_vel = forward_obstacle_avoidance * 0.7
                yaw_rate_rad = yaw_rate_obstacle_avoidance * 2.0

            forward_vel = smooth_velocity(last_forward_v, forward_vel, alpha_filter=True, alpha_acc=0.1, alpha_dec=0.3)
            last_forward_v = forward_vel

            # Convert yaw_rate to degrees
            if last_pred == 'YES':
                yaw_rate = yaw_rate_rad*YAW_RATE_SCALE_CNN/np.pi * 180
                print(f"navigator output: {yaw_rate}")
            else: #tof_obstacle_avoidance
                yaw_rate = -yaw_rate_rad*YAW_RATE_SCALE_TOA/ np.pi * 180
                forward_vel = min(max_forward_vel, forward_vel)


            # if forward_vel != last_forward_v or yaw_rate != last_yaw:
            #     print('rate yaw: ', round(yaw_rate, 3), " deg/s")
            #     print('forward velocity: ', forward_vel)
            #     if yaw_rate < 0.0:
            #         print("[CONTROLLER] turn right")
            #     elif yaw_rate == 0.0:
            #         print("[CONTROLLER] no turn")
            #     else:
            #         print("[CONTROLLER] turn left")
            #     if forward_vel > 0.0:
            #         print("[CONTROLLER] forward")
            #     else: 
            #         print("[CONTROLLER] backwards")
            #     last_yaw = yaw_rate
            #     last_forward_v = forward_vel

        else:
        
            # KEYBOARD CONTROLLED
            # CMD TURN RIGHT
            if keyboard.is_pressed('e'):
                yaw_rate += angular_step
            # CMD TURN LEFT
            if keyboard.is_pressed('q'):
                yaw_rate -= angular_step
            # CMD FORWARD
            if keyboard.is_pressed('w'):
                forward_vel += forward_step
            # CMD BACKWARD
            if keyboard.is_pressed('s'):
                forward_vel -= forward_step
            # CMD RIGHT
            if keyboard.is_pressed('d'):
                sideways_vel -= sideways_step
            # CMD LEFT
            if keyboard.is_pressed('a'):
                sideways_vel += sideways_step
            # CMD DOWNWARD
            if keyboard.is_pressed('o'):
                height += height_step
            # CMD UPWARD
            if keyboard.is_pressed('p'):
                height -= height_step
            if keyboard.is_pressed('k'):
                kill_flag = True

        if kill_flag == True:
            print('KILL')
            commander.send_stop_setpoint()
            log_conf.stop()
            return

        # print('yaw rate deg: ', yaw_rate)

        commander.send_hover_setpoint(vx=forward_vel, vy=sideways_vel, yawrate=yaw_rate, zdistance=height)

        time.sleep(0.03)


