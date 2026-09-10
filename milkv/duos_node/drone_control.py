# Flight control loop on the Milk-V. The Crazyradio dongle stays on the PC:
# this loop makes all the decisions (auto/manual mixing, obstacle avoidance,
# failsafes) and streams SETPOINT instructions to the PC radio bridge
# (pc_node/radio_bridge.py), which executes them on the cflib Commander and
# sends telemetry back up. The keyboard state also comes in from the PC.
#
# Takeoff is armed from the PC with the space key (no blind 10 s countdown, the
# pilot is remote now).

import threading
import time

import numpy as np

from common import protocol

# p(gate) above which auto mode follows the navigator's yaw instead of the ToF
# obstacle avoidance (the inference loop only runs the navigator above it)
GATE_THRESHOLD = 0.5
from common.tof_obstacle_avoidance import avoid_obstacles_tof

FAILSAFE_THRESHOLD = 250 #in mm
YAW_RATE_SCALE_CNN = 2.75
YAW_RATE_SCALE_TOA = 1.5

# sensor/prediction staleness (wifi or inference died)
STALE_HOVER_S = 0.3
STALE_ABORT_S = 2.0
# PC key stream staleness (wire or ground station died)
KEYS_HOVER_S = 1.0
KEYS_ABORT_S = 3.0


class RemoteCommander:
    # same call surface as the cflib Commander, but every call becomes a
    # SETPOINT frame that the PC radio bridge executes on the real Commander
    def __init__(self, pc_link):
        self._pc_link = pc_link

    def _send(self, sp_type, vx=0.0, vy=0.0, yawrate=0.0, zdistance=0.0):
        self._pc_link.publish(
            protocol.FRAME_SETPOINT,
            protocol.encode_setpoint(sp_type, vx, vy, yawrate, zdistance, time.monotonic()),
        )

    def send_hover_setpoint(self, vx=0.0, vy=0.0, yawrate=0.0, zdistance=0.0):
        self._send(protocol.SP_HOVER, vx, vy, yawrate, zdistance)

    def send_stop_setpoint(self):
        self._send(protocol.SP_STOP)

    def send_unlock(self):
        self._send(protocol.SP_UNLOCK)


class TelemetryState:
    # latest drone telemetry received from the PC radio bridge (50ms log block)
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {'z': 0.0, 'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0, 'tumbled': 0}
        self._t_mon = 0.0

    def update(self, msg):
        with self._lock:
            for k in self._data:
                if k in msg:
                    self._data[k] = msg[k]
            self._t_mon = time.monotonic()

    def snapshot(self):
        with self._lock:
            return dict(self._data)

    def age_s(self):
        with self._lock:
            if self._t_mon <= 0.0:
                return float('inf')
            return time.monotonic() - self._t_mon


class KeyState:
    # latest pressed-keys set received from the PC
    def __init__(self):
        self._lock = threading.Lock()
        self._pressed = set()
        self._t_mon = 0.0

    def update(self, pressed):
        with self._lock:
            self._pressed = set(pressed)
            self._t_mon = time.monotonic()

    def is_pressed(self, key):
        with self._lock:
            return key in self._pressed

    def age_s(self):
        with self._lock:
            if self._t_mon <= 0.0:
                return float('inf')
            return time.monotonic() - self._t_mon


class FlightData:
    # freshest ToF frame + freshest predictions from the inference loop
    def __init__(self):
        self._lock = threading.Lock()
        self._tof = None            # (matrix_mm, validity, t_mon)
        self._pred = None           # (p_gate_ema, yaw_rate, t_mon)

    def set_tof(self, package):
        with self._lock:
            self._tof = (package['matrix'], package['validity_matrix'], package['metadata']['t_mon'])

    def set_prediction(self, p_gate_ema, yaw_rate):
        with self._lock:
            self._pred = (float(p_gate_ema), float(yaw_rate), time.monotonic())

    def get(self):
        with self._lock:
            return self._tof, self._pred

    def age_s(self):
        # age of the older of the two inputs the auto mode depends on
        with self._lock:
            if self._tof is None or self._pred is None:
                return float('inf')
            now = time.monotonic()
            return max(now - self._tof[2], now - self._pred[2])


def failsafe_required(tof, failsafe_threshold):
    col_wise_sum = np.sum(tof, axis=0)
    left_fail_boundary = 2
    right_fail_boundary = 6
    for i in range(left_fail_boundary, right_fail_boundary):
        if (col_wise_sum[i] / 8.0 < failsafe_threshold):
            return True
    return False


def smooth_velocity(previous_command, target_command, alpha_filter, alpha_acc=0.2, alpha_dec=0.4):
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


def drone_flight_controller(commander, telemetry, flight_data, key_state, orchestrator, flight_status, stop_event):
    # commander: RemoteCommander (setpoints go to the PC radio bridge)
    # telemetry: TelemetryState fed by the PC's 'telemetry' messages

    # Motion params (same as the old PC controller)
    forward_step = 0.5      # [m/s]
    sideways_step = 0.5     # [m/s]
    angular_step = 57.3     # [deg/s]  57.3 deg/s == 1 rad/s
    height_step = 0.01      # [m]
    height = 0.4            # [m] Start height

    gate_threshold = GATE_THRESHOLD
    forward_vel_multiplier = 1.75

    # Wait until the PC radio bridge is up (telemetry flowing = drone connected)
    print("[CF CONTROL] Waiting for the PC radio bridge / drone telemetry...")
    flight_status['state'] = 'waiting_radio'
    while not stop_event.is_set() and telemetry.age_s() > 1.0:
        time.sleep(0.1)
    if stop_event.is_set():
        return

    commander.send_unlock()

    # Wait for the PC to arm takeoff with space
    print("[CF CONTROL] Radio bridge up. Waiting for SPACE from the PC to take off...")
    flight_status['state'] = 'armed'
    while not stop_event.is_set():
        if key_state.is_pressed('space') and key_state.age_s() < 0.5:
            break
        if key_state.is_pressed('k'):
            print("[CF CONTROL] Kill before takeoff, controller exiting")
            flight_status['state'] = 'killed'
            commander.send_stop_setpoint()
            return
        # keep the commander alive while waiting (same as the old PC controller)
        commander.send_unlock()
        time.sleep(0.05)
    if stop_event.is_set():
        return

    print("[CF CONTROL] TAKEOFF")
    flight_status['state'] = 'flying'

    # Slow takeoff to avoid high currents and camera feed cutoff
    current_height = 0.0
    for i in range(0, 100):
        current_height += height / 100
        commander.send_hover_setpoint(vx=0.0, vy=0.0, yawrate=0.0, zdistance=current_height)
        time.sleep(0.01)

    kill_flag = False
    auto_mode = False
    last_pred = None
    last_forward_v = 0.0
    max_forward_vel = 0.5

    def land_and_stop(reason):
        nonlocal height
        print(f"[CF CONTROL] {reason}: landing + stop")
        while height > 0.05:
            height -= 0.01
            commander.send_hover_setpoint(vx=0.0, vy=0.0, yawrate=0.0, zdistance=height)
            time.sleep(0.02)
        commander.send_stop_setpoint()
        flight_status['state'] = 'landed'

    while not stop_event.is_set():
        forward_vel = 0.0
        sideways_vel = 0.0
        yaw_rate = 0.0

        drone_telemetry = telemetry.snapshot()
        flight_status.update(drone_telemetry)

        # Crash detection (decided here, motors stopped via the PC bridge)
        if drone_telemetry['tumbled'] == 1:
            print("[CRASH DETECTED] drone crashed!! killing drone")
            kill_flag = True
        if abs(drone_telemetry['pitch']) > 70 or abs(drone_telemetry['roll']) > 70:
            print("[CRASH DETECTED] Extreme angle. killing drone!")
            kill_flag = True
        if kill_flag:
            print('kill')
            commander.send_stop_setpoint()
            flight_status['state'] = 'crashed'
            # motors are off, dump the buffer + retrain right here
            orchestrator.trigger_dump(source='crash')
            return

        # PC key stream watchdog: no ground station -> no pilot -> get down
        keys_age = key_state.age_s()
        if keys_age > KEYS_ABORT_S:
            land_and_stop(f"PC KEY STREAM DEAD ({keys_age:.1f}s)")
            return
        if keys_age > KEYS_HOVER_S:
            commander.send_hover_setpoint(vx=0.0, vy=0.0, yawrate=0.0, zdistance=height)
            time.sleep(0.03)
            continue

        if key_state.is_pressed('i'):
            if not auto_mode:
                print("[CF CONTROL] AUTO MODE ENGAGED")
            auto_mode = True

        manual_keys = ['w', 'a', 's', 'd', 'q', 'e', 'o', 'p', 'k']
        if any(key_state.is_pressed(key) for key in manual_keys):
            if auto_mode:
                print("[CF CONTROL] MANUAL OVERRIDE: AUTO MODE DISENGAGED\n")
            auto_mode = False
        flight_status['auto'] = auto_mode

        if auto_mode:
            # Sensor/prediction watchdog (wifi to the deck or inference died)
            data_age = flight_data.age_s()
            if data_age > STALE_ABORT_S:
                land_and_stop(f"SENSOR/PREDICTION STREAM DEAD ({data_age:.1f}s)")
                return
            if data_age > STALE_HOVER_S:
                commander.send_hover_setpoint(vx=0.0, vy=0.0, yawrate=0.0, zdistance=height)
                time.sleep(0.03)
                continue

            tof, pred = flight_data.get()
            tof_frame, tof_validity, _ = tof
            gate_prob, yaw_rate_nn, _ = pred

            # Run tof obstacle avoidance
            forward_obstacle_avoidance, _, yaw_rate_obstacle_avoidance = avoid_obstacles_tof(None, tof_frame, tof_validity)

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
                    # Fly towards the gate with the navigator yaw rate
                    forward_vel = max(0.5, forward_obstacle_avoidance) * forward_vel_multiplier
                    yaw_rate_rad = yaw_rate_nn
            else:  # If gate is not seen use ToF obstacle avoidance
                if last_pred != 'NO':
                    print('NO: ', round(gate_prob * 100, 3), "%")
                last_pred = 'NO'
                forward_vel = forward_obstacle_avoidance  #* 0.7
                yaw_rate_rad = yaw_rate_obstacle_avoidance * 2.0

            forward_vel = smooth_velocity(last_forward_v, forward_vel, alpha_filter=True, alpha_acc=0.1, alpha_dec=0.3)
            last_forward_v = forward_vel

            # Convert yaw_rate to degrees
            if last_pred == 'YES':
                yaw_rate = yaw_rate_rad*YAW_RATE_SCALE_CNN/np.pi * 180
            else: #tof_obstacle_avoidance
                yaw_rate = -yaw_rate_rad*YAW_RATE_SCALE_TOA/ np.pi * 180
                forward_vel = min(max_forward_vel, forward_vel)

        else:
            # KEYBOARD CONTROLLED (keys arrive from the PC)
            if key_state.is_pressed('e'):
                yaw_rate += angular_step
            if key_state.is_pressed('q'):
                yaw_rate -= angular_step
            if key_state.is_pressed('w'):
                forward_vel += forward_step
            if key_state.is_pressed('s'):
                forward_vel -= forward_step
            if key_state.is_pressed('d'):
                sideways_vel -= sideways_step
            if key_state.is_pressed('a'):
                sideways_vel += sideways_step
            if key_state.is_pressed('o'):
                height += height_step
            if key_state.is_pressed('p'):
                height -= height_step
            if key_state.is_pressed('k'):
                kill_flag = True

        if kill_flag:
            print('KILL')
            commander.send_stop_setpoint()
            flight_status['state'] = 'killed'
            return

        commander.send_hover_setpoint(vx=forward_vel, vy=sideways_vel, yawrate=yaw_rate, zdistance=height)
        time.sleep(0.03)

    # stop_event set (node shutting down)
    commander.send_stop_setpoint()
    flight_status['state'] = 'stopped'
