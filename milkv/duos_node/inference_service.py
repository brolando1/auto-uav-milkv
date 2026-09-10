# Runs both models on the Duo S: the PyTorch GateClassifier (p_gate, was in the
# viewer thread) and the TFLite GateNavigator (yaw rate, was in the control
# thread). Results go to the PC as STATE frames.

import threading
from collections import deque
import time
from pathlib import Path

import cv2

import training_quantization.continual_learning.img_preprocessing as img_preprocessing
import training_quantization.continual_learning.tof_preprocessing as tof_preprocessing
from training_quantization.continual_learning.compat import encoder_fingerprint, export_classifier_onnx
from training_quantization.continual_learning.runtime_utils import (
    infer_gate_probability_with_latent,
    OnnxClassifier,
    onnx_sibling,
    onnx_is_fresh,
    load_gate_model,
    infer_gate_probability,
)

from common import protocol
from duos_node.drone_control import GATE_THRESHOLD

DEBUG_INPUTS_HOLD_S = 3.0   # keep relaying model inputs this long after the last request


class ModelManager:
    # holds the live classifier so the orchestrator can hot-swap it after a finetune
    def __init__(self, ckpt_path, device, latent_tap="post_comb1", classifier_backend="onnx"):
        self.device = device
        self.latent_tap = latent_tap    # same tap the finetune trains from (config.json)
        # "onnx": run the checkpoint's .onnx sibling with onnxruntime (~3.5x
        # faster than torch on the Duo S, same numbers); "torch": plain torch.
        self.classifier_backend = classifier_backend if classifier_backend in ("onnx", "torch") else "onnx"
        self._lock = threading.Lock()
        self.model = None               # torch model: fingerprint, and inference fallback
        self.onnx = None                # OnnxClassifier when the .onnx sibling is available
        self.backend_name = "torch"
        self.model_name = "none"
        self.model_gen = 0
        self.encoder_fp = None          # fingerprint of the pre-tap weights of the live model
        self.load(ckpt_path, allow_export=True)

    def load(self, ckpt_path, allow_export=False):
        """allow_export: export a missing .onnx here (only at startup; a hot-swap
        runs on the inference thread and must not block for seconds, the
        training child exports its checkpoint itself)."""
        ckpt_path = Path(ckpt_path)
        print(f"[MODEL] Loading checkpoint: {ckpt_path}")
        model = load_gate_model(str(ckpt_path), self.device)
        fp = encoder_fingerprint(model, self.latent_tap)
        onnx = None
        if self.classifier_backend == "onnx":
            try:
                if not onnx_is_fresh(ckpt_path) and allow_export:
                    t0 = time.monotonic()
                    export_classifier_onnx(model, onnx_sibling(ckpt_path), self.latent_tap)
                    print(f"[MODEL] Exported {onnx_sibling(ckpt_path).name} ({time.monotonic() - t0:.1f}s)")
                if onnx_is_fresh(ckpt_path):
                    onnx = OnnxClassifier(onnx_sibling(ckpt_path))
                else:
                    print(f"[MODEL] WARNING: no fresh {onnx_sibling(ckpt_path).name}, running this checkpoint with torch (slower)")
            except Exception as e:
                print(f"[MODEL] WARNING: onnxruntime classifier unavailable ({e}), running with torch")
                onnx = None
        with self._lock:
            self.model = model
            self.onnx = onnx
            self.backend_name = "onnxruntime" if onnx is not None else "torch"
            self.model_name = ckpt_path.name
            self.model_gen += 1
            self.encoder_fp = fp
        print(f"[MODEL] Loaded {ckpt_path.name} (gen {self.model_gen}, encoder {fp[:10]} @ {self.latent_tap}, inference: {self.backend_name})")

    def infer(self, cam_norm, tof_norm):
        """Returns (p_gate, latent, encoder_fp). The latent is the activation at
        latent_tap, i.e. what the finetune would recompute from the dumped
        frames; the ring buffer keeps it so that pass can be skipped."""
        with self._lock:
            model = self.model
            onnx = self.onnx
            fp = self.encoder_fp
        if onnx is not None:
            p, z = onnx.infer(cam_norm, tof_norm)
        else:
            p, z = infer_gate_probability_with_latent(model, cam_norm, tof_norm, device=self.device, tap=self.latent_tap)
        return p, z, fp


class StageTimer:
    """Rolling per-stage timings of the inference loop (ms), reported in STATE
    as mean / p95 over the last `window` frames so the PC can collect proper
    statistics without touching the board."""

    def __init__(self, window=300):
        self._lock = threading.Lock()
        self._window = int(window)
        self._d = {}
        self._cache = ({}, 0.0)

    def record(self, name, ms):
        with self._lock:
            dq = self._d.get(name)
            if dq is None:
                dq = self._d[name] = deque(maxlen=self._window)
            dq.append(float(ms))

    def summary(self, max_age_s=1.0):
        now = time.monotonic()
        cached, t = self._cache
        if now - t < max_age_s:
            return cached
        out = {}
        with self._lock:
            for name, dq in self._d.items():
                if not dq:
                    continue
                v = sorted(dq)
                out[name] = {"mean": round(sum(v) / len(v), 2),
                             "p95": round(v[int(0.95 * (len(v) - 1))], 2),
                             "n": len(v)}
        self._cache = (out, now)
        return out


def _proc_mem_mb(pid="self"):
    """VmRSS / VmHWM (peak RSS) of a process in MB, or None if it is gone."""
    try:
        rss = hwm = None
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) / 1024.0
                elif line.startswith("VmHWM:"):
                    hwm = int(line.split()[1]) / 1024.0
        return {"rss": round(rss, 1) if rss is not None else None,
                "peak": round(hwm, 1) if hwm is not None else None}
    except OSError:
        return None


def _system_mem_mb():
    try:
        m = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                m[k] = int(v.split()[0]) / 1024.0
        return {"total": round(m["MemTotal"], 1), "available": round(m["MemAvailable"], 1),
                "swap_used": round(m["SwapTotal"] - m["SwapFree"], 1)}
    except (OSError, KeyError):
        return None


class InferenceService:
    def __init__(self, *, pairer, model_manager, pred_filter, ema_filter,
                 orchestrator, pc_link, cpx_link, thr=0.5, cam_preproc="crop",
                 median_k=11, ema_percent=100.0, flight_data=None, flight_status=None,
                 key_state=None, navigator_every=2, navigator_mode="always"):
        self.pairer = pairer
        self.model_manager = model_manager
        self.pred_filter = pred_filter
        self.ema_filter = ema_filter
        self.orchestrator = orchestrator
        self.pc_link = pc_link
        self.cpx_link = cpx_link
        self.flight_data = flight_data      # feeds the local flight controller
        self.flight_status = flight_status  # telemetry from it, relayed in STATE
        self.key_state = key_state          # PC key stream, age shown in STATE
        self.thr = float(thr)
        self.cam_preproc = cam_preproc
        self.median_k = int(median_k)
        self.ema_percent = float(ema_percent)
        # run the navigator on every n-th frame it is needed on (1 = every frame);
        # in between the last yaw rate is reused, the classifier keeps full rate
        self.navigator_every = max(1, int(navigator_every))
        self._nav_frames_needed = 0   # frames since the navigator became needed
        self._last_yaw_rate = 0.0
        # 'always': the navigator runs (decimated) on every frame so the frame
        # rate does not change with the flight mode / gate; its yaw is handed
        # to the controller only when _navigator_needed(). 'gated': old
        # behaviour, it is only computed when needed.
        self.navigator_mode = navigator_mode if navigator_mode in ("always", "gated") else "always"
        self.timing = StageTimer()
        self._mem = ({}, 0.0)

        # needs tflite_runtime (or full TF as fallback); keep going without the
        # navigator so the classifier/relay still work if neither is installed
        self.navigator = None
        try:
            from training_quantization.inference_gate_navigator_in_loop import InferenceGateNavigatorInLoop
            self.navigator = InferenceGateNavigatorInLoop()
            print(f"[INFER] Gate navigator loaded (backend: {self.navigator.backend_name})")
        except Exception as e:
            print(f"[INFER] WARNING: gate navigator unavailable, yaw_rate will stay 0.0 ({e})")

        self.echo_t_pc = None
        self.debug_until = 0.0
        self._running = True
        self._start_time = time.time()
        self._last_time = time.time()
        self._frame_count = 0

    def stop(self):
        self._running = False

    def request_debug_inputs(self):
        # the PC viewer re-requests this with every ping while --show_model_inputs is on
        self.debug_until = time.monotonic() + DEBUG_INPUTS_HOLD_S

    def _publish_debug_inputs(self, cam_decoded, tof_norm, cam_seq):
        # exactly what the models get, so the PC debug window shows the truth
        try:
            cam_uint8 = img_preprocessing.camera_uint8_168(cam_decoded, preproc=self.cam_preproc)
            ok, jpg = cv2.imencode('.jpg', cam_uint8, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if ok:
                self.pc_link.publish(protocol.FRAME_DEBUG,
                                     protocol.encode_debug(cam_seq, time.monotonic(), jpg.tobytes(), tof_norm))
        except Exception as e:
            print(f"[INFER] Debug inputs failed: {e}")

    def _navigator_needed(self, p_gate_ema):
        # The controller uses the navigator's yaw only in auto mode and only
        # while p(gate) >= GATE_THRESHOLD (otherwise ToF obstacle avoidance
        # steers), so the ~55 ms are spent only then. Sensing-only runs
        # (no drone) keep it for the viewer.
        fs = self.flight_status
        if fs is None or fs.get('state') == 'no_drone':
            return True
        return bool(fs.get('auto')) and p_gate_ema >= GATE_THRESHOLD

    def _yield_to_training(self):
        # While a finetune child runs the single core belongs to the training:
        # idle this loop to ~1 Hz (one classifier+navigator pass costs ~200 ms,
        # at 5 Hz the node still took half the core). The only exception is
        # autonomous flight: there the controller consumes the predictions and
        # its stale-prediction watchdog would hover/land the drone within 2 s.
        # Manual flight (keys) and everything on the ground (crash, landed,
        # armed, no --fly) are throttled. The fork happens before the first sleep.
        if self.orchestrator.train_proc is None:
            return
        fs = self.flight_status if self.flight_status is not None else {}
        if fs.get('state') == 'flying' and bool(fs.get('auto')):
            return
        time.sleep(1.0)

    def run(self):
        print("[INFER] Inference loop started")
        while self._running:
            self._yield_to_training()
            pair = self.pairer.latest()
            if pair is None:
                self.orchestrator.poll_training()
                time.sleep(0.005)
                continue

            cam_decoded, tof_mm, tof_validity, tof_meta, _jpeg, cam_seq = pair
            t_arrival = self.pairer.last_t_mon
            t_loop0 = time.perf_counter()
            self._frame_count += 1

            try:
                cam_norm = img_preprocessing.camera_norm_168(cam_decoded, preproc=self.cam_preproc)
            except Exception as e:
                print(f"[INFER] Camera preprocessing failed: {e}")
                continue
            tof_norm = tof_preprocessing.tof_norm_21x21_from_8x8_mm(tof_mm)
            t1 = time.perf_counter()
            self.timing.record("preprocess", (t1 - t_loop0) * 1000.0)

            if time.monotonic() < self.debug_until:
                self._publish_debug_inputs(cam_decoded, tof_norm, cam_seq)

            # classifier -> p_gate (raw -> median -> ema, same as the viewer)
            t1 = time.perf_counter()
            p_gate_raw, latent, encoder_fp = self.model_manager.infer(cam_norm, tof_norm)
            t2 = time.perf_counter()
            self.timing.record("classifier", (t2 - t1) * 1000.0)

            # ring buffer (+ latent for the finetune) + continuous recording
            self.orchestrator.on_pair(cam_norm, tof_norm, latent=latent, encoder_fp=encoder_fp)
            p_gate_med = self.pred_filter.update(p_gate_raw)
            p_gate_ema = self.ema_filter.update(p_gate_med)
            pred = "GATE" if p_gate_ema >= self.thr else "NO_GATE"
            t3 = time.perf_counter()
            self.timing.record("buffer_filters", (t3 - t2) * 1000.0)

            # navigator -> yaw rate (rad/s, scaling stays in the PC control loop).
            # Its ~50 ms only buy something in autonomous mode (the controller
            # ignores yaw_rate otherwise) and in sensing-only runs (no drone),
            # where the viewer shows it; skipped in manual flight / on the ground.
            # With navigator_every=2 it runs on the first frame the gate is
            # needed on and then on every second one; the frames in between
            # reuse the last yaw rate, so the classifier keeps its full rate.
            # navigator_mode 'always' computes it on every frame (constant frame
            # rate), 'gated' only when the controller will use it.
            yaw_needed = self._navigator_needed(p_gate_ema)
            yaw_rate = 0.0
            t3 = time.perf_counter()
            if self.navigator is not None and (yaw_needed or self.navigator_mode == "always"):
                if self._nav_frames_needed % self.navigator_every == 0:
                    try:
                        if cam_decoded.shape[:2] == (168, 168):
                            # the navigator's own preprocessing (preproc='none') equals the
                            # classifier's for a 168x168 frame: reuse cam_norm/tof_norm
                            self.navigator.set_sample_from_normalized(cam_norm, tof_norm)
                            self._last_yaw_rate = float(self.navigator.predict_navigation()[0])
                        elif self.navigator._predict_pre_step(cam_decoded, tof_mm):
                            self._last_yaw_rate = float(self.navigator.predict_navigation()[0])
                    except Exception as e:
                        print(f"[INFER] Navigator failed: {e}")
                    self.timing.record("navigator_run", (time.perf_counter() - t3) * 1000.0)
                self._nav_frames_needed += 1
                yaw_rate = self._last_yaw_rate
            else:
                # gate gone / manual mode: forget the old yaw and make sure the
                # navigator runs again on the very first frame it is needed
                self._nav_frames_needed = 0
                self._last_yaw_rate = 0.0
            t4 = time.perf_counter()
            self.timing.record("navigator_per_frame", (t4 - t3) * 1000.0)

            if self.flight_data is not None:
                # the controller only ever gets a yaw it may act on
                self.flight_data.set_prediction(p_gate_ema, yaw_rate if yaw_needed else 0.0)

            self.orchestrator.poll_training()
            t5 = time.perf_counter()
            self.timing.record("poll_training", (t5 - t4) * 1000.0)

            now = time.time()
            dt = now - self._last_time
            self._last_time = now
            cam_fps_inst = (1.0 / dt) if dt > 1e-6 else 0.0
            cam_fps_avg = self._frame_count / max(1e-6, (now - self._start_time))

            state = {
                "seq": cam_seq,
                "t_duo_mon": time.monotonic(),
                "p_gate_raw": round(p_gate_raw, 4),
                "p_gate_med": round(p_gate_med, 4),
                "p_gate_ema": round(p_gate_ema, 4),
                "yaw_rate": round(yaw_rate, 5),
                "yaw_used": bool(yaw_needed),
                "pred": pred,
                "thr": self.thr,
                "median_k": self.median_k,
                "ema_percent": self.ema_percent,
                "model_name": self.model_manager.model_name,
                "model_gen": self.model_manager.model_gen,
                "classifier_backend": self.model_manager.backend_name,
                "cam_fps_inst": round(cam_fps_inst, 1),
                "cam_fps_avg": round(cam_fps_avg, 1),
                "tof_fps_inst": round(tof_meta.get("fps_inst", 0.0), 1),
                "tof_fps_avg": round(tof_meta.get("fps_avg", 0.0), 1),
                "tof_seq": tof_meta.get("seq"),
                "wifi_ok": self.cpx_link.connected,
                "echo_t_pc": self.echo_t_pc,
                "training": self.orchestrator.training_status(),
                "flight": self._flight_state(),
                "timing_ms": self.timing.summary(),
                "mem_mb": self._mem_snapshot(),
            }
            t6 = time.perf_counter()
            self.timing.record("state_build", (t6 - t5) * 1000.0)
            self.pc_link.publish(protocol.FRAME_STATE, protocol.encode_json(state))
            t7 = time.perf_counter()
            self.timing.record("publish", (t7 - t6) * 1000.0)
            self.timing.record("loop_total", (t7 - t_loop0) * 1000.0)
            if t_arrival is not None:
                # camera frame decoded & paired -> prediction published
                self.timing.record("latency_arrival_to_state", (time.monotonic() - t_arrival) * 1000.0)

        print("[INFER] Inference loop stopped")

    def _mem_snapshot(self, max_age_s=1.0):
        cached, t = self._mem
        now = time.monotonic()
        if now - t < max_age_s:
            return cached
        snap = {"node": _proc_mem_mb("self"), "system": _system_mem_mb(),
                "training": self.orchestrator.training_mem()}
        self._mem = (snap, now)
        return snap

    def _flight_state(self):
        if self.flight_status is None:
            return None
        flight = dict(self.flight_status)
        if self.key_state is not None:
            age = self.key_state.age_s()
            flight["keys_age_s"] = round(age, 2) if age != float('inf') else None
        return flight
