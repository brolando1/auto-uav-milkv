# Connects to the AI-deck socket and counts CPX packets per source for a few
# seconds. Stop duos_node.main first: the ESP32 only serves one client.
#   python3 tools/cpx_probe.py [--ip 192.168.4.1] [--seconds 10]
import argparse, os, socket, struct, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "milkv"))
from common import protocol

ap = argparse.ArgumentParser()
ap.add_argument("--ip", default="192.168.4.1")
ap.add_argument("--port", type=int, default=5000)
ap.add_argument("--seconds", type=float, default=10.0)
a = ap.parse_args()

names = {protocol.CPX_SRC_STM32: "STM32", protocol.CPX_SRC_GAP8: "GAP8"}
counts, tof_frames = {}, 0
asm = protocol.TofFrameAssembler()
print(f"connecting to {a.ip}:{a.port} ...")
s = socket.create_connection((a.ip, a.port), timeout=5)
s.settimeout(2.0)
print("connected, listening", a.seconds, "s")
t_end = time.time() + a.seconds
while time.time() < t_end:
    try:
        hdr = protocol.rx_bytes(s, 4)
    except socket.timeout:
        print("  (no packets for 2 s)")
        continue
    length, r0, r1 = struct.unpack('<HBB', hdr)
    payload = protocol.rx_bytes(s, length - 2) if length > 2 else b''
    src, _dst, fn = protocol.parse_cpx_route(r0, r1)
    key = (names.get(src, f"src{src}"), fn)
    counts[key] = counts.get(key, 0) + 1
    if src == protocol.CPX_SRC_STM32 and fn == protocol.CPX_F_APP:
        if asm.add_chunk(payload) is not None:
            tof_frames += 1
s.close()
print("\npackets per (source, function):")
for (src, fn), n in sorted(counts.items()):
    print(f"  {src:6s} fn={fn}: {n}")
print(f"\ncomplete ToF frames: {tof_frames}  ({tof_frames / a.seconds:.1f} Hz)")
if tof_frames == 0:
    print("no ToF over CPX -> check the STM32 firmware/flash (TOF_OVER_CPX)")
