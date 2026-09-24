# Wire protocol shared between the Duo S node and the PC ground station,
# plus the CPX framing constants for the AI-deck socket (192.168.4.1:5000).
#
# Duo S <-> PC framing (TCP, little-endian):
#   header: <IB  = payload_length (u32), frame_type (u8)
#   payload depends on frame_type, see below.
#
# CPX wire framing on the AI-deck socket (see lib/cpx/src/cpx.c):
#   <H  wireLength (= payload + 2 route bytes)
#   B   route0 = dst:3 | src:3 | lastPacket:1 | reserved:1
#   B   route1 = function:6 | version:2

import json
import struct

import numpy as np

# ---------------- Duo S <-> PC frame types ----------------
FRAME_STATE = 0x01     # JSON: predictions + fps + training status (per inference)
FRAME_JPEG = 0x02      # <Id (seq, t_duo_mon) + raw jpeg bytes
FRAME_TOF = 0x03       # <Id (seq, t_duo_mon) + 128B u16 distances + 64B status
FRAME_SETPOINT = 0x04  # <Bffffd: sp_type, vx, vy, yawrate, zdistance, t_duo_mon
                       # (Duo S flight controller -> PC radio bridge)
FRAME_DEBUG = 0x05     # <Id (seq, t_duo_mon) + <I jpeg_len + jpeg of the camera model input (168x168 u8)
                       # + 21x21 float32 ToF model input (Duo S -> PC, only while the viewer asks for it)
FRAME_CMD = 0x10       # JSON: {"cmd": ..., ...}  (PC -> Duo S: keys, telemetry, dump, ping, ...)

# setpoint types executed by the PC radio bridge
SP_HOVER = 1    # commander.send_hover_setpoint(vx, vy, yawrate, zdistance)
SP_STOP = 2     # commander.send_stop_setpoint()
SP_UNLOCK = 3   # commander.send_setpoint(0, 0, 0, 0)

LINK_HEADER = struct.Struct('<IB')
SEQ_T_HEADER = struct.Struct('<Id')
SETPOINT_STRUCT = struct.Struct('<Bffffd')

# ---------------- CPX constants ----------------
CPX_SRC_STM32 = 1
CPX_SRC_GAP8 = 4
CPX_F_APP = 5

# ToF app packet from the STM32 (main_tof.c, TOF_OVER_CPX). The UART2 CPX link
# caps the payload at ~100B so one 8x8 frame is split into 3 chunks:
#   [0] magic 0x54 ('T'), [1] frame seq, [2] chunk idx (0..2), [3] n chunks (3),
#   [4:8] timestamp_ms u32, [8:72] 64 bytes of data
#   chunk 0: distance_mm[0:32]  (bytes 0:64)
#   chunk 1: distance_mm[32:64] (bytes 64:128)
#   chunk 2: target_status[0:64]
TOF_MAGIC = 0x54
TOF_CHUNKS = 3
TOF_CHUNK_DATA = 64
TOF_CHUNK_LEN = 8 + TOF_CHUNK_DATA


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


def encode_setpoint(sp_type, vx=0.0, vy=0.0, yawrate=0.0, zdistance=0.0, t_mon=None):
    if t_mon is None:
        import time
        t_mon = time.monotonic()
    return SETPOINT_STRUCT.pack(sp_type, float(vx), float(vy), float(yawrate), float(zdistance), float(t_mon))


def decode_setpoint(payload):
    # returns (sp_type, vx, vy, yawrate, zdistance, t_duo_mon)
    return SETPOINT_STRUCT.unpack(payload)


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


# ---------------- CPX side (AI-deck socket) ----------------
def parse_cpx_route(route0, route1):
    src = (route0 >> 3) & 0x07
    dst = route0 & 0x07
    function = route1 & 0x3F
    return src, dst, function


def parse_tof_chunk(payload):
    # Returns (seq, chunk_idx, n_chunks, timestamp_ms, data64) or None if not ours
    if len(payload) != TOF_CHUNK_LEN or payload[0] != TOF_MAGIC:
        return None
    seq = payload[1]
    chunk_idx = payload[2]
    n_chunks = payload[3]
    (timestamp_ms,) = struct.unpack_from('<I', payload, 4)
    return seq, chunk_idx, n_chunks, timestamp_ms, payload[8:]


class TofFrameAssembler:
    """Reassembles the 3 CPX chunks of one ToF frame (keyed by the frame seq)."""

    def __init__(self):
        self._seq = None
        self._chunks = {}
        self._timestamp_ms = 0

    def add_chunk(self, payload):
        # Returns (seq, timestamp_ms, dist_bytes, status_bytes) when a frame
        # completes, else None.
        parsed = parse_tof_chunk(payload)
        if parsed is None:
            return None
        seq, chunk_idx, n_chunks, timestamp_ms, data = parsed
        if n_chunks != TOF_CHUNKS or chunk_idx >= TOF_CHUNKS:
            return None

        if seq != self._seq:
            self._seq = seq
            self._chunks = {}
        self._chunks[chunk_idx] = data
        self._timestamp_ms = timestamp_ms

        if len(self._chunks) == TOF_CHUNKS:
            dist_bytes = self._chunks[0] + self._chunks[1]
            status_bytes = self._chunks[2]
            self._chunks = {}
            self._seq = None
            return seq, self._timestamp_ms, dist_bytes, status_bytes
        return None
