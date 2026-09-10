# Flight control & ToF and Camera logger & Continual learning

## Architecture (Milk-V Duo S setup)

All flight *decisions* run on the Milk-V Duo S (inference, obstacle avoidance, control loop, crash detection, retraining). The **Crazyradio stays on the PC**, but the PC is only a dumb radio bridge + ground station: the Duo S streams SETPOINT instructions over the wire, the PC executes them on the cflib Commander and sends drone telemetry back up. Keys are captured on the PC and forwarded to the Duo S controller.

```
STM32 (ToF app) --CPX/UART2--> ESP32 (AP "WiFi streaming example") <--WiFi TCP:5000-- Duo S (only wifi client)
GAP8 (camera jpeg) --CPX----->                                            | classifier + navigator
                                                                          | control loop @33Hz, obstacle
Crazyflie <--Crazyradio (USB on the PC)                                   | avoidance, retrain-on-crash
   ^ setpoints        | telemetry                                         | TCP server :5800 on the wired link
PC (radio bridge + viewer + keyboard)                                     v
PC <---- jpeg / ToF / p_gate / yaw / SETPOINTS / training status -------- Duo S
PC ----- keys (space/i/wasd/qe/op/k) / telemetry / dump / record / ping -> Duo S
```

- ToF frames go over the AI-deck wifi (CPX) instead of the radio (see `TOF_OVER_CPX` in the ToF firmware). The radio only carries setpoints + telemetry. The STM32 reaches the ESP32 over UART2; that link only works if both sides use the same baud rate (see "ToF firmware" below), otherwise the camera still streams but no ToF arrives.
- The wifi network is created by the GAP8 streamer (`WiFi streaming example`, open network, AI-deck at `192.168.4.1`). The STM32 is told not to configure wifi (`CONFIG_DECK_AI_WIFI_NO_SETUP`), two competing setups left the old ESP32 firmware with no network at all.
- The Duo S is the single TCP client of the AI-deck (the stock ESP32 firmware only serves one), it relays everything to the PC over ethernet/USB-NCM.
- **Takeoff is armed from the PC with `space`** (`k` aborts before takeoff). Then as before: `i` auto mode, wasd/qe/op manual override, `k` kill. `k` also stops the motors directly on the PC bridge, so kill works even if the Duo S hangs.
- Crash detection runs on the Duo S (telemetry relayed from the PC): stop instruction to the bridge, dump the ring buffer, start the finetune, hot-swap the new checkpoint. A dump requested while a training is running is deferred until that training finishes.
- The crash visual (`crash_<id>_visual.png`) and the 18 s p(gate) plot (`crash_<id>_plot.pdf`) are written on the PC into `pc/crash_events/` (the Duo S reports every dump in its status stream and the viewer saves them, also when no new camera frame arrives). Both sides append to their own `crash_events.log`.
- Layered failsafes:
  - Duo S controller: ToF/prediction stream stale in auto mode -> hover after 0.3 s, land + stop after 2 s; PC key stream dead -> hover after 1 s, land + stop after 3 s (`milkv/duos_node/drone_control.py`).
  - PC radio bridge: no setpoints from the Duo S -> hover after 0.3 s, land + stop after 2 s (`pc/pc_node/radio_bridge.py`). So if the Duo S or the wire dies mid-flight, the PC lands the drone on its own.
  - If the PC itself dies, the crazyflie's built-in commander watchdog cuts the motors (no setpoints for ~500 ms) - same as it always was.

## Repository layout: one folder per machine

| Folder | Copy to | Contents |
|--------|---------|----------|
| `milkv/` | the Milk-V Duo S | `duos_node/` (AI-deck reader, pairing, inference, flight controller, retrain orchestrator, PC link server, bench tests), `common/` (wire protocol, ToF obstacle avoidance), `training_quantization/` (models, preprocessing, continual-learning pipeline), `requirements.txt` |
| `pc/` | the ground station PC | `pc_node/` (`main.py`, radio bridge, link client, viewer + OpenCV helpers, pairing, its own copy of `protocol.py`), `cache/` (cflib TOC cache), `requirements.txt`; `crash_events/` gets created at the first dump |
| `tools/` | (offline, run on a PC next to `milkv/`) | `player_with_predictions.py` (dataset player, uses `milkv/training_quantization`), `stargate_noise.py`, hardware checks: `tof_wifi_check.sh`, `cpx_probe.py`, `cf_console_check.py`, `cf_assert_dump.py` (see "Checking the drone without the Duo S") |
| `app-tof-logger-tof/`, `wifi-img-streamer/`, `lib/` | crazyflie / AI-deck | firmware, see below |

Each of `milkv/` and `pc/` is self-contained: copy the folder, `pip install -r requirements.txt` inside it, run from inside it. The only file that exists in both is the wire protocol (`milkv/common/protocol.py` and `pc/pc_node/protocol.py`); the protocol tests fail if the two copies differ, so when you change it copy it over. Gitignored things the Milk-V also needs: `milkv/training_quantization/throwaway_models/` (seed checkpoint) and the bootstrap dataset (see "Downloading dataset"). The gate navigator loads through `tflite-runtime`, TensorFlow or `onnxruntime` (in that order); without any of them the node still runs, with `yaw_rate = 0`.

## Running

- **On the Duo S** (from `milkv/`):
  `python3 -m duos_node.main --fly --ckpt training_quantization/throwaway_models/<model>.pt --finetune_on_dump --buffer_n 90 --median_k 7`
  (no cflib/radio on the board. Run it under a restart loop/systemd. Without `--fly` it runs sensing/inference only. Board setup: see "Setting up the Duo S".)
- **On the PC** (from `pc/`, Crazyradio plugged in):
  `sudo -E <python> -m pc_node.main --fly --keyboard --viewer --plot --duos-ip <duo_ip>`
  `--fly` runs the radio bridge, `--keyboard` forwards the flight keys to the Duo S at 30 Hz (needs sudo), `--viewer` shows the camera/ToF/p(gate) windows (runs on the main thread because OpenCV windows only work from there). `--uri` selects the radio URI (default `radio://0/120/2M/E7E7E7E7E7`; our drone answers on `radio://0/120/2M/E7E7E7E706`, check the address in cfclient). The PC does not need to be on the drone's wifi.
  Use a venv (`python3 -m venv venv && pip install -r pc/requirements.txt -r milkv/requirements.txt`) and run everything with its interpreter, also under sudo: `sudo -E venv/bin/python3 -m pc_node.main ...`. The `keyboard` module needs root even for `--viewer` alone.

### Setting up the Duo S

Our board runs Debian 13 (trixie) riscv64 with Python 3.13, user `debian`, reachable over the USB link at `10.2.250.1` (the PC side gets `10.2.250.x`). Debian ships everything the node needs as riscv64 packages, pip wheels do not exist for this arch:

```
sudo apt-get install --no-install-recommends python3-numpy python3-opencv python3-torch python3-torchvision python3-onnxruntime python3-onnx
```

Internet on the board: simplest is a phone hotspot. `wlan0` also knows the `PewPew` hotspot (priority 1, below the drone's AP), and with the drone off the board joins it and gets a default route and DNS from it, so plain `apt`/`pip`/`curl` work (with the drone on, the drone's AP wins and has no internet; `sudo wpa_cli -i wlan0 disable_network 0` / `enable_network 0` switches temporarily). `/etc/dhcpcd.conf` has `nogateway` only for the drone's SSID. Without a hotspot, either NAT the USB link through the PC, or run an HTTP proxy on the PC and forward it over ssh (`bash tools/duos_proxy.sh`), then give the proxy to apt:
```
# PC (venv):  pip install proxy.py; proxy --hostname 127.0.0.1 --port 8899 &
#             ssh -f -N -R 8899:127.0.0.1:8899 debian@10.2.250.1
# board:      sudo apt-get -o Acquire::http::Proxy=http://127.0.0.1:8899 -o Acquire::https::Proxy=http://127.0.0.1:8899 update/install ...
```
If apt reports `Failed to fetch ... deb13uN`, the package index is stale: run `apt-get update` (through the proxy) and install again. The board also has no RTC, set the clock before flying (`sudo date -u -s "$(date -u +'%F %T')"` from the PC over ssh), otherwise the crash ids and logs carry a wrong date.

Deploy and check from the PC: `bash tools/deploy_duos.sh debian@10.2.250.1 /home/debian/milkv` (rsync of `milkv/` without crash images/datasets, then a report of arch, python, installed modules, wifi and the protocol tests on the board). Copy a seed checkpoint into `training_quantization/throwaway_models/` on the board yourself (gitignored), the tracked `training_quantization/model/gate_classifier_model.pt` works as a start.

Start the node with `python3 -u ...` (or `PYTHONUNBUFFERED=1`) when its output goes to a file, otherwise the log stays empty for minutes; importing torch and loading the model takes about 2 minutes on the board, only then does `:5800` open. Expect ~90% of the single core and ~290 MB RSS for sensing/inference.

Training launcher: by default the node **forks** the finetune off its own process (`--train_launcher fork`): the child inherits torch, the model and the pipeline modules, so the training starts in well under a second instead of the 20-60 s a fresh interpreter needs on the board, and shares most memory copy-on-write. The fork is executed by the inference thread at the top of its loop (never inside torch/cv2), the child gets its own session, log (`simulation_last.log`), closed sockets and `oom_score_adj=1000`. `--train_launcher subprocess` restores the old fresh-interpreter behaviour. The preload also constructs a throwaway Adam optimizer once, because the first `torch.optim.Adam()` lazily imports torch's dynamo/inductor/sympy stack (~20 s, ~60 MB on the board); without that the forked child paid it in every run. While the child trains the inference loop idles at ~1 Hz so the training gets the core (at 5 Hz, classifier + navigator still took half of it). The one exception is autonomous flight (`flight_status` `flying` with `auto`): the controller consumes the predictions and its stale-prediction watchdog would hover/land the drone, so there the loop keeps full rate and a `t` dump trains slower. Manual flight and everything on the ground (crash, landed, armed, no `--fly`) are throttled. Measured on the real drone, `--buffer_n 65` (45 frames dumped), `eval_collisions_after_ft=false`, latents reused, inference throttled to 1 Hz during the run: dump + fork 0.8 s, setup 1.3 s, 2 epochs 7.1 s, ONNX export 2.6 s, save/hot-swap ~2 s, **14 s dump -> new model live on onnxruntime**, node back at 25 fps 4 s later (was 210 s at the start with a fresh interpreter, validation, forced prepare, post-FT evaluation and a second encoder pass). Frame rates on the real drone: ~25 fps in manual flight / on the ground (camera delivers 26), ~20.5 fps constant with the navigator always on and on every 2nd frame (default), ~15 fps with it on every frame. The node also keeps, for every frame in the ring buffer, the latent it computed at inference time (its forward is split at `latent_tap`, `compat.infer_with_latent`, numerically identical to the full forward). A dump writes them as `latents.npy` + `latents_meta.json` next to `camera_images/`, and `prepare_collision` uses them instead of running the encoder over the dumped frames again, but only if tap, sample count and the SHA1 fingerprint of the pre-tap weights (`compat.encoder_fingerprint`) match the model the finetune loads; otherwise it recomputes and says why. Finetunes never change pre-tap weights, so the fingerprint stays valid across generations (`python3 -m duos_node.tests.test_latent_reuse` checks all of this). What is left is compute on this torch build (generic BLAS, no vector unit: one conv step on a 128 batch costs ~1.7 s): fewer/smaller epochs, fewer replay samples (`n_original_*_to_select`) or a later `latent_tap` (only the FC layer trains). `config.json` runs with `force_prepare_original_dataset=false` (the prepared latents in `continual_learning/original_dataset/` are built once by the first run, ~7 min on the board, and stay valid because only layers after the latent tap are trained) and `validation=false`.

Memory: the board has 411 MB RAM and no swap by default. The node (~260 MB RSS with torch) plus a finetune run (~330 MB peak with `validation`/`force_prepare_original_dataset` on) gets both killed by the OOM killer. Fixes in place: a 1 GB `/swapfile` (in `/etc/fstab`), `vm.swappiness=20`, the training subprocess sets its own `oom_score_adj=1000` so the kernel kills it before the node,.

Wifi: `wlan0` is ifupdown-managed (do not leave backup files in `/etc/network/interfaces.d/`, ifupdown reads all of them). `/etc/network/interfaces.d/wlan0` points at `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf`, which lists the AI-deck AP (`WiFi streaming example`, `key_mgmt=NONE`, priority 10) and the `PewPew` hotspot (priority 1); `/etc/dhcpcd.conf` has an `ssid "WiFi streaming example"` / `nogateway` block so the drone AP never becomes the default route while a hotspot may. When the drone is on, `wpa_cli -i wlan0 status` shows `COMPLETED` and `ping 192.168.4.1` answers.

**Reboot trap:** the Milk-V image runs `/etc/init.d/S30wifi` at every boot, which regenerates `/etc/network/interfaces.d/wlan0` from `/boot/wifi.ssid` + `/boot/wifi.pass` (a PewPew-only `wpa-essid` stanza) and thereby silently drops the drone AP; the symptom is the node looping on `[CPX] Connection lost: [Errno 101] Network is unreachable` while the PC still sees the AP. The script skips that rewrite when `/boot/wpa_supplicant.conf` exists (it then only copies it to `/etc/wpa_supplicant.conf`), so the board now carries our config there and the stanza is `iface wlan0 inet dhcp` + `wpa-conf /etc/wpa_supplicant.conf` (`tools/duos/wlan_persist_fix.sh` does all of it and reconnects). To change wifi networks edit `/boot/wpa_supplicant.conf` (drone AP priority 10, hotspot priority 1), not `/boot/wifi.ssid`. Known nit: dhcpcd still installs the drone's default route (metric 3005) although `dhcpcd.conf` has `nogateway` for that SSID; harmless for the node (the PC link is a directly connected USB subnet), it only matters if the board should reach the internet through another interface at the same time.

Classifier inference on the board runs through **onnxruntime** (`--classifier_backend onnx`, default): torch's generic CPU kernels need ~50 ms per frame on the Duo S, onnxruntime ~15 ms for the identical network (probability bit-identical, latent within 2e-6, `test_latent_reuse`). Every checkpoint gets an `.onnx` sibling with outputs `p_gate` + `latent` (`compat.export_classifier_onnx`, needs `python3-onnx`): the node exports a missing one at startup, and the finetune child exports its new checkpoint right after saving it (~3 s on the board, warmed in the preload), so a hot-swap loads the `.onnx` without blocking the inference thread. A checkpoint without a fresh `.onnx` runs with torch and says so in the log; `--classifier_backend torch` forces that. The per-frame budget on the board is then ~15 ms classifier + ~12 ms decode/preprocessing (+ ~25 ms navigator, which only runs in autonomous mode while p(gate) >= `GATE_THRESHOLD`, the only case where the controller uses its yaw, and in sensing-only runs for the viewer), i.e. roughly 3x the frame rate of the torch path. Measured stage by stage on the board (`bench_frame.py`-style, one core): jpeg decode 7 ms, crop+normalize 1 ms, classifier 14.5 ms, navigator 25 ms. The navigator runs on every frame regardless of flight mode or gate (`--navigator_mode always`, default) so the frame rate is constant; its yaw is handed to the controller only in autonomous mode with p(gate) >= `GATE_THRESHOLD` (`yaw_used` in STATE), otherwise the controller gets 0. `--navigator_mode gated` computes it only in that case (faster without a gate, but the rate then jumps between ~25 and ~20 fps). It is also decimated: `--navigator_every 2` (default) runs it on every second frame, the frame in between reuses the last yaw rate; the counter resets when the gate is gone / mode is manual so the first frame of a new gate always gets a fresh yaw. `--navigator_every 1` restores every frame (15 fps). STATE carries `timing_ms` (rolling mean/p95 per loop stage over the last 300 frames, `InferenceService.timing`) and `mem_mb` (node RSS/peak, system available/swap, training child RSS/peak), so statistics can be taken from the PC: `tools/measure_duos.py` (repeated inference windows + retrain trials), `tools/duos/bench_frame.py` (isolated stage cost on the board).

Measured on the real drone, 2026-09-08, node on the ground (`--fly`, waiting for the radio), navigator always + every 2nd frame, 3 x 30 s windows and 3 retrain trials (`--buffer_n 65`, 45 frames dumped, 135 replay latents):

| inference | value |
|---|---|
| camera delivered | 26.0 fps |
| frames processed | 20.5 ± 0.1 fps (constant, independent of mode) |
| loop per frame | 47.5 ms (jpeg decode 1.6, preprocess 5.1, classifier 20.0, buffer+filters 2.0, navigator 35.9 per run = 18.0 per frame, state+publish 2.2) |
| latency frame decoded -> prediction published | 64.6 ms mean |
| PC <-> node link RTT (USB) | 47 ms mean, 82 ms p95 |
| node RSS | 297 MB (peak 300), system available ~120-140 MB, swap used 27-50 MB |
| isolated stage cost (nothing else running) | classifier 14.6 ms, navigator 23.8 ms, decode 7.1 ms worst-case jpeg, normalize 1.2 ms; the loop numbers are higher because the CPX receiver, relay and PC link threads share the single core |

| retrain (mean ± std, 10 consecutive trials, all reused the dumped latents) | s |
|---|---|
| dump written -> child forked | 0.68 ± 0.05 |
| child setup (config, replay latents, dumped latents) | 0.81 ± 0.22 |
| epoch 1 / epoch 2 (180 latent samples) | 4.02 ± 0.43 / 3.68 ± 0.04 |
| training total | 7.72 ± 0.44 |
| ONNX export | 2.68 ± 0.17 |
| checkpoint load/save, merge, other | 2.12 ± 0.14 |
| child wall time | 13.33 ± 0.78 |
| **dump -> new model live (hot-swap)** | **14.00 ± 0.78** (min 13.55, max 16.29; the first trial after a node start is the slowest) |
| node while training | throttled to 0.84 fps |

Idle-board numbers (`python3 -m duos_node.bench_standalone`, node stopped, nothing else running; real dumped frames, 10 passes x 45 frames, and 10 retrains of the real pipeline in a scratch copy of the model folder), 2026-09-08:

| inference stage, idle board | ms (mean ± std) |
|---|---|
| jpeg decode (324x244) | 2.8 ± 0.8 |
| camera crop + normalize | 2.5 ± 0.3 |
| ToF 8x8 -> 21x21 normalize | 1.2 |
| classifier, onnxruntime | 14.8 ± 1.4 |
| navigator quantize inputs | 3.0 ± 0.5 |
| navigator run, onnxruntime | 23.0 ± 2.5 |
| classifier + navigator | 40.9 |
| classifier, torch (for reference) | 57.6 |

That gives an idle-board frame budget of 21 ms with the classifier only (47 fps), 34 ms with the navigator on every 2nd frame (29 fps) and 47 ms with it on every frame (21 fps); the live node reaches 25 / 20.5 / 15 fps because the camera receiver, jpeg relay and PC link share the core.

| retraining stage, idle board, 10 runs | s (mean ± std) |
|---|---|
| fork + child start/exit | 0.14 ± 0.03 |
| setup (model, replay latents) | 0.55 ± 0.06 |
| prepare_collisions (45 dumped latents reused) | 0.10 ± 0.04 |
| prepare_training | 0.04 |
| epoch 1 / epoch 2 (180 latent samples) | 2.65 ± 0.20 / 2.49 ± 0.06 |
| checkpoint save | 0.13 ± 0.03 |
| ONNX export | 1.74 ± 0.07 |
| **fork -> child exit** | **7.92 ± 0.37** (min 7.68, max 9.00, first run slowest) |
| training child peak RSS | 209 MB |

So a retrain is ~8 s of pure compute and ~14 s in the live node: the difference is the dump write (0.7 s), the hot-swap (~2 s) and the stream/relay threads that keep taking ~30% of the core while the child trains.

Memory on the board (411 MB RAM + 1 GB swapfile), sampled once a second with `tools/duos/mem_sampler.sh`, summarized by `tools/duos/mem_report.py`:

| | node idle | training peak |
|---|---|---|
| system used (MemTotal - MemAvailable) | 260-270 MB, ~140 MB available | 320 MB max, 92 MB available at the minimum |
| swap used | ~45 MB | ~50 MB max |
| node process RSS | 230-257 MB (torch + onnxruntime sessions + preloaded training modules; ~300 MB peak right after a hot-swap) | 257 MB |
| training child RSS | - | 262 MB mean, 282 MB max |
| everything else (journald, init, NetworkManager, wpa_supplicant, sshd, ...) | ~35 MB together, no single process above 12 MB | same |

Node and child RSS add up to more than the RAM because the child is forked: its 270 MB are mostly copy-on-write pages shared with the node, the real extra cost of a training is the ~50-60 MB the system usage grows by. Without the fork launcher (`--train_launcher subprocess`) the child is a separate interpreter with its own torch and would not fit next to the node without swapping.

Deleting a collision and its model on the board (`duos_node/clear_collision.py`): stop the node, then

```bash
ssh debian@10.2.250.1 'cd ~/milkv && python3 -m duos_node.clear_collision --dry-run'   # show what would go
ssh debian@10.2.250.1 'cd ~/milkv && python3 -m duos_node.clear_collision --yes'       # delete collision_0 dump + collision_0_finetune.pt/.onnx
```

`--name` picks another collision, `--keep-dump` / `--keep-model` delete only one half, `--force` allows it while a node runs (not while a training is writing). Every dump overwrites the same `collision_dataset/train/collision_0/` folder and every finetune overwrites `collision_0_finetune.pt` (the child finetunes the newest `.pt` in `throwaway_models/`, so the models chain), which is why removing that one model resets the node to the seed checkpoint at the next retrain; the prepared replay latents and `crash_events.log` stay.

CPX link watchdog: when the drone is power-cycled (battery swap) the ESP32 never closes the TCP connection, so the node used to sit in `recv()` on an ESTABLISHED socket forever and needed a restart. `CPXLink` now treats 3 s without any CPX data as a lost connection (`STALL_TIMEOUT_S`) and reconnects; `reconnects` counts them.

The Duo S runs Linux on a single core, so threads cannot make the two networks run in parallel; the remaining levers are fewer navigator runs, or a runtime built for the vector unit / TPU (vendor SDK, not the Debian packages). Gate navigator on the board: `tflite-runtime` has no riscv64 build and Debian ships no tflite/TensorFlow package for any architecture, so the navigator runs the same network exported to ONNX (`training_quantization/model/gate_navigator_model.onnx`, QDQ int8, plus `.onnx.json` with the quantization parameters) through `onnxruntime`. The loader tries tflite-runtime, then TensorFlow, then onnxruntime, so a PC with the original runtime keeps using the `.tflite`. Outputs are bit-identical to the tflite interpreter (`python3 -m duos_node.tests.test_navigator_backend`, reference outputs in `duos_node/tests/navigator_tflite_reference.npz`), ~25 ms per inference on the Duo S (a float export of the same network is not faster there, 26 ms, so the exact int8 one stays). For 168x168 frames the inference loop feeds the navigator the classifier's already normalized arrays (identical values, saves its ~7 ms of preprocessing). Re-export after changing the tflite model: `python -m tf2onnx.convert --tflite gate_navigator_model.tflite --output gate_navigator_model.onnx --opset 13`, then give every node a unique name (onnxruntime rejects tf2onnx's duplicates) and refresh the `.onnx.json`; the backend loads it at `ORT_ENABLE_EXTENDED` with `QDQS8ToU8Transformer` disabled (fuses Conv+Clip: 26.3 -> 24.0 ms on the board, still bit-exact) and falls back to `ORT_ENABLE_BASIC` if the runtime rejects it (that transformer, and `ALL`, fail on this graph with "two nodes with same node name"). Navigator speed investigation (2026-09-08, on the board): per-operator profile is 48% Conv, 40% QuantizeLinear/DequantizeLinear, i.e. the QDQ graph runs float convolutions with quantize/dequantize around them and the int8 kernels never engage. Making them engage would not help: QLinearConv with this network's exact layer shapes is 1.4-1.8x *slower* than float Conv on the Debian riscv64 onnxruntime build (per-layer benchmark, sum 28.5 ms int8 vs 17.0 ms float); the first 5x5 stride-2 conv on the 168x168 input alone costs 8 ms (0.7 MMAC, i.e. the build is unvectorized generic code). The remaining levers are outside onnxruntime: a runtime built for the C906's RVV 0.7.1 (T-Head toolchain), the CV181x TPU (vendor SDK image), or a smaller navigator retrained on the PC. Fixed on the way: the navigator quantized its inputs with a plain uint8 cast, so ToF cells beyond 3.0 m (the model's input range, the training data was clipped at 3 m) wrapped around to near distances. Inputs are now clipped to 0..255 before the cast, in all backends.

### Bench testing without the drone

From `milkv/`:
- `python3 -m duos_node.tests.test_protocol` runs the protocol/loopback tests, `python3 -m duos_node.tests.test_latent_reuse` the checks for the inference-latent reuse in the finetune, and `python3 -m duos_node.tests.check_dumped_latents` recomputes the latents of the last collision dump with the pipeline's encoder pass and compares them frame by frame with the `latents.npy` the node wrote (run it on the board after a real crash to audit that path).
- `python3 -m duos_node.tests.fake_cpx_server` fakes the AI-deck socket (camera + ToF in CPX framing) on localhost:5000, so the whole pipeline can be tested on one machine:
  `python3 -m duos_node.main -n 127.0.0.1 --ckpt training_quantization/model/gate_classifier_model.pt` and then, from `pc/`, `python3 -m pc_node.main --viewer --duos-ip 127.0.0.1` (without `--fly` the PC side does not open the radio, so no crazyflie is needed).

### Checking the drone without the Duo S

The Duo S node is plain Python, so it also runs on the PC against the real AI-deck: join the drone's wifi and start `python3 -m duos_node.main --ckpt ...` from `milkv/` without `-n` (it defaults to `192.168.4.1`), then the viewer against `127.0.0.1` as above. Lower-level checks (PC on the drone's wifi, Crazyradio plugged in, run from the repo root with the venv active):

- `bash tools/tof_wifi_check.sh [radio-uri]` captures the crazyflie console over the radio and counts CPX packets on the wifi socket at the same time, and writes both to `tof_check_<date>.log`. A healthy drone shows `STM32` packets at ~15 Hz of complete ToF frames and `ToF CPX: N frames sent, 0 send timeouts` in the console.
- `python3 tools/cpx_probe.py` only counts CPX packets per source on the AI-deck socket (stop the node first, the ESP32 serves one client). Only `GAP8` packets means the STM32 -> ESP32 UART2 link is dead (baud rate, see below).
- `python3 tools/cf_console_check.py [uri]` reads firmware/deck params, power-cycles the STM32 and captures the boot console. `python3 tools/cf_assert_dump.py [--uri ...] [--reset]` captures the console and asks the firmware for stored assert info. Close cfclient first, it holds the radio.

### Argument Reference

Duo S node (`duos_node.main`):

| Argument | Description |
|----------|-------------|
| `--ckpt` | Starting checkpoint used for inference |
| `--buffer_n 90` | Keep the last 90 paired samples in RAM (the ring buffer that gets dumped) |
| `--collision_name collisione_0 --collision_label no_gate` | Destination path and label for the saved dataset |
| `--finetune_on_dump` | a dump (key or crash) also starts `simulation.py` fine-tuning (as subprocess) |
| `--median_k 7 --ema_percent 100 --thr 0.5` | prediction smoothing + decision threshold |
| `--cam_preproc crop` | camera preprocessing (`crop` or `resize`) |

PC viewer (`pc_node.main --viewer`): `--plot` enables the live plot of `p(gate)` vs time, `--show_model_inputs` shows a debug window with the raw camera/ToF next to the model inputs the Duo S relays while the window is on, `--buffer_key t` sets the dump key.

### Key Controls

Keys are captured with a global keyboard hook, so it does not matter which window is focused.

| Key | Action |
|-----|--------|
| `z` | Quit the viewer |
| `t` | Dump current buffer to collision dataset (+ finetune with `--finetune_on_dump`) |
| `r` | Start continuous recording |
| `b` | Stop continuous recording |

## Keyboard

The board can be controlled manually and autonomously. With `--keyboard` the PC forwards key presses to the flight controller on the Duo S; **the drone takes off when you press `space`**, `k` before takeoff aborts.

- **Manual control** :
    - W, A, S, D command velocities as usual
    - Q, E command yaw rates 
    - O, P command height changes
    - K kills the drone making it fall out of the sky

- **Autonomous control** :
    - The I command will make the drone fly autonomously. It will randomly explore its surroundings until it finds a gate and will then proceed to go through it.
    - To **stop the autonomous flying**, one of the commands responsible for manual control should be pressed.

## Firmware

### ToF firmware 

The ToF firmware can be found in `app-tof-logger-tof`. It sends the ToF frames over CPX/wifi (`TOF_OVER_CPX` in the `Makefile`); the old CRTP-over-radio path is still in the source behind that flag, but nothing in this repo reads it anymore. Each frame goes out as 3 CPX packets (magic `'T'`, seq, chunk, n, timestamp + 64 data bytes), sent with a 200 ms timeout so a stalled link drops frames instead of blocking the app; the console reports `ToF CPX: N frames sent, M send timeouts` every ~20 s.

`app-config` holds the kconfig overrides, two of them matter for the AI-deck link:
- `CONFIG_CPX_UART2_BAUDRATE=115200`: the ESP32 on our AI-deck runs an older Bitcraze firmware that talks at 115200 (the crazyflie default is 576000, with which the handshake never completes and no ToF arrives while the camera keeps working). If you update the ESP32 firmware to a current release (`cfloader flash <aideck_esp.bin> deck-bcAI:esp-fw`), remove this line.
- `CONFIG_DECK_AI_WIFI_NO_SETUP=y`: the GAP8 streamer configures the wifi, the STM32 must not.

To **build and flash**:
- Move to `app-tof-logger-tof` folder
- In `Makefile` adapt path `CRAZYFLIE_BASE` to your crazyflie firmware checkout (currently `$(HOME)/auto-uav/crazyflie-firmware`, tested with 2026.04)
- Run `make clean` to clean exisiting previous builds
- Run `make` to build 
- Put crazyflie into bootloader mode and flash `build/cf2.bin`: `cfloader flash build/cf2.bin stm32-fw` (the `cfloader` from the cfclient install; `make cload` calls `python3 -m cfloader`, which recent cflib versions no longer ship)

### AI-deck Firmware for camera image streaming

The necessary firmware to stream 168 x 168 camera images is in the `wifi-img-streamer` directory. To build it, the `lib` directory is also needed.
In order to **build and flash** the firmware, follow the linked AI-deck tutorials by bitcraze:
- https://www.bitcraze.io/documentation/tutorials/getting-started-with-aideck/ to setup the AI-deck
- https://www.bitcraze.io/documentation/repository/aideck-gap8-examples/master/examples/wifi-streamer/ to configure the crazyflie firmware for AI-deck support and for flashing instructions. Instead of navigating to the aideck-gap8-examples repository just stay in this repository and adjust the `examples/other/wifi-img-streamer` path with `./wifi-img-streamer` in both paths

## Downloading dataset

Finetuning requires the Stargate dataset. If it is not yet downloaded, please run `milkv/training_quantization/continual_learning/bootstrap_data.py` which will do it for you. It might take some time to download, please be patient. The dataset has to be on the Duo S (that is where `simulation.py` runs).

## Experiment procedures

- Make sure the Radio channel is set to a high value (>=100) in the cfclient to reduce interference with the wifi streaming
- Start the crazyflie; the Duo S connects to the AI-deck wifi (`WiFi streaming example`), the PC is connected to the Duo S over the wired link
- On the Duo S, from `milkv/`, start `python3 -m duos_node.main --fly ...` (see above)
- On the PC, from `pc/`, run `sudo -E ~/"path_to_your_python_env_dir"/bin/python3 -m pc_node.main --fly --keyboard --viewer --duos-ip <duo_ip>`
- **Aborting the programm** : after you landed or killed the drone, press `z` to close the viewer, afterwards `CTRL-C` on the terminal to completely stop the programm

## Quick start (our hardware)

Drone: crazyflie `radio://0/120/2M/E7E7E7E706`, AI-deck wifi `WiFi streaming example` (open), deck at `192.168.4.1`.
Duo S: `ssh debian@10.2.250.1` over the USB link, repo in `~/milkv`, joins the drone wifi by itself.
PC: this repo in `~/Desktop/milkv-drone`, venv in `venv/`.

1. Power the drone. Plug in the Duo S (USB) and the Crazyradio. Close cfclient (it holds the radio).
2. Set the board clock and start the node (2 terminals, or one ssh session):
   ```
   ssh debian@10.2.250.1 "sudo date -u -s '$(date -u +'%F %T')'"
   ssh debian@10.2.250.1
   cd ~/milkv && python3 -u -m duos_node.main --fly --ckpt training_quantization/throwaway_models/gate_classifier_model.pt --finetune_on_dump --buffer_n 90 --median_k 7
   ```
   Leave out `--fly` for sensing/inference only. Wait ~2 min for `[PCLINK] Listening on 0.0.0.0:5800` and `[CPX] Connected`.
   (`bash ~/node_start_ft.sh` on the board does the same in the background, log in `~/node.log`.)
3. PC ground station:
   ```
   cd ~/Desktop/milkv-drone/pc && sudo -E ~/Desktop/milkv-drone/venv/bin/python3 -m pc_node.main --fly --keyboard --viewer --plot --duos-ip 10.2.250.1 --uri radio://0/120/2M/E7E7E7E706
   ```
   Viewer only (no radio, no keyboard forwarding needed): drop `--fly --keyboard --uri ...`.
4. `space` arms takeoff, `i` autonomous, wasd/qe/op manual, `k` kill, `t` dump + finetune, `z` quits the viewer, then Ctrl-C.
5. Training output on the board: `~/milkv/simulation_last.log`; new checkpoints land in `~/milkv/training_quantization/throwaway_models/` and are hot-swapped into the running node.

Redeploy code changes to the board with `bash tools/deploy_duos.sh debian@10.2.250.1 /home/debian/milkv` (datasets and checkpoints on the board are left alone).

## Common example commands:

Duo S (from `milkv/`): `python3 -u -m duos_node.main --fly --ckpt ./training_quantization/throwaway_models/gate_classifier_model.pt --finetune_on_dump --buffer_n 90 --median_k 7`

PC (from `pc/`): `sudo -E ~/Desktop/milkv-drone/venv/bin/python3 -m pc_node.main --fly --keyboard --viewer --plot --show_model_inputs --duos-ip 10.2.250.1 --uri radio://0/120/2M/E7E7E7E706`
