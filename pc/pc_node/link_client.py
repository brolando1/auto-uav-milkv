# PC side of the wired link to the Duo S. Receives the relayed camera/ToF
# stream plus the predictions and feeds them into the pairing seam the viewer
# reads (camera_tof_pairing.current_tof_package + frame_pairing).

import socket
import threading
import time

import cv2
import numpy as np

import pc_node.camera_tof_pairing as pairing
from pc_node import protocol


class DuoLink:
    def __init__(self, duos_ip, duos_port=5800, shared_state=None, on_setpoint=None):
        self.duos_ip = duos_ip
        self.duos_port = duos_port
        self.shared_state = shared_state
        self.on_setpoint = on_setpoint  # radio bridge callback (payload bytes)

        self._sock = None
        self._send_lock = threading.Lock()
        self._running = True

        self._lock = threading.Lock()
        self._debug = None   # (cam model input u8 168x168, tof model input f32 21x21, seq)
        self.remote = {
            'p_gate_raw': 0.0,
            'p_gate_med': 0.0,
            'p_gate_ema': 0.0,
            'yaw_rate': 0.0,
            'pred': 'NO_GATE',
            'seq': None,
            'model_name': 'unknown',
            'model_gen': 0,
            'cam_fps_inst': 0.0,
            'cam_fps_avg': 0.0,
            'tof_fps_inst': 0.0,
            'tof_fps_avg': 0.0,
            'wifi_ok': False,
            'training': {'state': 'idle'},
            'echo_t_pc': None,
            't_state_mon': 0.0,   # monotonic time of last STATE frame
            't_rx_mon': 0.0,      # monotonic time of last frame of any kind
            'link_ok': False,
        }

        # ToF fps bookkeeping (recomputed on the PC side at arrival)
        self._tof_frame_count = 0
        self._tof_start_time = None
        self._tof_last_time = time.time()

    def start(self):
        threading.Thread(name="DuoLinkThread", target=self._run, daemon=True).start()

    def stop(self):
        self._running = False

    def snapshot(self):
        with self._lock:
            return dict(self.remote)

    def latest_debug(self):
        # newest model inputs relayed by the Duo S (only while the viewer asks), or None
        with self._lock:
            return self._debug

    def state_age_s(self):
        with self._lock:
            if not self.remote['link_ok'] or self.remote['t_state_mon'] <= 0.0:
                return float('inf')
            return time.monotonic() - self.remote['t_state_mon']

    def send_command(self, cmd_dict, quiet=False):
        cmd_dict.setdefault('t_pc', time.monotonic())
        with self._send_lock:
            sock = self._sock
            if sock is None:
                if not quiet:
                    print(f"[DUOLINK] Not connected, command dropped: {cmd_dict.get('cmd')}")
                return False
            try:
                protocol.send_frame(sock, protocol.FRAME_CMD, protocol.encode_json(cmd_dict))
                return True
            except (OSError, ConnectionError) as e:
                print(f"[DUOLINK] Send failed: {e}")
                return False

    def _run(self):
        while self._running:
            try:
                print(f"[DUOLINK] Connecting to {self.duos_ip}:{self.duos_port}...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.duos_ip, self.duos_port))
                sock.settimeout(None)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                print("[DUOLINK] Connected")
                with self._send_lock:
                    self._sock = sock
                with self._lock:
                    self.remote['link_ok'] = True
                self._recv_loop(sock)
            except (OSError, ConnectionError) as e:
                print(f"[DUOLINK] Connection lost: {e}")
            finally:
                with self._send_lock:
                    self._sock = None
                with self._lock:
                    self.remote['link_ok'] = False
                try:
                    sock.close()
                except Exception:
                    pass
            if self._running:
                time.sleep(1.0)

    def _recv_loop(self, sock):
        while self._running:
            frame_type, payload = protocol.recv_frame(sock)
            now_mon = time.monotonic()
            with self._lock:
                self.remote['t_rx_mon'] = now_mon

            if frame_type == protocol.FRAME_SETPOINT:
                # flight critical: hand straight to the radio bridge
                if self.on_setpoint is not None:
                    self.on_setpoint(payload)

            elif frame_type == protocol.FRAME_STATE:
                state = protocol.decode_json(payload)
                with self._lock:
                    self.remote.update(state)
                    self.remote['t_state_mon'] = now_mon
                if self.shared_state is not None:
                    with self.shared_state['lock']:
                        self.shared_state['p_gate'] = float(state.get('p_gate_ema', 0.0))

            elif frame_type == protocol.FRAME_JPEG:
                _seq, _t_duo, jpeg_bytes = protocol.decode_jpeg(payload)
                nparr = np.frombuffer(jpeg_bytes, np.uint8)
                decoded = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
                pairing.frame_pairing(decoded)

            elif frame_type == protocol.FRAME_DEBUG:
                seq, _t_duo, cam_jpeg, tof_norm = protocol.decode_debug(payload)
                cam_uint8 = cv2.imdecode(np.frombuffer(cam_jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
                with self._lock:
                    self._debug = (cam_uint8, tof_norm.copy(), seq)

            elif frame_type == protocol.FRAME_TOF:
                seq, _t_duo, matrix, validity = protocol.decode_tof(payload)
                now = time.time()
                if self._tof_start_time is None:
                    self._tof_start_time = now
                dt = now - self._tof_last_time
                self._tof_last_time = now
                self._tof_frame_count += 1
                total_elapsed = now - self._tof_start_time
                fps_inst = 1.0 / dt if dt > 0 else 0.0
                fps_avg = self._tof_frame_count / total_elapsed if total_elapsed > 0 else 0.0

                pairing.current_tof_package = {
                    'matrix': matrix,
                    'validity_matrix': validity,
                    'metadata': {
                        'seq': seq,
                        'fps_inst': fps_inst,
                        'fps_avg': fps_avg,
                        't_mon': now_mon,
                    },
                }
