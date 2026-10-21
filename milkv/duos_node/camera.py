# Cameras on the Duo S: GC2083 through the vendor middleware (libmaixcam_lib),
# VD55G1 through our own driver in milkv/vd55g1. Both deliver 324x244
# grayscale frames like the AI-deck camera did, so the rest of the node stays
# the same.

import ctypes
from ctypes import c_int, c_void_p, POINTER, byref
import os
import threading

import cv2
import numpy as np

LIB_DIR = "/mnt/system/usr/lib"
# the vendor libs depend on each other in a circle, loading the list twice resolves everything
VENDOR_LIBS = [
    "libsys.so", "libisp.so", "libisp_algo.so", "libae.so", "libaf.so", "libawb.so",
    "libcvi_bin.so", "libcvi_bin_isp.so", "libcvi_ispd2.so", "libsns_full.so", "libsns_gc2083.so",
    "libvi.so", "libvpss.so", "libvenc.so", "libvdec.so", "libvo.so", "libgdc.so", "librgn.so",
    "libosdc.so", "libmisc.so", "libcvi_ive.so", "libsample.so",
]

# The hardware scaler delivers 16:9, width a multiple of 64. 448x252 is the
# smallest grab that contains the 324x244 frame, which is then a plain centre
# cut (no cv2.resize, ~12 ms/frame on this core). Field of view is 3.6%
# narrower than the old 640x360 grab + resize path, the pixel scale the same.
GRAB_W, GRAB_H = 448, 252
OUT_W, OUT_H = 324, 244     # AI-deck frame size
NV21 = 19                   # gray plane first in the buffer


class Camera:
    def __init__(self, on_frame, frame_wanted=None):
        self.on_frame = on_frame    # on_frame(gray_244x324, seq)
        # frame_wanted(seq) -> bool: frames it declines are dropped right after the
        # pop, without the copy/resize/on_frame (the node uses this to idle the
        # camera thread while a finetune runs)
        self.frame_wanted = frame_wanted
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(name="CameraThread", target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread.join(timeout=3.0)

    def _open(self):
        mode = ctypes.RTLD_GLOBAL | 1   # 1 = RTLD_LAZY
        ctypes.CDLL("libstdc++.so.6", mode=mode)
        ctypes.CDLL(f"{LIB_DIR}/3rd/libini.so", mode=mode)
        for _ in range(2):
            for name in VENDOR_LIBS:
                try:
                    ctypes.CDLL(f"{LIB_DIR}/{name}", mode=mode)
                except OSError:
                    pass
        lib = ctypes.CDLL(f"{LIB_DIR}/libmaixcam_lib.so", mode=mode)
        # C++ library, mangled names
        self._deinit = lib._Z10mmf_deinitv
        self._pop = lib._Z16mmf_vi_frame_popiPPvPiS1_S1_S1_
        self._pop.argtypes = [c_int, POINTER(c_void_p)] + [POINTER(c_int)] * 4
        self._free = lib._Z17mmf_vi_frame_freei
        self._free.argtypes = [c_int]
        self._del = lib._Z18mmf_del_vi_channeli
        self._del.argtypes = [c_int]
        add = lib._Z18mmf_add_vi_channeliiii
        add.argtypes = [c_int] * 4
        set_timeout = lib._Z22mmf_vi_set_pop_timeouti
        set_timeout.argtypes = [c_int]

        if lib._Z8mmf_initv() != 0:
            raise RuntimeError("mmf_init failed")
        if lib._Z11mmf_vi_initv() != 0:
            self._deinit()
            raise RuntimeError("mmf_vi_init failed, camera connected?")
        set_timeout(500)
        self._ch = lib._Z25mmf_get_vi_unused_channelv()
        if add(self._ch, GRAB_W, GRAB_H, NV21) != 0:
            self._deinit()
            raise RuntimeError("mmf_add_vi_channel failed")

    def _run(self):
        try:
            self._open()
        except Exception as e:
            print(f"[CAM] {e}")
            return
        print("[CAM] GC2083 running")
        data, length = c_void_p(), c_int()
        w, h, fmt = c_int(), c_int(), c_int()
        seq = 0
        while self._running:
            if self._pop(self._ch, byref(data), byref(length), byref(w), byref(h), byref(fmt)) != 0:
                continue    # timeout
            seq += 1
            if self.frame_wanted is not None and not self.frame_wanted(seq):
                self._free(self._ch)
                continue
            # w is the stride the driver picked, it rounds widths up
            y = np.frombuffer(ctypes.string_at(data.value, w.value * h.value), dtype=np.uint8).reshape(h.value, w.value)
            self._free(self._ch)
            if OUT_H <= h.value <= GRAB_H and w.value >= OUT_W:
                # the grab is the small one: centre cut, no resize
                y0 = (h.value - OUT_H) // 2
                x0 = (w.value - OUT_W) // 2
                frame = np.ascontiguousarray(y[y0:y0 + OUT_H, x0:x0 + OUT_W])
                mode = "centre cut"
            else:
                # the driver delivered something else (bigger): 4:3 centre cut + resize
                cut = h.value * 4 // 3
                x0 = (w.value - cut) // 2
                frame = cv2.resize(y[:, x0:x0 + cut], (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
                mode = "4:3 cut + resize"
            if seq == 1:
                print(f"[CAM] driver delivers {w.value}x{h.value} (asked {GRAB_W}x{GRAB_H}) -> {OUT_W}x{OUT_H} by {mode}")
            self.on_frame(frame, seq)
        self._del(self._ch)
        self._deinit()


VD55G1_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vd55g1", "build", "libvd55cam.so")


class Vd55g1Camera:
    # ST VD55G1 on the J2 connector, through milkv/vd55g1 (Sophgo sensor driver,
    # ISP with auto-exposure, hardware scaler). The library delivers the
    # 324x244 gray frame directly. Needs `make -C vd55g1` and the camera power
    # on (vd55g1/board/vd55g1-power.sh on, or the systemd unit).
    def __init__(self, on_frame, frame_wanted=None, fps=30.0):
        self.on_frame = on_frame
        self.frame_wanted = frame_wanted
        self.fps = fps
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(name="CameraThread", target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread.join(timeout=3.0)

    def _run(self):
        try:
            lib = ctypes.CDLL(VD55G1_LIB)
        except OSError as e:
            print(f"[CAM] {e} (build it on the board: make -C vd55g1)")
            return
        lib.vd55cam_open.argtypes = [c_int, c_int, ctypes.c_float, c_int]
        lib.vd55cam_read.argtypes = [c_void_p, c_int]
        lib.vd55cam_read.restype = ctypes.c_int64
        if lib.vd55cam_open(OUT_W, OUT_H, self.fps, 0) != 0:
            print("[CAM] vd55cam_open failed, camera power on? (vd55g1/board/vd55g1-power.sh on)")
            return
        print(f"[CAM] VD55G1 running, {OUT_W}x{OUT_H} at {self.fps:.0f} fps")
        buf = np.empty((OUT_H, OUT_W), dtype=np.uint8)
        seq = 0
        try:
            while self._running:
                n = lib.vd55cam_read(buf.ctypes.data, 500)
                if n < 0:
                    print("[CAM] vd55cam_read failed")
                    break
                if n == 0:
                    continue    # timeout
                seq += 1
                if self.frame_wanted is not None and not self.frame_wanted(seq):
                    continue
                self.on_frame(buf.copy(), seq)
        finally:
            lib.vd55cam_close()


class FakeCamera:
    # random 324x244 frames at 30 fps, for running the node without a camera
    def __init__(self, on_frame, frame_wanted=None):
        self.on_frame = on_frame
        self.frame_wanted = frame_wanted
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(name="CameraThread", target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread.join(timeout=3.0)

    def _run(self):
        import time
        print("[CAM] fake camera running (random frames)")
        seq = 0
        while self._running:
            time.sleep(1 / 30)
            seq += 1
            if self.frame_wanted is not None and not self.frame_wanted(seq):
                continue
            self.on_frame(np.random.randint(0, 256, (OUT_H, OUT_W), dtype=np.uint8), seq)


CAMERAS = {"gc2083": Camera, "vd55g1": Vd55g1Camera}


if __name__ == "__main__":
    # quick check: python3 -m duos_node.camera [gc2083|vd55g1]
    # prints the frame rate, last frame lands in /tmp
    import sys
    import time
    stamps, last = [], []

    def on_frame(gray, seq):
        stamps.append(time.monotonic())
        last[:] = [gray]

    cam = CAMERAS[sys.argv[1] if len(sys.argv) > 1 else "gc2083"](on_frame)
    cam.start()
    time.sleep(8)
    cam.stop()
    if not last:
        sys.exit("no frames")
    cv2.imwrite("/tmp/cam_last.png", last[0])
    print(f"{len(stamps)} frames, {(len(stamps) - 1) / (stamps[-1] - stamps[0]):.1f} fps, last frame in /tmp/cam_last.png")
