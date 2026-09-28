# Wire protocol shared between the Duo S node and the PC ground station, plus
# the framing of the serial link between the Duo S and the Crazyflie.
#
# Duo S <-> PC framing (TCP, little-endian):
#   header: <IB  = payload_length (u32), frame_type (u8)
#   payload depends on frame_type, see below.
#
# Duo S <-> Crazyflie framing (UART1 of the expansion port, 115200 8N1):
#   AA 55 | type (u8) | len (u8) | payload | xor of type, len and payload
# The STM32 side of this lives in app-tof-logger-tof/src/main_tof.c.

import json
import struct

import numpy as np

# ---------------- Duo S <-> PC frame types ----------------
FRAME_STATE = 0x01     # JSON: predictions + fps + training status (per inference)
FRAME_JPEG = 0x02      # <Id (seq, t_duo_mon) + raw jpeg bytes
FRAME_TOF = 0x03       # <Id (seq, t_duo_mon) + 128B u16 distances + 64B status
FRAME_DEBUG = 0x05     # <Id (seq, t_duo_mon) + <I jpeg_len + jpeg of the camera model input (168x168 u8)
                       # + 21x21 float32 ToF model input (Duo S -> PC, only while the viewer asks for it)
FRAME_CMD = 0x10       # JSON: {"cmd": ..., ...}  (PC -> Duo S: keys, dump, ping, ...)

# setpoint types, sent to the drone in the UART command frames
SP_HOVER = 1    # hover setpoint (vx, vy, yawrate, zdistance)
SP_STOP = 2     # motors off
SP_UNLOCK = 3   # arm and keep the commander alive with a zero setpoint

LINK_HEADER = struct.Struct('<IB')
SEQ_T_HEADER = struct.Struct('<Id')

# ---------------- Duo S <-> Crazyflie serial frames ----------------
UART_SYNC = b'\xaa\x55'
UART_TOF = 0x54     # 'T' STM32 -> Duo S: <BI seq, timestamp_ms + 128B u16 distances + 64B status
UART_STATE = 0x53   # 'S' STM32 -> Duo S: <ffffB z, roll, pitch, yaw, tumbled
UART_CMD = 0x43     # 'C' Duo S -> STM32: <Bffff sp_type (SP_*), vx, vy, yawrate, zdistance

UART_TOF_HEADER = struct.Struct('<BI')
UART_TOF_LEN = UART_TOF_HEADER.size + 128 + 64
UART_STATE_STRUCT = struct.Struct('<ffffB')
UART_CMD_STRUCT = struct.Struct('<Bffff')


def rx_bytes(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data.extend(chunk)
    return bytes(data)


# ---------------- Duo S <-> PC link helpers ----------------
def send_frame(sock, frame_type, payload):
    sock.sendall(LINK_HEADER.pack(len(payload), frame_type) + payload)


def recv_frame(sock):
    hdr = rx_bytes(sock, LINK_HEADER.size)
    length, frame_type = LINK_HEADER.unpack(hdr)
    payload = rx_bytes(sock, length) if length > 0 else b''
    return frame_type, payload


def encode_json(obj):
    return json.dumps(obj).encode('utf-8')


def decode_json(payload):
    return json.loads(payload.decode('utf-8'))


def encode_jpeg(seq, t_mon, jpeg_bytes):
    return SEQ_T_HEADER.pack(int(seq) & 0xFFFFFFFF, float(t_mon)) + bytes(jpeg_bytes)


def decode_jpeg(payload):
    seq, t_mon = SEQ_T_HEADER.unpack_from(payload, 0)
    return seq, t_mon, payload[SEQ_T_HEADER.size:]


def encode_tof(seq, t_mon, dist_bytes, status_bytes):
    # dist_bytes: 128B raw u16-LE mm, status_bytes: 64B raw status
    return SEQ_T_HEADER.pack(int(seq) & 0xFFFFFFFF, float(t_mon)) + bytes(dist_bytes) + bytes(status_bytes)


def decode_tof(payload):
    seq, t_mon = SEQ_T_HEADER.unpack_from(payload, 0)
    off = SEQ_T_HEADER.size
    dist_bytes = payload[off:off + 128]
    status_bytes = payload[off + 128:off + 192]
    matrix, validity = tof_arrays_from_raw(dist_bytes, status_bytes)
    return seq, t_mon, matrix, validity


def encode_debug(seq, t_mon, cam_jpeg_bytes, tof_norm_21):
    # cam_jpeg_bytes: jpeg of the 168x168 uint8 camera model input,
    # tof_norm_21: 21x21 float32 standardized ToF model input
    tof = np.ascontiguousarray(tof_norm_21, dtype=np.float32)
    return (SEQ_T_HEADER.pack(int(seq) & 0xFFFFFFFF, float(t_mon))
            + struct.pack('<I', len(cam_jpeg_bytes)) + bytes(cam_jpeg_bytes) + tof.tobytes())


def decode_debug(payload):
    # returns (seq, t_duo_mon, cam_jpeg_bytes, tof_norm_21x21 float32)
    seq, t_mon = SEQ_T_HEADER.unpack_from(payload, 0)
    off = SEQ_T_HEADER.size
    (jpeg_len,) = struct.unpack_from('<I', payload, off)
    off += 4
    cam_jpeg = payload[off:off + jpeg_len]
    off += jpeg_len
    tof_norm = np.frombuffer(payload[off:off + 21 * 21 * 4], dtype='<f4').reshape(21, 21)
    return seq, t_mon, cam_jpeg, tof_norm


def tof_arrays_from_raw(dist_bytes, status_bytes):
    # status 5/9 is valid, invalid pixels get clamped to 3000mm (max range 3.0m)
    distances = np.frombuffer(dist_bytes, dtype='<u2').astype(np.float32).reshape(8, 8)
    status = np.frombuffer(status_bytes, dtype=np.uint8).reshape(8, 8)
    validity = (status == 5) | (status == 9)
    matrix = np.where(validity, distances, 3000.0).astype(np.float32)
    return matrix, validity


# ---------------- serial link helpers ----------------
def uart_checksum(data):
    x = 0
    for b in data:
        x ^= b
    return x


def uart_encode(frame_type, payload):
    body = bytes([frame_type, len(payload)]) + bytes(payload)
    return UART_SYNC + body + bytes([uart_checksum(body)])


def uart_encode_cmd(sp_type, vx=0.0, vy=0.0, yawrate=0.0, zdistance=0.0):
    return uart_encode(UART_CMD, UART_CMD_STRUCT.pack(sp_type, vx, vy, yawrate, zdistance))


def uart_decode_tof(payload):
    # returns (seq, timestamp_ms, dist_bytes, status_bytes)
    seq, timestamp_ms = UART_TOF_HEADER.unpack_from(payload, 0)
    off = UART_TOF_HEADER.size
    return seq, timestamp_ms, payload[off:off + 128], payload[off + 128:off + 192]


def uart_decode_state(payload):
    z, roll, pitch, yaw, tumbled = UART_STATE_STRUCT.unpack(payload)
    return {'z': z, 'roll': roll, 'pitch': pitch, 'yaw': yaw, 'tumbled': tumbled}


class UartParser:
    # feed it whatever came in from the port and get the complete frames back;
    # bytes before a sync marker and frames with a bad checksum are dropped
    def __init__(self):
        self._buf = bytearray()

    def feed(self, data):
        self._buf.extend(data)
        frames = []
        while True:
            start = self._buf.find(UART_SYNC)
            if start < 0:
                del self._buf[:-1]    # keep the last byte, it may be half a marker
                break
            del self._buf[:start]
            if len(self._buf) < 4:
                break
            length = self._buf[3]
            end = 4 + length + 1
            if len(self._buf) < end:
                break
            body = bytes(self._buf[2:4 + length])
            if uart_checksum(body) == self._buf[4 + length]:
                frames.append((body[0], body[2:]))
                del self._buf[:end]
            else:
                del self._buf[:2]
        return frames
