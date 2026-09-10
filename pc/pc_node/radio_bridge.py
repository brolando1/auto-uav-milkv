# Radio bridge on the PC: the Crazyradio stays plugged in here, but all flight
# decisions are made on the Milk-V. This just executes the SETPOINT frames the
# Duo S streams over the wire and feeds the drone telemetry back up.
#
# It has its own watchdog: it owns the radio, so if the Duo S (or the wire)
# dies mid-flight, the bridge hovers and then lands the drone by itself.

import threading
import time

from cflib.crazyflie import Commander
from cflib.crazyflie.log import LogConfig

from pc_node import protocol

SP_HOVER_TIMEOUT_S = 0.3   # no setpoint from the Duo S -> hold hover
SP_ABORT_S = 2.0           # still nothing -> land + stop


class RadioBridge:
    def __init__(self, scf, link):
        self.commander = Commander(scf.cf)
        self.link = link
        self.scf = scf

        self._lock = threading.Lock()
        self._last_sp_mon = 0.0
        self._height = 0.4
        self.flying = False
        self._running = True
        self._unlock_logged = False

        self._log_conf = LogConfig(name='FlightState', period_in_ms=50)
        self._log_conf.add_variable('stateEstimate.z', 'float')
        self._log_conf.add_variable('stateEstimate.roll', 'float')
        self._log_conf.add_variable('stateEstimate.pitch', 'float')
        self._log_conf.add_variable('stateEstimate.yaw', 'float')
        self._log_conf.add_variable('sys.isTumbled', 'uint8_t')

    def start(self):
        def log_callback(timestamp, data, logconf):
            self.link.send_command({
                'cmd': 'telemetry',
                'z': data['stateEstimate.z'],
                'roll': data['stateEstimate.roll'],
                'pitch': data['stateEstimate.pitch'],
                'yaw': data['stateEstimate.yaw'],
                'tumbled': data['sys.isTumbled'],
            }, quiet=True)

        self.scf.cf.log.add_config(self._log_conf)
        self._log_conf.data_received_cb.add_callback(log_callback)
        self._log_conf.start()
        threading.Thread(name="RadioBridgeWatchdog", target=self._watchdog, daemon=True).start()
        print("[BRIDGE] Radio bridge up, forwarding telemetry to the Duo S")

    def on_setpoint(self, payload):
        # called from the DuoLink rx thread for every SETPOINT frame
        sp_type, vx, vy, yawrate, zdistance, _t_duo = protocol.decode_setpoint(payload)
        with self._lock:
            self._last_sp_mon = time.monotonic()
            if sp_type == protocol.SP_HOVER:
                self._height = zdistance
                self.flying = True
            elif sp_type == protocol.SP_STOP:
                self.flying = False

        if sp_type == protocol.SP_HOVER:
            self.commander.send_hover_setpoint(vx=vx, vy=vy, yawrate=yawrate, zdistance=zdistance)
        elif sp_type == protocol.SP_STOP:
            print("[BRIDGE] STOP")
            self.commander.send_stop_setpoint()
        elif sp_type == protocol.SP_UNLOCK:
            # the Duo S repeats this at 20 Hz while waiting for takeoff, log it once
            if not self._unlock_logged:
                print("[BRIDGE] unlock (commander armed, waiting for SPACE on this PC)")
                self._unlock_logged = True
            self.commander.send_setpoint(0.0, 0.0, 0.0, 0)

    def kill_now(self):
        # local hard kill ('k' on this machine), works even if the Duo S hangs
        with self._lock:
            self.flying = False
        print("[BRIDGE] LOCAL KILL")
        self.commander.send_stop_setpoint()

    def _watchdog(self):
        while self._running:
            time.sleep(0.03)
            with self._lock:
                if not self.flying:
                    continue
                age = time.monotonic() - self._last_sp_mon
                height = self._height
            if age > SP_ABORT_S:
                print(f"[BRIDGE] DUO S SETPOINT STREAM DEAD ({age:.1f}s): landing + stop")
                while height > 0.05:
                    height -= 0.01
                    self.commander.send_hover_setpoint(vx=0.0, vy=0.0, yawrate=0.0, zdistance=height)
                    time.sleep(0.02)
                self.commander.send_stop_setpoint()
                with self._lock:
                    self.flying = False
            elif age > SP_HOVER_TIMEOUT_S:
                self.commander.send_hover_setpoint(vx=0.0, vy=0.0, yawrate=0.0, zdistance=height)

    def stop(self):
        self._running = False
        try:
            self._log_conf.stop()
        except Exception:
            pass
        with self._lock:
            was_flying = self.flying
            self.flying = False
        if was_flying:
            self.commander.send_stop_setpoint()
