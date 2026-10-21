# auto-uav-milkv

Autonomous gate flight with a Crazyflie 2.x and a ToF deck. Inference, flight control, crash detection and retraining run on a Milk-V Duo S with its own camera (CAM-GC2083). Duo S and Crazyflie talk over a UART wire. The PC only shows the viewer and forwards the keyboard.

```
GC2083 camera --CSI--> Duo S  <--UART1/ttyS2--> Crazyflie STM32 (ToF app)
                       | classifier + navigator       ToF 8x8 @15Hz, state @15Hz  -->
                       | control loop @33Hz,          <-- hover / stop / unlock setpoints
                       | obstacle avoidance,
                       | retrain-on-crash
                       | TCP server :5800 on the USB link
PC <---- jpeg / ToF / p_gate / yaw / training status -------- Duo S
PC ----- keys (space/i/wasd/qe/op/k) / dump / record / ping -> Duo S
```

- The camera delivers 324x244 grayscale at 30 fps, the size the AI-deck camera had, so the model input did not change. The scaler grabs 448x252 and the frame is a plain centre cut of it, no resize. The inference sees every frame, the viewer gets a jpeg of every third one (10 fps).
- ToF frames, drone state and setpoints go over the UART. No radio, no wifi.
- Duo S and PC talk over the USB network link (`10.2.250.1`).
- On a crash the Duo S dumps the ring buffer, finetunes the classifier on it and swaps the new model in while running.

## Repository layout

| Folder | Where it runs | What |
|---|---|---|
| `milkv/` | Duo S | `duos_node/` node, `common/` protocol + obstacle avoidance, `training_quantization/` models and training pipeline, `vd55g1/` VD55G1 camera driver |
| `pc/` | PC | `pc_node/` viewer, keyboard, link client |
| `tools/` | PC | deploy and drone check scripts, `duos/` board helpers |
| `app-tof-logger-tof/` | Crazyflie STM32 | ToF + UART link firmware |
| `wifi-img-streamer/`, `lib/` | AI-deck GAP8 | old camera streamer, not used anymore |

`milkv/common/protocol.py` and `pc/pc_node/protocol.py` must be identical, the protocol tests check that.

## Setup

### Wiring

Three wires between the Crazyflie expansion port and the Duo S header, both 3 V logic:

| Crazyflie, left row | Duo S header |
|---|---|
| pin 2 RX1 | pin 11 UART2 TX |
| pin 3 TX1 | pin 13 UART2 RX |
| pin 10 GND | pin 9 GND |

### Drone firmware

`app-tof-logger-tof`, set `CRAZYFLIE_BASE` in the `Makefile` (tested with crazyflie-firmware 2026.04), then

```
make clean && make
cfloader flash build/cf2.bin stm32-fw     # crazyflie in bootloader mode
```

The app reads the ToF sensor, sends ToF and state frames on UART1 and takes the setpoints from there. No AI-deck settings needed.

### Duo S

Debian image from https://github.com/scpcom/sophgo-sg200x-debian (Debian 13 riscv64, vendor 5.10 kernel). Login `debian`, password `rv`, reachable at `10.2.250.1` over USB. No pip wheels for riscv64, install from apt:

```
sudo apt-get install --no-install-recommends python3-numpy python3-opencv python3-torch python3-torchvision python3-onnxruntime python3-onnx
```

Internet on the board for apt: phone hotspot in `/boot/wpa_supplicant.conf`. Alternative: `bash tools/duos_proxy.sh` forwards an HTTP proxy from the PC, then `apt-get -o Acquire::http::Proxy=http://127.0.0.1:8899 ...`.

Camera: CAM-GC2083 on the narrow 16-pin connector J1. The image already has the sensor config (`/mnt/data/sensor_cfg.ini`). The vendor camera library needs root, so the node runs with `sudo`.

Or the ST VD55G1 (PCB4189) on the camera connector J2, with our driver in `milkv/vd55g1/`: `make -C vd55g1` on the board, install `vd55g1/board/vd55g1-power.service` (I2C pin mux + camera power at boot), then start the node with `--camera vd55g1`. Details in `milkv/vd55g1/README.md`.

UART: header pins 11 and 13 are `/dev/ttyS2` once the pinmux is set. Persistent with a small systemd unit that runs at boot:

```
duo-pinmux -w B11/UART2_TX
duo-pinmux -w B12/UART2_RX
```

Deploy the code from the PC:

```
bash tools/deploy_duos.sh debian@10.2.250.1 /home/debian/milkv
```

Then on the board:

- copy a seed checkpoint to `~/milkv/training_quantization/throwaway_models/` (`training_quantization/model/gate_classifier_model.pt` works)
- download the Stargate dataset: `python3 training_quantization/continual_learning/bootstrap_data.py`

### PC

```
cd pc && python3 -m venv venv && venv/bin/pip install -r requirements.txt
```

## Usage

1. Power the drone, connect the UART wires, plug in the Duo S.
2. Duo S, from `~/milkv` (set the clock first, the board has no RTC):

   ```
   ssh debian@10.2.250.1 "sudo date -u -s '$(date -u +'%F %T')'"
   ssh debian@10.2.250.1
   cd ~/milkv && sudo python3 -u -m duos_node.main --fly --ckpt training_quantization/throwaway_models/gate_classifier_model.pt --finetune_on_dump --buffer_n 90 --median_k 7
   ```

   Loading torch and the model takes ~2 min. Ready when the log shows `[CAM] GC2083 running` (`[CAM] VD55G1 running` with `--camera vd55g1`), `[PCLINK] Listening on 0.0.0.0:5800` and `[CF CONTROL] Drone state arriving`. Without `--fly` the node only streams sensing and predictions.

   Without a working camera, `--fake_camera` feeds random frames instead, so inference, dump and finetune still run (the predictions mean nothing, auto mode flies on the ToF):

   ```
   cd ~/milkv && sudo python3 -u -m duos_node.main --fly --fake_camera --ckpt training_quantization/throwaway_models/gate_classifier_model.pt --finetune_on_dump --buffer_n 65 --median_k 7
   ```

   Only one node at a time. Stop with Ctrl-C, or from another shell `sudo pkill -INT -f duos_node.main` (never `kill -9`, the camera then stays stuck until a reboot).

3. PC, from `pc/`:

   ```
   sudo -E venv/bin/python3 -m pc_node.main --keyboard --viewer --plot --duos-ip 10.2.250.1
   ```

   `--keyboard` key forwarding (needs root), `--viewer` camera/ToF/p(gate) windows, `--plot` live p(gate) plot. Viewer only: drop `--keyboard`.

   Over wifi instead of USB: same commands with the board's wifi address (router client list, e.g. `192.168.0.3`) in place of `10.2.250.1`, both for `ssh` and `--duos-ip`.

4. Fly (keys below). `z` closes the viewer, then Ctrl-C.

Keys (global hook, window focus does not matter):

| Key | Action |
|---|---|
| `space` | arm takeoff, `k` before takeoff aborts |
| `i` | autonomous: explore, find a gate, fly through it. Any manual key ends it |
| `w a s d` | velocity |
| `q e` | yaw rate |
| `o p` | height |
| `k` | kill |
| `t` | dump the ring buffer (+ finetune with `--finetune_on_dump`) |
| `r` / `b` | start / stop continuous recording |
| `z` | quit the viewer |

Failsafes: stale ToF/prediction stream in auto mode, hover after 0.3 s, land after 2 s. Dead key stream, hover after 1 s, land after 3 s. No setpoints from the Duo S at all, the Crazyflie's commander watchdog levels the drone after 0.5 s and cuts the motors after 2 s.

### Crash and retraining

- Crash detected from the drone state: stop, dump the last `--buffer_n` frames to `training_quantization/collision_dataset/train/collision_0/`, start the finetune, hot-swap the new checkpoint. `t` does the same by hand.
- Inference throttles to ~1 Hz while training, except in autonomous flight.
- A dump during a running training is queued.
- Training log: `~/milkv/simulation_last.log` on the board. Crash images: `pc/crash_events/crash_<id>_visual.png`, `crash_<id>_plot.pdf`. Both sides append to `crash_events.log`.
- Models chain: each finetune starts from the newest `.pt` in `throwaway_models/` and writes `collision_0_finetune.pt`.

Reset to the seed checkpoint (node stopped, on the board from `~/milkv`):

```
python3 -m duos_node.clear_collision 

```

## Testing without the drone

From `milkv/`:

```
python3 -m duos_node.simple_node --ckpt training_quantization/model/gate_classifier_model.pt [--frames <dataset dir>] [--finetune_on_dump]
```

The node's learning loop in one file, no drone, camera or PC link. `d` + Enter simulates a crash, `--dump_at <n>` does it at frame n. Good starting point to read the code.

On the board, each input on its own:

```
sudo python3 -m duos_node.camera       # 8 s of frames, prints the fps, last frame in /tmp/cam_last.png (add vd55g1 for the VD55G1)
python3 -m duos_node.uart_link         # 5 s of the wire, prints the ToF rate and the drone state
```

Tests: `duos_node.tests.test_protocol`, `test_latent_reuse`, `test_navigator_backend`, `check_dumped_latents` (compares the latents of the last dump with a fresh encoder pass, run on the board after a crash).

Drone checks over the radio (Crazyradio plugged into the PC, from the repo root): `python3 tools/cf_console_check.py [uri]`, `python3 tools/cf_assert_dump.py`: boot console, firmware params, stored asserts.

## Troubleshooting

- `[CAM] mmf_vi_init failed`: the sensor did not answer, reseat the ribbon on J1 at both ends. The vendor libraries log to the journal, `journalctl -b | grep VI-ERR` shows the reason.
- `uart(drone<->duo)=DOWN` in the viewer: no frames from the drone. Check the three wires, that the drone runs the new app, and that `/dev/ttyS2` exists (pinmux).
- Node log stays empty: start with `python3 -u`.
- PC cannot connect to :5800: wait, model loading takes ~2 min.
- Node or training killed: no swap.
- `apt: Failed to fetch ... deb13uN`: `apt-get update`.
- Wrong dates in crash ids: set the clock before flying.

## Node options

`duos_node.main` (runs with `sudo`):

| Option | |
|---|---|
| `--ckpt` | starting checkpoint |
| `--fly` | run the flight controller, otherwise sensing only |
| `--buffer_n 90` | ring buffer length |
| `--collision_name collision_0 --collision_label no_gate` | dump folder and label |
| `--finetune_on_dump` | dump also starts the finetune |
| `--median_k 7 --ema_percent 100 --thr 0.5` | prediction smoothing, threshold |
| `--camera gc2083` | `gc2083` (J1) or `vd55g1` (J2, `milkv/vd55g1`) |
| `--cam_preproc crop` | `crop` or `resize` |
| `--classifier_backend onnx` | `onnx` (default, much faster on the board) or `torch` |
| `--navigator_mode gated` | `gated` (default: only in auto mode with a gate in view, ~26 ms per run on the board) or `always` |
| `--navigator_every 2` | run the navigator every n-th frame |
| `--train_launcher fork` | `fork` or `subprocess` |

`pc_node.main`: `--keyboard`, `--viewer`, `--plot`, `--duos-ip`, `--show_model_inputs` (raw camera/ToF next to the model inputs), `--buffer_key t`.

## Implementation notes

- Camera: `duos_node/camera.py` reads the GC2083 through the vendor middleware (`libmaixcam_lib.so` via ctypes), asks the scaler for 640x360, cuts the 4:3 center and resizes to 324x244 gray. The rest of the pipeline sees the same frames as with the AI-deck. The VD55G1 (`Vd55g1Camera`) goes through `vd55g1/build/libvd55cam.so`: Sophgo sensor driver, ISP with the Sophgo AE, hardware scaler straight to 324x244 gray.
- UART link: `duos_node/uart_link.py`, framing in `common/protocol.py`, 115200 baud. ToF at 15 Hz, drone state at 15 Hz, setpoints at 33 Hz. 1 s without a frame shows as DOWN in the viewer.
- Classifier runs on onnxruntime. Every checkpoint gets an `.onnx` sibling (outputs `p_gate`, `latent`), exported by the node at startup if missing and by the finetune after saving. Without a fresh `.onnx` the node falls back to torch.
- Navigator runs the tflite model exported to ONNX (`training_quantization/model/gate_navigator_model.onnx` + `.onnx.json`), outputs identical to tflite. Loader order: tflite-runtime, TensorFlow, onnxruntime. Without any of them `yaw_rate = 0`. Runs on every second frame by default. Re-export: `python -m tf2onnx.convert --tflite gate_navigator_model.tflite --output gate_navigator_model.onnx --opset 13`, then make node names unique and update the `.onnx.json`.
- The finetune is forked from the node process (torch and model already loaded, starts in < 1 s). It trains on the latents the node stored with each buffered frame (`latents.npy`), only the layers after the latent tap, and recomputes if the tap or encoder fingerprint does not match.
- Replay latents of the Stargate dataset are built once in `continual_learning/original_dataset/` (a few minutes on the board). Pipeline config: `continual_learning/config.json`.
