# Reader for the AI-deck socket (single TCP client on 192.168.4.1:5000).
# Both the GAP8 (jpeg stream) and the STM32 (ToF via TOF_OVER_CPX) end up on
# this socket, so unlike the old PC camera logger we have to demux on the CPX source
# field instead of assuming everything is image traffic.

import socket
import struct
import threading
import time

from common import protocol

IMG_HEADER = struct.Struct('<BHHBBI')  # magic, width, height, depth, format, size


# No CPX data for this long means the deck is gone (drone power-cycled, battery
# swap): the TCP socket stays ESTABLISHED forever otherwise, because the ESP32
# never sends a FIN, and the node would sit in recv() until restarted.
STALL_TIMEOUT_S = 3.0


class CPXLink:
    def __init__(self, deck_ip="192.168.4.1", deck_port=5000, on_jpeg=None, on_tof=None,
                 stall_timeout_s=STALL_TIMEOUT_S):
        self.deck_ip = deck_ip
        self.deck_port = deck_port
        self.stall_timeout_s = float(stall_timeout_s)
        self.reconnects = 0
        self.on_jpeg = on_jpeg      # on_jpeg(jpeg_bytes, seq)
        self.on_tof = on_tof        # on_tof(package_dict)
        self.connected = False
        self._running = True
        self._thread = None

        # jpeg assembly state
        self._img_collecting = False
        self._img_size = 0
        self._img_format = 0
        self._img_stream = bytearray()
        self._img_count = 0

        # tof state
        self._tof_assembler = protocol.TofFrameAssembler()
        self._tof_frame_count = 0
        self._tof_start_time = None
        self._tof_last_time = time.time()

    def start(self):
        self._thread = threading.Thread(name="CPXLinkThread", target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            try:
                print(f"[CPX] Connecting to {self.deck_ip}:{self.deck_port}...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.deck_ip, self.deck_port))
                sock.settimeout(self.stall_timeout_s)
                print("[CPX] Connected")
                self.connected = True
                self._img_collecting = False
                self._tof_assembler = protocol.TofFrameAssembler()
                self._read_loop(sock)
            except socket.timeout:
                self.reconnects += 1
                print(f"[CPX] No data for {self.stall_timeout_s:.0f}s (deck off / rebooting?), reconnecting")
            except (OSError, ConnectionError) as e:
                self.reconnects += 1
                print(f"[CPX] Connection lost: {e}")
            finally:
                self.connected = False
                try:
                    sock.close()
                except Exception:
                    pass
            if self._running:
                time.sleep(1.0)

    def _read_loop(self, sock):
        while self._running:
            hdr = protocol.rx_bytes(sock, 4)
            length, route0, route1 = struct.unpack('<HBB', hdr)
            payload = protocol.rx_bytes(sock, length - 2) if length > 2 else b''

            src, _dst, function = protocol.parse_cpx_route(route0, route1)

            if src == protocol.CPX_SRC_GAP8:
                self._handle_gap8(payload)
            elif src == protocol.CPX_SRC_STM32 and function == protocol.CPX_F_APP:
                self._handle_stm32(payload)
            # anything else (console prints etc.) is ignored

    def _handle_gap8(self, payload):
        if not self._img_collecting:
            # expect the img_header_t info packet (magic 0xBC)
            if len(payload) == IMG_HEADER.size and payload[0] == 0xBC:
                magic, width, height, depth, fmt, size = IMG_HEADER.unpack(payload)
                self._img_size = size
                self._img_format = fmt
                self._img_stream = bytearray()
                self._img_collecting = True
            return

        self._img_stream.extend(payload)
        if len(self._img_stream) >= self._img_size:
            self._img_collecting = False
            self._img_count += 1
            if self._img_format != 0 and self.on_jpeg is not None:
                self.on_jpeg(bytes(self._img_stream[:self._img_size]), self._img_count)

    def _handle_stm32(self, payload):
        frame = self._tof_assembler.add_chunk(payload)
        if frame is None:
            return
        seq, timestamp_ms, dist_bytes, status_bytes = frame

        matrix, validity = protocol.tof_arrays_from_raw(dist_bytes, status_bytes)

        # fps bookkeeping, same fields the PC link client fills in
        now = time.time()
        if self._tof_start_time is None:
            self._tof_start_time = now
        dt = now - self._tof_last_time
        self._tof_last_time = now
        self._tof_frame_count += 1
        total_elapsed = now - self._tof_start_time
        fps_inst = 1.0 / dt if dt > 0 else 0.0
        fps_avg = self._tof_frame_count / total_elapsed if total_elapsed > 0 else 0.0

        package = {
            'matrix': matrix,
            'validity_matrix': validity,
            'metadata': {
                'seq': seq,
                'fps_inst': fps_inst,
                'fps_avg': fps_avg,
                't_mon': time.monotonic(),
                'timestamp_ms': timestamp_ms,
            },
            'raw': (dist_bytes, status_bytes),
        }

        if self.on_tof is not None:
            self.on_tof(package)
