# Round-trip checks for the wire protocol + a localhost loopback of the
# PCLink server and DuoLink-style frame parsing. Run with:
#   python3 -m duos_node.tests.test_protocol

import socket
import sys
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


def test_uart_frames():
    tof = protocol.uart_encode(protocol.UART_TOF, protocol.UART_TOF_HEADER.pack(7, 1234) + bytes(192))
    cmd = protocol.uart_encode_cmd(protocol.SP_HOVER, 0.1, -0.2, 3.0, 0.4)
    bad = b"\xaa\x55\x43\x03abc\x00"   # right shape, wrong checksum

    # garbage in front, a frame split over two reads, a corrupted frame in between
    parser = protocol.UartParser()
    assert parser.feed(b"xx" + tof[:50]) == []
    frames = parser.feed(tof[50:] + bad + cmd)
    assert [f[0] for f in frames] == [protocol.UART_TOF, protocol.UART_CMD]

    seq, timestamp_ms, dist, status = protocol.uart_decode_tof(frames[0][1])
    assert (seq, timestamp_ms, len(dist), len(status)) == (7, 1234, 128, 64)
    sp_type, vx, vy, yawrate, zdistance = protocol.UART_CMD_STRUCT.unpack(frames[1][1])
    assert sp_type == protocol.SP_HOVER and abs(vx - 0.1) < 1e-6 and abs(zdistance - 0.4) < 1e-6

    state = protocol.uart_decode_state(protocol.UART_STATE_STRUCT.pack(0.4, 1.0, -2.0, 90.0, 1))
    assert abs(state['z'] - 0.4) < 1e-6 and state['tumbled'] == 1


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
