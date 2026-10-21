# VD55G1 driver for the Milk-V Duo S

Driver for the ST VD55G1 (ST PCB4189 board) on the Duo S **J2** camera connector, built into the Sophgo media stack the same way the vendor's own sensors are:

```
VD55G1 --MIPI 1 lane, RAW8--> MIPI RX -> VI -> ISP (mono, Sophgo AE) -> VPSS scaler -> 324x244 gray
   ^                                           |
   +---- exposure / gain / frame length -------+  (ISP I2C sync, every frame)
```

| Part | What |
|---|---|
| `build/libsns_vd55g1.so` | Sensor driver: `stSnsVd55g1_Obj`, the same kind of object as `libsns_gc2083.so`. Boots the sensor, uploads the firmware patch, configures MIPI and window, exposure/gain callbacks for the Sophgo AE. |
| `build/libvd55cam.so` | Capture library: sensor + VI + ISP + VPSS, plain C API (`cam/vd55cam.h`). `duos_node/camera.py` (`Vd55g1Camera`) uses it via ctypes. |
| `build/vd55cam_test` | Frame rate, exposure and gain once a second, saves the last frame as PGM. |
| `build/vd55g1_ctl` | I2C-only sensor check (`status`, `probe`, `start`, `stop`). |

The vendor `libmaixcam_lib.so` only knows the sensors compiled into it, which is why the capture library exists.

## Setup (on the board)

```
cd ~/milkv/vd55g1
make
sudo cp board/vd55g1-power.service /etc/systemd/system/
sudo systemctl enable --now vd55g1-power      # I2C2 pin mux + camera power, at every boot
sudo build/vd55cam_test                       # 5 s: ~30 fps, exposure/gain, /tmp/vd55cam_last.pgm
```

Without the unit: `sudo board/vd55g1-power.sh on` once after every boot.

The node: `sudo python3 -u -m duos_node.main --camera vd55g1 ...`. Camera only: `sudo python3 -m duos_node.camera vd55g1`.

## Modes

| | Sensor window | Output |
|---|---|---|
| default | 768x576, centre of the 804x704 array (4:3) | any size via the VPSS, the node asks for 324x244 |
| `VD55CAM_FULL_HEIGHT` | 768x704 | same |

- 1.4 to 60 fps (frame length), 30 fps in the node. RAW8, 1 lane at 600 Mbit/s, 12 us line.
- Exposure: Sophgo AE, sensor in manual mode. Up to frame length - 64 lines, analog gain 1-8x, sensor digital gain 1-4x, ISP digital gain up to 2x.
- Tone: sRGB gamma. The ISP's adaptive tone mapping (DRC, local contrast, dehaze) is off, so the same brightness gives the same gray value in every scene. `VD55CAM_ISP_TONE` switches it back on. There is no ISP tuning file for this sensor, the rest of the ISP runs on its defaults.
- Test pattern: `VD55G1_PATTERN=1` (grey ramp) or `2` (noise) in the environment.

`vd55cam_test -R raw.pgm` also saves one raw sensor frame (before the ISP), useful to tell sensor problems from ISP problems.

## Notes

- The window width must be a multiple of 64: the ISP reads the raw frame with the width rounded up to 64 pixels while the VI writes it unpadded. At 800 px wide every line shifts by 32 pixels (diagonal stripes).
- The line must be at least as long as its MIPI transfer, otherwise the sensor stops in an error state (`vd55g1_ctl status` shows state 0xff). `vd55g1.c: line_length_min()` rounds up for this. Only a power cycle gets it out: `sudo board/vd55g1-power.sh off && sudo board/vd55g1-power.sh on`.
- A process killed with `kill -9` leaves the VI/VPSS set up in the kernel; the next `vd55cam_open()` tears that down first, no reboot needed (tested).
- The kernel keeps the frame buffer pool of the first camera start after boot. `libvd55cam` asks for one big enough for both modes; if another program (the GC2083 path, the old capture tool) started first with smaller buffers, `VD55CAM_FULL_HEIGHT` fails with `CVI_VI_EnableChn ... 0xc00e8040` until a reboot. Check with `sudo cat /proc/cvitek/vb` (768x704 needs a block size of at least 811008).
- The vendor libraries do not link their own dependencies (`libm`, `libvo`, `libgdc`), `libvd55cam.so` links them so Python can load it.
- `sdk/`: Sophgo headers pinned to the board's library version (see `sdk/README.md`). The PC SDK in `duo-buildroot-sdk-v2` is a different version, its `ISP_SNS_OBJ_S` has a different layout.

## Files

- `sensor/vd55g1.c/.h`, `vd55g1_patch.h`: register access, boot, patch, configuration, ported from ST's GPL-2.0 Linux driver ([STMicroelectronics/vd55g1-linux-driver](https://github.com/STMicroelectronics/vd55g1-linux-driver))
- `sensor/vd55g1_cmos.c`, `vd55g1_cmos_param.h`, `vd55g1_cmos_ex.h`: sensor object, modes, AE/AWB callbacks (structure of the SDK's `sms_sc035gs_1L` driver)
- `sensor/vd55g1_sensor_ctl.c`: I2C, probe, init, standby/restart, flip
- `cam/vd55cam.c/.h`: capture library
- `tools/`: `vd55cam_test.c`, `vd55g1_ctl.c`
- `board/`: J2 pin mux + power script and its systemd unit
