# Inference loop on the Duo S: gate classifier (p_gate) and gate navigator
# (yaw rate) on every paired camera/ToF frame. Results go to the PC as STATE frames.

import threading
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
)

from common import protocol
from duos_node.drone_control import GATE_THRESHOLD

DEBUG_INPUTS_HOLD_S = 3.0   # keep relaying model inputs this long after the last request


class ModelManager:
    # holds the live classifier so the orchestrator can hot-swap it after a finetune
    def __init__(self, ckpt_path, device, latent_tap="post_comb1", classifier_backend="onnx"):
        self.device = device
        self.latent_tap = latent_tap    # same tap the finetune trains from (config.json)
        # "onnx": run the checkpoint's .onnx sibling with onnxruntime, "torch": plain torch
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
        # 'always': the navigator runs on every frame (constant frame rate), its yaw
        # is handed to the controller only when _navigator_needed(). 'gated': it
        # only runs when needed.
        self.navigator_mode = navigator_mode if navigator_mode in ("always", "gated") else "always"

        # keep going without the navigator (no tflite/onnxruntime backend) so the
        # classifier and the relay still work
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
        # the controller uses the navigator's yaw only in auto mode while
        # p(gate) >= GATE_THRESHOLD; sensing-only runs (no drone) keep it for the viewer
        fs = self.flight_status
        if fs is None or fs.get('state') == 'no_drone':
            return True
        return bool(fs.get('auto')) and p_gate_ema >= GATE_THRESHOLD

    def _yield_to_training(self):
        # while a finetune child runs, idle this loop to ~1 Hz so the training gets
        # the core. Not in autonomous flight: there the controller needs the
        # predictions, its watchdog would land the drone otherwise.
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
            self._frame_count += 1

            try:
                cam_norm = img_preprocessing.camera_norm_168(cam_decoded, preproc=self.cam_preproc)
            except Exception as e:
                print(f"[INFER] Camera preprocessing failed: {e}")
                continue
            tof_norm = tof_preprocessing.tof_norm_21x21_from_8x8_mm(tof_mm)

            if time.monotonic() < self.debug_until:
                self._publish_debug_inputs(cam_decoded, tof_norm, cam_seq)

            # classifier -> p_gate (raw -> median -> ema, same as the viewer)
            p_gate_raw, latent, encoder_fp = self.model_manager.infer(cam_norm, tof_norm)

            # ring buffer (+ latent for the finetune) + continuous recording
            self.orchestrator.on_pair(cam_norm, tof_norm, latent=latent, encoder_fp=encoder_fp)
            p_gate_med = self.pred_filter.update(p_gate_raw)
            p_gate_ema = self.ema_filter.update(p_gate_med)
            pred = "GATE" if p_gate_ema >= self.thr else "NO_GATE"

            # navigator -> yaw rate (rad/s). Runs on every navigator_every-th frame,
            # the frames in between reuse the last yaw rate.
            yaw_needed = self._navigator_needed(p_gate_ema)
            yaw_rate = 0.0
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
                self._nav_frames_needed += 1
                yaw_rate = self._last_yaw_rate
            else:
                # gate gone / manual mode: forget the old yaw and make sure the
                # navigator runs again on the very first frame it is needed
                self._nav_frames_needed = 0
                self._last_yaw_rate = 0.0

            if self.flight_data is not None:
                # the controller only ever gets a yaw it may act on
                self.flight_data.set_prediction(p_gate_ema, yaw_rate if yaw_needed else 0.0)

            self.orchestrator.poll_training()

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
            }
            self.pc_link.publish(protocol.FRAME_STATE, protocol.encode_json(state))

        print("[INFER] Inference loop stopped")

    def _flight_state(self):
        if self.flight_status is None:
            return None
        flight = dict(self.flight_status)
        if self.key_state is not None:
            age = self.key_state.age_s()
            flight["keys_age_s"] = round(age, 2) if age != float('inf') else None
        return flight
