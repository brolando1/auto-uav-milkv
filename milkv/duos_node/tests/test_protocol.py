# Round-trip checks for the wire protocol + a localhost loopback of the
# PCLink server and DuoLink-style frame parsing. Run with:
#   python3 -m duos_node.tests.test_protocol

import socket
import struct
import sys
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import numpy as np

from common import protocol
from duos_node.pc_link import PCLink


def test_json_roundtrip():
    state = {"p_gate_ema": 0.42, "yaw_rate": -0.1, "training": {"state": "idle"}}
    assert protocol.decode_json(protocol.encode_json(state)) == state


def test_jpeg_roundtrip():
    payload = protocol.encode_jpeg(7, 123.456, b"\xff\xd8fakejpeg\xff\xd9")
    seq, t_mon, jpeg = protocol.decode_jpeg(payload)
    assert seq == 7
    assert abs(t_mon - 123.456) < 1e-9
    assert jpeg == b"\xff\xd8fakejpeg\xff\xd9"


def test_tof_roundtrip():
    dist = np.arange(64, dtype='<u2') * 50
    status = np.full(64, 5, dtype=np.uint8)
    status[3] = 0
    payload = protocol.encode_tof(9, 1.5, dist.tobytes(), status.tobytes())
    seq, t_mon, matrix, validity = protocol.decode_tof(payload)
    assert seq == 9
    assert matrix.shape == (8, 8) and validity.shape == (8, 8)
    assert not validity.flat[3]
    assert matrix.flat[3] == 3000.0          # invalid -> clamped
    assert matrix.flat[10] == 10 * 50        # valid -> raw mm
    assert validity.flat[10]


def test_tof_assembler():
    dist = (np.arange(64, dtype='<u2') * 31).tobytes()
    status = np.full(64, 9, dtype=np.uint8).tobytes()
    asm = protocol.TofFrameAssembler()
    ts = 42

    def chunk(seq, idx, data):
        return bytes([protocol.TOF_MAGIC, seq, idx, 3]) + struct.pack('<I', ts) + data

    assert asm.add_chunk(chunk(1, 0, dist[0:64])) is None
    assert asm.add_chunk(chunk(1, 1, dist[64:128])) is None
    out = asm.add_chunk(chunk(1, 2, status))
    assert out is not None
    seq, timestamp_ms, dist_out, status_out = out
    assert seq == 1 and timestamp_ms == 42
    assert dist_out == dist and status_out == status

    # a chunk from a new frame drops the incomplete old one
    assert asm.add_chunk(chunk(2, 0, dist[0:64])) is None
    assert asm.add_chunk(chunk(3, 0, dist[0:64])) is None
    assert asm.add_chunk(chunk(3, 1, dist[64:128])) is None
    assert asm.add_chunk(chunk(3, 2, status)) is not None


def test_debug_roundtrip():
    tof = (np.arange(441, dtype=np.float32) / 100.0).reshape(21, 21)
    payload = protocol.encode_debug(3, 2.5, b"\xff\xd8jpg\xff\xd9", tof)
    seq, t_mon, jpg, tof_out = protocol.decode_debug(payload)
    assert seq == 3 and abs(t_mon - 2.5) < 1e-9
    assert jpg == b"\xff\xd8jpg\xff\xd9"
    assert tof_out.shape == (21, 21) and np.array_equal(tof_out, tof)


def test_pc_protocol_copy_in_sync():
    # pc/pc_node/protocol.py is a copy of common/protocol.py so the pc/ folder
    # is self-contained; the two must not drift apart
    pc_copy = APP_ROOT.parent / "pc" / "pc_node" / "protocol.py"
    if pc_copy.exists():
        assert pc_copy.read_text() == (APP_ROOT / "common" / "protocol.py").read_text(), \
            "pc/pc_node/protocol.py differs from milkv/common/protocol.py - copy it over"


def test_cpx_route():
    # dst=3 (wifi host), src=1 (stm32), function=5 (app)
    route0 = 3 | (1 << 3)
    route1 = 5
    src, dst, function = protocol.parse_cpx_route(route0, route1)
    assert (src, dst, function) == (1, 3, 5)


def test_pc_link_loopback():
    received_cmds = []
    link = PCLink(host="127.0.0.1", port=58990, on_command=received_cmds.append)
    link.start()
    time.sleep(0.2)

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", 58990))
    time.sleep(0.2)

    # duos -> pc
    link.publish(protocol.FRAME_STATE, protocol.encode_json({"p_gate_ema": 0.9}))
    frame_type, payload = protocol.recv_frame(client)
    assert frame_type == protocol.FRAME_STATE
    assert protocol.decode_json(payload)["p_gate_ema"] == 0.9

    # pc -> duos
    protocol.send_frame(client, protocol.FRAME_CMD, protocol.encode_json({"cmd": "ping", "t_pc": 1.0}))
    t0 = time.time()
    while not received_cmds and time.time() - t0 < 2.0:
        time.sleep(0.02)
    assert received_cmds and received_cmds[0]["cmd"] == "ping"

    # latest-wins: nothing reading, publish twice, only newest arrives
    link.publish(protocol.FRAME_TOF, b"old")
    link.publish(protocol.FRAME_TOF, b"new")
    frame_type, payload = protocol.recv_frame(client)
    assert frame_type == protocol.FRAME_TOF
    assert payload in (b"old", b"new")  # timing dependent, but usually "new"

    client.close()
    link.stop()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"{t.__name__}: OK")
    print("all protocol tests passed")
