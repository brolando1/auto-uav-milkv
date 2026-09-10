# Fakes the AI-deck socket for bench testing without the drone: serves the
# same CPX wire format on localhost:5000, with jpeg frames "from the GAP8"
# (~10Hz) and 3-chunk ToF frames "from the STM32" (15Hz).
#
#   python3 -m duos_node.tests.fake_cpx_server
# then point duos_node at it:
#   python3 -m duos_node.main -n 127.0.0.1 --ckpt <model.pt>

import argparse
import socket
import struct
import sys
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import cv2
import numpy as np

from common import protocol

IMG_HEADER = struct.Struct('<BHHBBI')
CPX_MTU_PAYLOAD = 1020


def cpx_pack(src, dst, function, payload):
    route0 = (dst & 0x07) | ((src & 0x07) << 3)
    route1 = function & 0x3F
    return struct.pack('<HBB', len(payload) + 2, route0, route1) + payload


def make_jpeg(t):
    # moving blob so the viewer shows motion
    img = np.zeros((168, 168), dtype=np.uint8)
    cx = int(84 + 60 * np.sin(t * 1.5))
    cy = int(84 + 60 * np.cos(t * 0.9))
    cv2.circle(img, (cx, cy), 30, 200, -1)
    cv2.putText(img, f"{t:.1f}", (10, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 255, 1)
    ok, jpeg = cv2.imencode('.jpg', img)
    return jpeg.tobytes()


def make_tof(t):
    # gradient + a moving "obstacle", a few invalid pixels
    dist = np.full((8, 8), 2000, dtype=np.uint16)
    col = int(4 + 3 * np.sin(t))
    dist[:, col] = 600
    status = np.full((8, 8), 5, dtype=np.uint8)
    status[0, 0] = 0  # invalid corner
    return dist.tobytes(), status.tobytes()


def send_jpeg(sock, jpeg_bytes):
    header = IMG_HEADER.pack(0xBC, 168, 168, 1, 1, len(jpeg_bytes))
    sock.sendall(cpx_pack(protocol.CPX_SRC_GAP8, 3, protocol.CPX_F_APP, header))
    for off in range(0, len(jpeg_bytes), CPX_MTU_PAYLOAD):
        chunk = jpeg_bytes[off:off + CPX_MTU_PAYLOAD]
        sock.sendall(cpx_pack(protocol.CPX_SRC_GAP8, 3, protocol.CPX_F_APP, chunk))


def send_tof(sock, seq, dist_bytes, status_bytes):
    ts = int(time.monotonic() * 1000) & 0xFFFFFFFF
    for idx in range(protocol.TOF_CHUNKS):
        if idx < 2:
            data = dist_bytes[idx * 64:(idx + 1) * 64]
        else:
            data = status_bytes
        payload = bytes([protocol.TOF_MAGIC, seq & 0xFF, idx, protocol.TOF_CHUNKS]) + struct.pack('<I', ts) + data
        sock.sendall(cpx_pack(protocol.CPX_SRC_STM32, 3, protocol.CPX_F_APP, payload))


def serve_client(sock, cam_hz, tof_hz):
    print("[FAKE] Client connected")
    t0 = time.time()
    next_cam = 0.0
    next_tof = 0.0
    tof_seq = 0
    try:
        while True:
            now = time.time() - t0
            if now >= next_tof:
                dist, status = make_tof(now)
                send_tof(sock, tof_seq, dist, status)
                tof_seq += 1
                next_tof = now + 1.0 / tof_hz
            if now >= next_cam:
                send_jpeg(sock, make_jpeg(now))
                next_cam = now + 1.0 / cam_hz
            time.sleep(0.002)
    except (OSError, ConnectionError):
        print("[FAKE] Client disconnected")
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser(description="Fake AI-deck CPX stream for bench tests")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--cam_hz", type=float, default=10.0)
    parser.add_argument("--tof_hz", type=float, default=15.0)
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(1)
    print(f"[FAKE] AI-deck fake listening on {args.host}:{args.port}")
    while True:
        client, addr = server.accept()
        threading.Thread(target=serve_client, args=(client, args.cam_hz, args.tof_hz), daemon=True).start()


if __name__ == "__main__":
    main()
