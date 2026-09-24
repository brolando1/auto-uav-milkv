# auto-uav-milkv

Autonomous gate flight with a Crazyflie 2.x (AI-deck + ToF deck). Inference, flight control, crash detection and retraining run on a Milk-V Duo S. The PC only bridges the Crazyradio, shows the viewer and forwards the keyboard.

```
STM32 (ToF app) --CPX/UART2--> ESP32 (AP "WiFi streaming example") <--WiFi TCP:5000-- Duo S (only wifi client)
GAP8 (camera jpeg) --CPX----->                                            | classifier + navigator
                                                                          | control loop @33Hz, obstacle
Crazyflie <--Crazyradio (USB on the PC)                                   | avoidance, retrain-on-crash
   ^ setpoints        | telemetry                                         | TCP server :5800 on the wired link
PC (radio bridge + viewer + keyboard)                                     v
PC <---- jpeg / ToF / p_gate / yaw / setpoints / training status -------- Duo S
PC ----- keys (space/i/wasd/qe/op/k) / telemetry / dump / record / ping -> Duo S
```

- ToF frames go over the AI-deck wifi (CPX), the radio only carries setpoints and telemetry.
- The AI-deck wifi is created by the GAP8 streamer (`WiFi streaming example`, open, deck at `192.168.4.1`). The Duo S is its only TCP client.
- Duo S and PC talk over the USB network link (`10.2.250.1`).
- On a crash the Duo S dumps the ring buffer, finetunes the classifier on it and swaps the new model in while running.

## Repository layout

| Folder | Where it runs | What |
|---|---|---|
| `milkv/` | Duo S | `duos_node/` node, `common/` protocol + obstacle avoidance, `training_quantization/` models and training pipeline |
| `pc/` | PC | `pc_node/` radio bridge, viewer, keyboard, link client |
| `tools/` | PC | deploy, measurement and drone check scripts, `duos/` scripts for the board |
| `app-tof-logger-tof/` | Crazyflie STM32 | ToF firmware |
| `wifi-img-streamer/`, `lib/` | AI-deck GAP8 | camera streamer |

`milkv/common/protocol.py` and `pc/pc_node/protocol.py` must be identical, the protocol tests check that.

## Setup

### Drone firmware

AI-deck: build and flash `wifi-img-streamer` following the Bitcraze docs, with `./wifi-img-streamer` instead of the example path.

- https://www.bitcraze.io/documentation/tutorials/getting-started-with-aideck/
- https://www.bitcraze.io/documentation/repository/aideck-gap8-examples/master/examples/wifi-streamer/

STM32: `app-tof-logger-tof`, set `CRAZYFLIE_BASE` in the `Makefile` (tested with crazyflie-firmware 2026.04), then

```
make clean && make
cfloader flash build/cf2.bin stm32-fw     # crazyflie in bootloader mode
```

`app-config` settings that matter:

- `CONFIG_CPX_UART2_BAUDRATE=115200`. The ESP32 firmware on this AI-deck talks at 115200. With the default 576000 the camera works but no ToF arrives. Remove after updating the ESP32 firmware.
- `CONFIG_DECK_AI_WIFI_NO_SETUP=y`. The GAP8 streamer sets up the wifi, not the STM32.

### Duo S

Debian image from https://github.com/scpcom/sophgo-sg200x-debian (Debian 13 riscv64, vendor 5.10 kernel). Login `debian`, password `rv`, reachable at `10.2.250.1` over USB. No pip wheels for riscv64, install from apt:

```
sudo apt-get install --no-install-recommends python3-numpy python3-opencv python3-torch python3-torchvision python3-onnxruntime python3-onnx
```

Internet on the board: phone hotspot as second wifi network with lower priority than the drone. Alternative: `bash tools/duos_proxy.sh` forwards an HTTP proxy from the PC, then `apt-get -o Acquire::http::Proxy=http://127.0.0.1:8899 ...`.

Wifi: networks are in `/boot/wpa_supplicant.conf` (drone first, hotspot second). Do not use `/boot/wifi.ssid`, the boot script would overwrite the config with that single network. `tools/duos/wlan_persist_fix.sh` repairs it.

Deploy the code from the PC:

```
bash tools/deploy_duos.sh debian@10.2.250.1 /home/debian/milkv
```

Then on the board:

- copy a seed checkpoint to `~/milkv/training_quantization/throwaway_models/` (`training_quantization/model/gate_classifier_model.pt` works)
- download the Stargate dataset: `python3 training_quantization/continual_learning/bootstrap_data.py`

### PC

```
python3 -m venv venv
venv/bin/pip install -r pc/requirements.txt -r milkv/requirements.txt
```

Radio address of the drone: see cfclient, ours is `radio://0/120/2M/E7E7E7E706`. Use a radio channel >= 100, lower channels interfere with the wifi.

## Usage

1. Power the drone, plug in Duo S and Crazyradio, close cfclient (it holds the radio).
2. Duo S, from `~/milkv` (set the clock first, the board has no RTC):

   ```
   ssh debian@10.2.250.1 "sudo date -u -s '$(date -u +'%F %T')'"
   ssh debian@10.2.250.1
   cd ~/milkv && python3 -u -m duos_node.main --fly --ckpt training_quantization/throwaway_models/gate_classifier_model.pt --finetune_on_dump --buffer_n 90 --median_k 7
   ```

   Loading torch and the model takes ~2 min. Ready when the log shows `[PCLINK] Listening on 0.0.0.0:5800` and `[CPX] Connected`. Without `--fly` the node only streams sensing and predictions.

3. PC, from `pc/`:

   ```
   sudo -E ../venv/bin/python3 -m pc_node.main --fly --keyboard --viewer --plot --duos-ip 10.2.250.1 --uri radio://0/120/2M/E7E7E7E706
   ```

   `--fly` radio bridge, `--keyboard` key forwarding (needs root), `--viewer` camera/ToF/p(gate) windows, `--plot` live p(gate) plot. Viewer only: drop `--fly --keyboard --uri`.

4. Fly (keys below). `z` closes the viewer, then Ctrl-C.

Keys (global hook, window focus does not matter):

| Key | Action |
|---|---|
| `space` | arm takeoff, `k` before takeoff aborts |
| `i` | autonomous: explore, find a gate, fly through it. Any manual key ends it |
| `w a s d` | velocity |
| `q e` | yaw rate |
| `o p` | height |
| `k` | kill. Also works when the Duo S hangs, the PC stops the motors itself |
| `t` | dump the ring buffer (+ finetune with `--finetune_on_dump`) |
| `r` / `b` | start / stop continuous recording |
| `z` | quit the viewer |

Failsafes: stale ToF/prediction stream in auto mode, hover after 0.3 s, land after 2 s. Dead key stream, hover after 1 s, land after 3 s. No setpoints at the PC bridge, hover after 0.3 s, land after 2 s. PC dead, the Crazyflie commander watchdog cuts the motors after ~500 ms.

### Crash and retraining

- Crash detected from telemetry: stop, dump the last `--buffer_n` frames to `training_quantization/collision_dataset/train/collision_0/`, start the finetune, hot-swap the new checkpoint. `t` does the same by hand.
- Inference throttles to ~1 Hz while training, except in autonomous flight.
- A dump during a running training is queued.
- Training log: `~/milkv/simulation_last.log` on the board. Crash images: `pc/crash_events/crash_<id>_visual.png`, `crash_<id>_plot.pdf`. Both sides append to `crash_events.log`.
- Models chain: each finetune starts from the newest `.pt` in `throwaway_models/` and writes `collision_0_finetune.pt`.

Reset to the seed checkpoint (node stopped, on the board from `~/milkv`):

```
python3 -m duos_node.clear_collision --dry-run
python3 -m duos_node.clear_collision --yes
```

## Testing without the drone

From `milkv/`:

```
python3 -m duos_node.simple_node --ckpt training_quantization/model/gate_classifier_model.pt [--frames <dataset dir>] [--finetune_on_dump]
```

The node's learning loop in one file, no drone, AI-deck or PC link. `d` + Enter simulates a crash, `--dump_at <n>` does it at frame n. Good starting point to read the code.

Full pipeline on one machine:

```
python3 -m duos_node.tests.fake_cpx_server                    # fakes the AI-deck on localhost:5000
python3 -m duos_node.main -n 127.0.0.1 --ckpt training_quantization/model/gate_classifier_model.pt
cd ../pc && python3 -m pc_node.main --viewer --duos-ip 127.0.0.1
```

Tests: `duos_node.tests.test_protocol`, `test_latent_reuse`, `test_navigator_backend`, `check_dumped_latents` (compares the latents of the last dump with a fresh encoder pass, run on the board after a crash).

Drone checks without the Duo S (PC on the drone wifi, Crazyradio plugged in, from the repo root):

- `bash tools/tof_wifi_check.sh [uri]`: console over radio + CPX packet count on the wifi. Healthy: STM32 packets at ~15 Hz, `ToF CPX: N frames sent, 0 send timeouts`.
- `python3 tools/cpx_probe.py`: packets per source. Only GAP8 means the STM32 to ESP32 link is dead (baud rate).
- `python3 tools/cf_console_check.py [uri]`, `python3 tools/cf_assert_dump.py`: boot console, firmware params, stored asserts.

## Troubleshooting

- Camera but no ToF: UART2 baud rate, see drone firmware.
- `[CPX] Connection lost: Network is unreachable` in a loop: wifi config on the board overwritten, run `tools/duos/wlan_persist_fix.sh`.
- Node log stays empty: start with `python3 -u`.
- PC cannot connect to :5800: wait, model loading takes ~2 min.
- Node or training killed: no swap.
- `apt: Failed to fetch ... deb13uN`: `apt-get update`.
- Radio does not open: cfclient still running.
- Wrong dates in crash ids: set the clock before flying.
- Drone power-cycled: nothing to do, the node reconnects after 3 s without data.

## Node options

`duos_node.main`:

| Option | |
|---|---|
| `--ckpt` | starting checkpoint |
| `--fly` | run the flight controller, otherwise sensing only |
| `-n <ip>` | AI-deck address, default `192.168.4.1` |
| `--buffer_n 90` | ring buffer length |
| `--collision_name collision_0 --collision_label no_gate` | dump folder and label |
| `--finetune_on_dump` | dump also starts the finetune |
| `--median_k 7 --ema_percent 100 --thr 0.5` | prediction smoothing, threshold |
| `--cam_preproc crop` | `crop` or `resize` |
| `--classifier_backend onnx` | `onnx` (default, much faster on the board) or `torch` |
| `--navigator_mode always` | `always` or `gated` (only in auto mode with a gate in view) |
| `--navigator_every 2` | run the navigator every n-th frame |
| `--train_launcher fork` | `fork` or `subprocess` |

`pc_node.main`: `--fly`, `--keyboard`, `--viewer`, `--plot`, `--duos-ip`, `--uri`, `--show_model_inputs` (raw camera/ToF next to the model inputs), `--buffer_key t`.

## Implementation notes

- Classifier runs on onnxruntime. Every checkpoint gets an `.onnx` sibling (outputs `p_gate`, `latent`), exported by the node at startup if missing and by the finetune after saving. Without a fresh `.onnx` the node falls back to torch.
- Navigator runs the tflite model exported to ONNX (`training_quantization/model/gate_navigator_model.onnx` + `.onnx.json`), outputs identical to tflite. Loader order: tflite-runtime, TensorFlow, onnxruntime. Without any of them `yaw_rate = 0`. Runs on every second frame by default. Re-export: `python -m tf2onnx.convert --tflite gate_navigator_model.tflite --output gate_navigator_model.onnx --opset 13`, then make node names unique and update the `.onnx.json`.
- The finetune is forked from the node process (torch and model already loaded, starts in < 1 s). It trains on the latents the node stored with each buffered frame (`latents.npy`), only the layers after the latent tap, and recomputes if the tap or encoder fingerprint does not match.
- Replay latents of the Stargate dataset are built once in `continual_learning/original_dataset/` (a few minutes on the board). Pipeline config: `continual_learning/config.json`.
- CPX watchdog: 3 s without data counts as disconnected, the node reconnects.
- The node publishes per-stage timings and memory use in its state stream. `tools/measure_duos.py` collects them from the PC, `tools/duos/bench_frame.py` and `python3 -m duos_node.bench_standalone` measure on the board.
