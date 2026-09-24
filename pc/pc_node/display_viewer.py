# Viewer on the PC. All numbers come from the STATE frames of the Duo S, the
# keys turn into commands to the Duo S.
#
# Keys come from a global keyboard hook (cv2.waitKey only sees keys while an
# OpenCV window has focus):
#   z = quit viewer, t = dump+finetune (--buffer_key), r = record start,
#   b = record stop. The flight keys are forwarded by pc_node/main.py.
#
# The dump and the retraining happen on the Duo S, the crash visual png and the
# 18 s p(gate) plot pdf are written here into pc/crash_events/: the STATE frame
# reports every dump (training.last_dump) and the viewer reacts to it even when
# no camera frame is arriving.

import argparse
import threading
import time
from collections import deque
from pathlib import Path
from typing import Deque, Optional, Tuple

import cv2
import keyboard
import numpy as np

from pc_node.camera_tof_pairing import paired_buffer, buffer_lock
from pc_node.ui import (
    overlay_text,
    render_tof_heatmap_panel,
    render_tof_heatmap_panel_mm,
    resize_keep_aspect,
    render_camera_input_panel,
    make_debug_grid_2x2,
    hstack_resize_to_height,
    RealTimeProbabilityPlot,
)

PING_PERIOD_S = 1.0
KEY_DEBOUNCE_S = 0.4
PLOT_HISTORY_S = 18.0


def remote_viewer(shared_state, link):
    parser = argparse.ArgumentParser(description="Ground station viewer (inference on the Duo S)")
    parser.add_argument("--window", type=str, default="AI-deck + ToF + p(gate) [remote]")
    parser.add_argument("--panel_h", type=int, default=360)
    parser.add_argument("--tof_vis_min", type=float, default=200.0)
    parser.add_argument("--tof_vis_max", type=float, default=4000.0)
    parser.add_argument("--tof_panel_size", type=int, default=320)
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--plot_window", type=str, default="p(gate) realtime")
    parser.add_argument("--plot_history_s", type=float, default=30.0)
    parser.add_argument("--plot_w", type=int, default=640)
    parser.add_argument("--plot_h", type=int, default=240)
    parser.add_argument("--buffer_key", type=str, default="t",
                        help="Press this key to dump the Duo S ring buffer (+ finetune if the node runs with --finetune_on_dump)")
    parser.add_argument("--record_start_key", type=str, default="r")
    parser.add_argument("--record_stop_key", type=str, default="b")
    # Debug/model-input visualization (the Duo S relays its real model inputs while this is on)
    parser.add_argument("--show_model_inputs", action="store_true",
                        help="Show a debug window with the raw camera/ToF next to the model inputs the Duo S feeds its models.")
    parser.add_argument("--debug_window", type=str, default="Raw + model inputs")
    parser.add_argument("--debug_panel_size", type=int, default=300)
    args, _ = parser.parse_known_args()

    # Validate single-char keys + avoid key conflicts
    keys_used = {
        "buffer_key": args.buffer_key,
        "record_start_key": args.record_start_key,
        "record_stop_key": args.record_stop_key,
    }
    for key_name, key in keys_used.items():
        if len(key) != 1:
            raise ValueError(f"--{key_name} must be a single character.")
    if len(set(keys_used.values())) != len(keys_used):
        raise ValueError(
            f"Key conflict detected: {keys_used}. "
            "Use different keys for collision dump, record start, and record stop."
        )

    # Crash artifacts (visual png, p(gate) plot pdf, log) go to pc/crash_events/
    crash_dir = Path(__file__).resolve().parent.parent / "crash_events"
    crash_log_path = crash_dir / "crash_events.log"

    plotter: Optional[RealTimeProbabilityPlot] = None
    if args.plot:
        plotter = RealTimeProbabilityPlot(
            history_s=float(args.plot_history_s),
            width=int(args.plot_w),
            height=int(args.plot_h),
            title="p(gate) vs time (from Duo S)",
        )

    start_time = time.time()
    last_ping = 0.0
    last_model_gen = None
    last_dump_n: Optional[int] = None
    last_state_mon = 0.0
    state_count = 0                                  # STATE frames = inferences on the Duo S
    plot_history_18s: Deque[Tuple[float, float]] = deque()
    last_combined_frame: Optional[np.ndarray] = None
    status_msg = ""
    status_until = 0.0

    def set_status(msg: str, seconds: float = 3.0) -> None:
        nonlocal status_msg, status_until
        status_msg = msg
        status_until = time.time() + float(seconds)

    # -------------------------------------------------------------------------
    # Global key capture (keyboard hook instead of cv2.waitKey)
    # -------------------------------------------------------------------------
    pending_keys: set = set()
    pending_keys_lock = threading.Lock()
    last_key_time: dict = {}

    def on_key_event(event) -> None:
        name = getattr(event, "name", None)
        if not name:
            return
        now_k = time.time()
        # Ignore auto-repeat while a key is held down
        if now_k - last_key_time.get(name, 0.0) < KEY_DEBOUNCE_S:
            return
        last_key_time[name] = now_k
        with pending_keys_lock:
            pending_keys.add(name)

    def take_pressed_keys() -> set:
        with pending_keys_lock:
            keys = set(pending_keys)
            pending_keys.clear()
        return keys

    key_hook = keyboard.on_press(on_key_event)
    print("[INFO] Key capture: global keyboard hook (works without window focus)")

    def save_crash_artifacts(dump: dict) -> None:
        # png of the last combined frame + pdf of the 18 s p(gate) history, plus
        # a ground-station entry in crash_events.log (the Duo S keeps its own)
        crash_id = str(dump.get("id") or time.strftime("%Y%m%d_%H%M%S"))
        reason = str(dump.get("reason", "crash"))
        crash_dir.mkdir(parents=True, exist_ok=True)

        img_save_path = crash_dir / f"crash_{crash_id}_visual.png"
        if last_combined_frame is not None:
            try:
                cv2.imwrite(str(img_save_path), last_combined_frame)
            except Exception as e:
                print(f"[WARN] Failed to save crash visual: {e}")
        else:
            print("[WARN] No camera frame received yet, crash visual not saved")

        plot_frames_count = len(plot_history_18s)
        plot_start_frame = max(1, state_count - plot_frames_count + 1)
        plot_save_path = crash_dir / f"crash_{crash_id}_plot.pdf"
        try:
            import matplotlib.pyplot as plt
            t_vals = [item[0] for item in plot_history_18s]
            p_vals = [item[1] for item in plot_history_18s]

            # Normalize time so the graph starts at 0.0s
            if t_vals:
                t0 = t_vals[0]
                t_vals = [t - t0 for t in t_vals]

            avg_fps_18s = plot_frames_count / PLOT_HISTORY_S if plot_frames_count > 0 else 0.0

            plt.figure(figsize=(10, 4))
            plt.plot(t_vals, p_vals, label="p(gate) EMA", color='#4c72b0')  # standard blue
            plt.axhline(y=0.5, color='steelblue', linestyle='--', linewidth=1)
            plt.ylim(-0.05, 1.05)
            plt.title(f"Confidence vs Time | frames {plot_start_frame}-{state_count} @ {avg_fps_18s:.1f} fps", fontsize=10)
            plt.xlabel("Tempo [s] (t=0 all frame start)", fontsize=9)
            plt.ylabel("p(gate)", fontsize=9)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(str(plot_save_path), dpi=150)
            plt.close()
        except Exception as e:
            print(f"[WARN] Failed to save crash plot: {e}")

        log_msg = (
            f"{reason.upper()} DUMP TRIGGERED: {crash_id} (on the Duo S, source={dump.get('source', '?')})\n"
            f"  - Target: {dump.get('target', '?')}\n"
            f"  - Total Frames: {dump.get('saved_n', '?')} (skipped {dump.get('skipped_n', '?')})\n"
            f"  - Plot Frames (18s context): {plot_start_frame} to {state_count}\n"
            f"  - Model in use: {dump.get('model', '?')}\n"
            f"  - Files: {img_save_path.name}, {plot_save_path.name}\n"
            f"--------------------------------------------------\n"
        )
        try:
            with open(crash_log_path, "a", encoding="utf-8") as f:
                f.write(log_msg)
            print(f"[INFO] Crash event logged to {crash_log_path}")
        except Exception as e:
            print(f"[WARN] Could not write to crash log: {e}")

        set_status(f"Duo S {reason} dump {crash_id}: visual + plot saved", 4.0)

    try:
        while True:
            # Pump the OpenCV GUI event loop; keys come from the hook, not waitKey
            cv2.waitKey(1)
            keys = take_pressed_keys()
            if "z" in keys:
                break

            now = time.time()
            if now - last_ping > PING_PERIOD_S:
                link.send_command({'cmd': 'ping'})
                if args.show_model_inputs:
                    link.send_command({'cmd': 'debug_inputs'})   # keep the Duo S relaying its model inputs
                last_ping = now

            remote = link.snapshot()
            training = remote.get('training', {}) or {}

            # One plot sample per STATE frame (= per inference on the Duo S)
            if remote['t_state_mon'] > 0.0 and remote['t_state_mon'] != last_state_mon:
                last_state_mon = remote['t_state_mon']
                state_count += 1
                p_gate_ema = float(remote['p_gate_ema'])
                plot_history_18s.append((now, p_gate_ema))
                while plot_history_18s and (now - plot_history_18s[0][0]) > PLOT_HISTORY_S:
                    plot_history_18s.popleft()
                if plotter is not None:
                    plotter.add(now - start_time, p_gate_ema)
                    cv2.imshow(args.plot_window, plotter.render())

                # notify once when a finetuned model got hot-swapped in on the Duo S
                if last_model_gen is not None and remote['model_gen'] != last_model_gen:
                    set_status(f"Duo S loaded new model: {remote['model_name']}", 4.0)
                last_model_gen = remote['model_gen']

                # A crash/manual dump happened on the Duo S -> save visual + plot
                # here. Checked on every STATE frame, so it also works when no
                # camera frame arrives (drone on the floor after a crash).
                dump = training.get('last_dump')
                dump_n = int((dump or {}).get('n', 0))
                if last_dump_n is None:
                    last_dump_n = dump_n        # dumps from before this viewer started are skipped
                elif dump_n != last_dump_n:
                    last_dump_n = dump_n
                    if dump:
                        save_crash_artifacts(dump)

            # Viewer keys -> commands to the Duo S
            if args.buffer_key in keys:
                if link.send_command({'cmd': 'dump'}):
                    set_status("Dump+finetune requested on Duo S", 2.5)
            if args.record_start_key in keys:
                if link.send_command({'cmd': 'record_start'}):
                    set_status("Recording start requested", 2.0)
            if args.record_stop_key in keys:
                if link.send_command({'cmd': 'record_stop'}):
                    set_status("Recording stop requested", 2.0)

            pair = None
            with buffer_lock:
                if len(paired_buffer) > 0:
                    pair = paired_buffer[-1]
                    paired_buffer.clear()

            if pair is None:
                time.sleep(0.01)
                continue

            cam_decoded, latest_tof_mm, meta = pair
            p_gate_ema = float(remote['p_gate_ema'])

            age_ms = (time.monotonic() - meta['t_mon']) * 1000.0
            seq_str = "seq=NA" if meta['seq'] is None else f"seq={meta['seq']}"
            age_str = f"age={age_ms:.0f}ms"

            tof_panel = render_tof_heatmap_panel_mm(
                latest_tof_mm,
                panel_size=int(args.tof_panel_size),
                vmin_mm=float(args.tof_vis_min),
                vmax_mm=float(args.tof_vis_max),
                draw_grid=True,
                title="ToF 8x8 (mm)",
                bottom_text=f"{seq_str}  {age_str}  tof_fps={meta['fps_inst']:.1f}Hz (avg {meta['fps_avg']:.1f})",
            )

            if cam_decoded is None or cam_decoded.size == 0:
                continue
            if cam_decoded.ndim == 2:
                cam3d = cv2.cvtColor(cam_decoded, cv2.COLOR_GRAY2BGR)
            else:
                cam3d = cam_decoded

            try:
                combined = hstack_resize_to_height(cam3d, tof_panel, height=int(args.panel_h))
                last_combined_frame = combined
            except Exception as e:
                print(f"[ERROR] hstack failed : {e}")
                continue

            flight = remote.get('flight') or {}
            if flight:
                flight_line = (
                    f"FLIGHT: {flight.get('state', '?')}  auto={flight.get('auto', False)}  "
                    f"z={flight.get('z', 0.0):.2f}m  rpy=({flight.get('roll', 0.0):.0f},"
                    f"{flight.get('pitch', 0.0):.0f},{flight.get('yaw', 0.0):.0f})  "
                    f"tumbled={flight.get('tumbled', 0)}"
                )
            else:
                flight_line = "FLIGHT: controller not running on Duo S"

            train_state = training.get('state', 'idle')
            if train_state == 'running':
                training_state_line = f"TRAINING: running ({training.get('elapsed', 0.0)}s) [on Duo S]"
            else:
                training_state_line = "TRAINING: idle"

            if training.get('recording'):
                rec_line = f"RECORDING: ON  saved={training.get('recording_saved', 0)} [on Duo S]"
            else:
                rec_line = "RECORDING: OFF"

            state_age = link.state_age_s()
            rtt_str = "NA"
            if remote.get('echo_t_pc'):
                rtt_str = f"{(time.monotonic() - float(remote['echo_t_pc'])) * 1000.0:.0f}ms"

            overlay_lines = [
                f"p(gate) raw={remote['p_gate_raw']:.3f}   med={remote['p_gate_med']:.3f}   "
                f"ema={p_gate_ema:.3f}   pred={remote['pred']}",
                f"CAM FPS inst/avg = {remote['cam_fps_inst']:.1f} / {remote['cam_fps_avg']:.1f}   yaw={remote['yaw_rate']:.3f} rad/s",
                f"TOF FPS inst/avg = {meta['fps_inst']:.1f} / {meta['fps_avg']:.1f}",
                f"ToF: {seq_str}, {age_str}  (paired as: camera_frame + latest_ToF)",
                f"Model: {remote['model_name']} (gen {remote['model_gen']})",
                f"Link: {'OK' if remote['link_ok'] else 'DOWN'}  state_age={state_age * 1000.0:.0f}ms  rtt={rtt_str}  "
                f"wifi(deck<->duo)={'OK' if remote['wifi_ok'] else 'DOWN'}",
                flight_line,
                rec_line,
                training_state_line,
            ]

            log_tail = training.get('log_tail') or []
            if log_tail:
                overlay_lines.append("--- simulation.py tail (Duo S) ---")
                overlay_lines.extend(log_tail)

            if training.get('status_msg'):
                overlay_lines.append(f"[Duo S] {training['status_msg']}")

            overlay_lines.append(
                f"Keys: z=quit_viewer, {args.buffer_key}=dump+finetune, "
                f"{args.record_start_key}=start_rec, {args.record_stop_key}=stop_rec"
            )
            overlay_lines.append("Flight keys: space=takeoff, i=auto, wasd/qe/op=manual, k=kill")
            if args.show_model_inputs:
                overlay_lines.append("Debug view ON: raw + transformed model inputs")

            if state_age > 0.5:
                overlay_lines.append(f"!!! DUO S STREAM STALE ({state_age:.1f}s) !!!")
            if train_state == 'running':
                overlay_lines.append("!! TRAINING RUNNING - do not fly !!")
            if training.get('pending_dump'):
                overlay_lines.append("!! dump deferred until the training finishes !!")

            if status_msg and now < status_until:
                overlay_lines.append(status_msg)

            shown = overlay_text(combined, overlay_lines)
            cv2.imshow(args.window, shown)

            if args.show_model_inputs:
                dbg = link.latest_debug()   # what the Duo S actually fed the models
                if dbg is not None:
                    cam_uint8, tof_norm, _dbg_seq = dbg
                    debug_panel_size = int(args.debug_panel_size)

                    cam_raw_panel = resize_keep_aspect(cam_decoded, debug_panel_size)
                    cam_raw_panel = cv2.resize(cam_raw_panel, (debug_panel_size, debug_panel_size), interpolation=cv2.INTER_AREA)
                    if cam_raw_panel.ndim == 2:
                        cam_raw_panel = cv2.cvtColor(cam_raw_panel, cv2.COLOR_GRAY2BGR)
                    cv2.rectangle(cam_raw_panel, (0, 0), (debug_panel_size - 1, 28), (0, 0, 0), -1)
                    cv2.putText(cam_raw_panel, "Camera decoded/raw", (10, 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)

                    cam_model_panel = render_camera_input_panel(
                        cam_uint8,
                        panel_size=debug_panel_size,
                        title="Camera model input",
                        bottom_text=f"{cam_uint8.shape[1]}x{cam_uint8.shape[0]} uint8 -> norm",
                    )
                    tof_raw_panel = render_tof_heatmap_panel_mm(
                        latest_tof_mm,
                        panel_size=debug_panel_size,
                        vmin_mm=float(args.tof_vis_min),
                        vmax_mm=float(args.tof_vis_max),
                        draw_grid=True,
                        title="ToF raw 8x8 (mm)",
                        bottom_text=seq_str,
                    )
                    tof_model_panel = render_tof_heatmap_panel(
                        tof_norm,
                        panel_size=debug_panel_size,
                        vmin=-4.0,
                        vmax=4.0,
                        draw_grid=True,
                        title="ToF model input",
                        bottom_text="21x21 standardized",
                    )
                    cv2.imshow(args.debug_window, make_debug_grid_2x2(cam_raw_panel, cam_model_panel, tof_raw_panel, tof_model_panel))

    except KeyboardInterrupt:
        pass
    finally:
        try:
            keyboard.unhook(key_hook)
        except Exception:
            pass
        cv2.destroyAllWindows()
        print("[INFO] Viewer exiting.")
