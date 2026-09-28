# Serial link to the Crazyflie: UART1 of the expansion port on the drone side,
# /dev/ttyS2 (header pins 11 and 13) on the Duo S. The STM32 app streams ToF
# frames and the drone state, the setpoints go back the same way. This is also
# the commander for the flight controller, same three calls as before.
#
# Test by hand with the wire connected:  python3 -m duos_node.uart_link

import os
import select
import termios
import threading
import time

from common import protocol

PORT = "/dev/ttyS2"
BAUD = termios.B115200
STALL_TIMEOUT_S = 1.0    # no frame for this long counts as disconnected


class UARTLink:
    def __init__(self, on_tof, on_state):
        self.on_tof = on_tof        # on_tof(package), same package the CPX reader used to build
        self.on_state = on_state    # on_state({'z', 'roll', 'pitch', 'yaw', 'tumbled'})
        self.connected = False
        self._fd = None
        self._running = False
        self._thread = None
        self._write_lock = threading.Lock()
        # tof fps bookkeeping, shown in the viewer
        self._tof_count = 0
        self._tof_t0 = None
        self._tof_last = time.time()

    def start(self):
        self._fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attr = termios.tcgetattr(self._fd)
        attr[0] = 0                                             # iflag: raw
        attr[1] = 0                                             # oflag: raw
        attr[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # cflag: 8N1, no flow control
        attr[3] = 0                                             # lflag: no echo, no line editing
        attr[4] = attr[5] = BAUD
        termios.tcsetattr(self._fd, termios.TCSANOW, attr)
        termios.tcflush(self._fd, termios.TCIOFLUSH)
        self._running = True
        self._thread = threading.Thread(name="UARTLinkThread", target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread.join(timeout=2.0)
        os.close(self._fd)

    # ---- commander side, called from the flight controller thread ----
    def send_hover_setpoint(self, vx=0.0, vy=0.0, yawrate=0.0, zdistance=0.0):
        self._send(protocol.uart_encode_cmd(protocol.SP_HOVER, vx, vy, yawrate, zdistance))

    def send_stop_setpoint(self):
        self._send(protocol.uart_encode_cmd(protocol.SP_STOP))

    def send_unlock(self):
        self._send(protocol.uart_encode_cmd(protocol.SP_UNLOCK))

    def _send(self, frame):
        with self._write_lock:
            try:
                os.write(self._fd, frame)
            except OSError:
                pass    # port not ready, the controller repeats every setpoint anyway

    # ---- reader side ----
    def _run(self):
        parser = protocol.UartParser()
        last_frame = 0.0
        while self._running:
            ready, _, _ = select.select([self._fd], [], [], 0.1)
            if ready:
                for frame_type, payload in parser.feed(os.read(self._fd, 4096)):
                    last_frame = time.monotonic()
                    if frame_type == protocol.UART_TOF and len(payload) == protocol.UART_TOF_LEN:
                        self._handle_tof(payload)
                    elif frame_type == protocol.UART_STATE and len(payload) == protocol.UART_STATE_STRUCT.size:
                        self.on_state(protocol.uart_decode_state(payload))
            self.connected = time.monotonic() - last_frame < STALL_TIMEOUT_S

    def _handle_tof(self, payload):
        seq, timestamp_ms, dist_bytes, status_bytes = protocol.uart_decode_tof(payload)
        matrix, validity = protocol.tof_arrays_from_raw(dist_bytes, status_bytes)

        now = time.time()
        if self._tof_t0 is None:
            self._tof_t0 = now
        dt = now - self._tof_last
        self._tof_last = now
        self._tof_count += 1
        elapsed = now - self._tof_t0

        self.on_tof({
            'matrix': matrix,
            'validity_matrix': validity,
            'metadata': {
                'seq': seq,
                'fps_inst': 1.0 / dt if dt > 0 else 0.0,
                'fps_avg': self._tof_count / elapsed if elapsed > 0 else 0.0,
                't_mon': time.monotonic(),
                'timestamp_ms': timestamp_ms,
            },
            'raw': (dist_bytes, status_bytes),
        })


if __name__ == "__main__":
    # quick check: counts ToF frames for 5 s and shows the last state
    tof_frames = []
    state = {}
    link = UARTLink(on_tof=tof_frames.append, on_state=state.update)
    link.start()
    time.sleep(5)
    link.stop()
    print(f"{len(tof_frames) / 5:.1f} ToF frames/s, state: {state or 'nothing received'}")
