# Crash -> dump -> finetune -> hot-swap machinery, ported from the viewer
# (the old opencv_viewer.py, handle_collision_dump_and_training) so it runs
# headless on the Duo S. The trigger now comes straight from the local flight
# controller ('crash') or as a command from the PC ('dump' = viewer key)
# instead of a local key press / shared_state flag.
#
# The crash visual png + the 18 s p(gate) plot pdf are produced by the PC
# viewer (it has the display and matplotlib): every dump is reported in the
# STATE frame via training_status()['last_dump'] and pc_node/display_viewer.py
# writes the files when it sees a new one.

import threading
import time
from collections import deque
from pathlib import Path

from training_quantization.continual_learning.runtime_utils import (
    ensure_dir,
    wipe_collision_leaf_dirs,
    wipe_leaf_dirs,
    tail_lines,
    make_session_stamp,
    save_pair_at_index,
    dump_collision_buffer_zero_index,
    start_simulation_subprocess,
    start_simulation_forked,
    close_simulation_log_handle,
    save_dumped_latents,
    clear_dumped_latents,
    find_newest_checkpoint,
)

FRAMES_TO_SKIP = 20  # post-impact frames dropped from the dump


class RetrainOrchestrator:
    def __init__(self, *, app_root, model_manager, pred_filter, ema_filter,
                 buffer_n, collision_root, collision_name, collision_label,
                 record_root, record_name,
                 finetune_on_dump, sim_cfg, train_log, throwaway_models_dir,
                 log_tail_lines=10, train_launcher="fork"):
        self.app_root = Path(app_root)
        self.model_manager = model_manager
        self.pred_filter = pred_filter
        self.ema_filter = ema_filter

        self.buffer_n = int(buffer_n)
        self.buffer_data = deque(maxlen=max(1, self.buffer_n))

        base = Path(collision_root) / collision_name / collision_label
        self.collision_name = collision_name
        self.collision_label = collision_label
        self.collision_root = str(collision_root)
        self.collision_cam_dir = base / "camera_images"
        self.collision_tof_dir = base / "tof_distance_array"
        ensure_dir(self.collision_cam_dir)
        ensure_dir(self.collision_tof_dir)

        self.record_root = Path(record_root)
        self.record_name = record_name
        ensure_dir(self.record_root)

        self.finetune_on_dump = bool(finetune_on_dump)
        self.sim_cfg_path = Path(sim_cfg).resolve()
        self.train_log_path = Path(train_log).resolve()
        self.throwaway_models_dir = Path(throwaway_models_dir).resolve()
        self.log_tail_lines = int(log_tail_lines)

        self.crash_log_path = self.app_root / "training_quantization" / "continual_learning" / "crash_events.log"

        self._lock = threading.Lock()
        self.train_proc = None
        self.train_mem = {}
        self._train_mem_t = 0.0
        self.last_train_peak_mb = None
        self.last_train_elapsed = None
        self.train_start_wall = None
        self.train_start_mon = None

        # "fork": the training child is forked off this process by the
        # inference thread (torch already loaded, see start_simulation_forked).
        # "subprocess": fresh interpreter (slow on the Duo S, always safe).
        self.train_launcher = train_launcher if train_launcher in ("fork", "subprocess") else "fork"
        self._fork_pending_since = None          # monotonic time of a queued fork
        self._fork_fallback_after_s = 10.0       # no inference thread around -> subprocess

        # a dump requested while a training is running is handled after it
        # finishes (same as the viewer's "dump deferred")
        self.pending_dump = None

        # last dump, relayed to the PC so it can save the visual + plot
        self.dump_count = 0
        self.last_dump = None

        self.recording_active = False
        self.recording_session_dir = None
        self.recording_cam_dir = None
        self.recording_tof_dir = None
        self.recording_idx = 0

        self.frame_count = 0
        self.status_msg = ""
        self.status_until = 0.0

    def _set_status(self, msg, seconds=3.0):
        print(f"[ORCH] {msg}")
        self.status_msg = msg
        self.status_until = time.time() + float(seconds)

    # called by the inference loop on every paired frame (normalized inputs)
    def on_pair(self, cam_norm, tof_norm, latent=None, encoder_fp=None):
        with self._lock:
            self.frame_count += 1
            self.buffer_data.append((cam_norm, tof_norm, latent, encoder_fp))
            if self.recording_active and self.recording_cam_dir is not None:
                save_pair_at_index(
                    cam_arr=cam_norm,
                    tof_arr=tof_norm,
                    cam_dir=self.recording_cam_dir,
                    tof_dir=self.recording_tof_dir,
                    idx=self.recording_idx,
                )
                self.recording_idx += 1

    def start_recording(self):
        with self._lock:
            if self.recording_active:
                self._set_status("Recording already active.", 2.0)
                return
            session_name = make_session_stamp()
            self.recording_session_dir = self.record_root / self.record_name / session_name
            self.recording_cam_dir = self.recording_session_dir / "camera_images"
            self.recording_tof_dir = self.recording_session_dir / "tof_distance_array"
            wipe_leaf_dirs(self.recording_cam_dir, self.recording_tof_dir)
            self.recording_idx = 0
            self.recording_active = True
            self._set_status(f"Recording started: {session_name}", 2.5)

    def stop_recording(self):
        with self._lock:
            if not self.recording_active:
                self._set_status("Recording is not active.", 2.0)
                return
            self.recording_active = False
            self._set_status(f"Recording stopped: saved {self.recording_idx} samples", 3.0)

    # 'crash' from the flight controller or 'dump' from the viewer key
    def trigger_dump(self, source="dump"):
        with self._lock:
            # Like the viewer: a trigger during a running training is kept
            # pending and handled once the subprocess finishes.
            if self.train_proc is not None:
                self.pending_dump = source
                self._set_status("Training already running: dump deferred.", 2.0)
                return False
            return self._dump_locked(source)

    def _dump_locked(self, source):
        # caller holds self._lock
        if len(self.buffer_data) == 0:
            self._set_status("Buffer empty (nothing to save)", 2.0)
            return False

        # Wipe old data on disk and save from 0
        try:
            wipe_collision_leaf_dirs(self.collision_cam_dir, self.collision_tof_dir)
        except Exception as e:
            self._set_status(f"Failed to wipe dataset dirs: {e}", 3.0)
            return False

        buffer_list = list(self.buffer_data)
        if len(buffer_list) > FRAMES_TO_SKIP:
            data_to_dump = buffer_list[:-FRAMES_TO_SKIP]
            skipped_n = FRAMES_TO_SKIP
        else:
            data_to_dump = buffer_list
            skipped_n = 0
            print(f"[WARN] Buffer too short to skip {FRAMES_TO_SKIP} frames.")

        saved_n = dump_collision_buffer_zero_index(
            buffer_data=[(e[0], e[1]) for e in data_to_dump],
            cam_dir=self.collision_cam_dir,
            tof_dir=self.collision_tof_dir,
        )
        print(f"[INFO] Collision dump: saved {saved_n}(skipped {skipped_n}) samples -> {self.collision_cam_dir.parent}")

        # Latents computed by the node at inference time: written next to the
        # frames so the finetune skips its encoder pass. Only if every frame
        # has one from the same pre-tap weights, otherwise the finetune recomputes.
        leaf_dir = self.collision_cam_dir.parent
        clear_dumped_latents(leaf_dir)
        fps = {e[3] for e in data_to_dump}
        if data_to_dump and all(e[2] is not None for e in data_to_dump) and len(fps) == 1 and None not in fps:
            try:
                n_lat = save_dumped_latents(
                    leaf_dir, [e[2] for e in data_to_dump],
                    tap=self.model_manager.latent_tap, encoder_fp=next(iter(fps)),
                    model_name=self.model_manager.model_name)
                print(f"[INFO] Collision dump: saved {n_lat} inference latents ({self.model_manager.latent_tap}) for the finetune")
            except Exception as e:
                print(f"[WARN] Could not save inference latents, the finetune will recompute them: {e}")
                clear_dumped_latents(leaf_dir)
        else:
            print("[INFO] Collision dump: no reusable inference latents (mixed or missing), the finetune will recompute them")
        self._set_status(f"Saved {saved_n} samples (skipped {skipped_n})(index reset to 0)", 2.5)

        reason = "crash" if source == "crash" else "manual"
        crash_id = self._write_crash_log(reason, source, saved_n, skipped_n)

        self.dump_count += 1
        self.last_dump = {
            "n": self.dump_count,
            "id": crash_id,
            "reason": reason,
            "source": source,
            "target": f"{self.collision_name}/{self.collision_label}",
            "saved_n": saved_n,
            "skipped_n": skipped_n,
            "model": self.model_manager.model_name,
        }

        if self.finetune_on_dump:
            self._start_finetune()
        return True

    def _write_crash_log(self, reason, source, saved_n, skipped_n):
        crash_id = make_session_stamp()
        last_frame_idx = max(0, saved_n - 1)
        collision_end_frame = self.frame_count - skipped_n
        collision_start_frame = max(1, self.frame_count - saved_n + 1)

        log_msg = (
            f"{reason.upper()} DUMP TRIGGERED: {crash_id} (source={source})\n"
            f"  - Target: {self.collision_name}/{self.collision_label}\n"
            f"  - Total Frames: {saved_n}\n"
            f"  - Dumped Files: {self.collision_root}/{self.collision_name} -> 000000.npy to {last_frame_idx:06d}.npy\n"
            f"  - Collision Frames: {collision_start_frame} to {collision_end_frame}\n"
            f"  - Model in use: {self.model_manager.model_name}\n"
            f"  - Visual/plot: saved by the PC viewer as crash_{crash_id}_visual.png / crash_{crash_id}_plot.pdf\n"
            f"--------------------------------------------------\n"
        )
        try:
            with open(self.crash_log_path, "a", encoding="utf-8") as f:
                f.write(log_msg)
            print(f"[INFO] Crash event logged to {self.crash_log_path}")
        except Exception as e:
            print(f"[WARN] Could not write to crash log: {e}")
        return crash_id

    def _start_finetune(self):
        # caller holds self._lock
        if not self.sim_cfg_path.exists():
            self._set_status(f"Config not found for simulation.py: {self.sim_cfg_path}", 3.0)
            return
        if self.train_launcher == "fork":
            # The fork itself is done by the inference thread in poll_training():
            # that thread is then provably outside torch/cv2 (see runtime_utils).
            self._fork_pending_since = time.monotonic()
            self._set_status("TRAINING QUEUED (fork on next inference tick)", 3.0)
            return
        self._launch_locked("subprocess")

    def _launch_locked(self, how):
        # caller holds self._lock
        try:
            if how == "fork":
                self.train_proc, self.train_start_wall = start_simulation_forked(
                    app_root=self.app_root, cfg_path=self.sim_cfg_path, log_path=self.train_log_path)
            else:
                self.train_proc, self.train_start_wall = start_simulation_subprocess(
                    app_root=self.app_root, cfg_path=self.sim_cfg_path, log_path=self.train_log_path)
            self.train_start_mon = time.monotonic()
            self._fork_pending_since = None
            print("================================================================")
            print(f"[DUOS] TRAINING STARTED (simulation.py, {how}, pid={self.train_proc.pid})")
            print(f"  cfg = {self.sim_cfg_path}")
            print(f"  log = {self.train_log_path}")
            print("================================================================")
            self._set_status(f"TRAINING STARTED ({how})", 3.0)
        except Exception as e:
            self._set_status(f"Failed to start training ({how}): {e}", 3.0)
            print(f"[DUOS] Failed to start training ({how}): {e}")
            self.train_proc = None
            self._fork_pending_since = None

    def _service_pending_fork_locked(self, from_inference_thread):
        # caller holds self._lock
        if self._fork_pending_since is None or self.train_proc is not None:
            return
        if from_inference_thread:
            self._launch_locked("fork")
        elif time.monotonic() - self._fork_pending_since > self._fork_fallback_after_s:
            print("[DUOS] Inference thread did not pick up the queued fork, falling back to a subprocess")
            self._launch_locked("subprocess")

    # called periodically from the inference loop; hot-swaps the model when the
    # subprocess finishes (same flow as the viewer's non-blocking poll)
    def _sample_train_mem_locked(self):
        # RSS / peak RSS of the running training child (from /proc), ~2 Hz
        proc = self.train_proc
        if proc is None:
            return
        now = time.monotonic()
        if now - self._train_mem_t < 0.5:
            return
        self._train_mem_t = now
        try:
            rss = hwm = None
            with open(f"/proc/{proc.pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1]) / 1024.0
                    elif line.startswith("VmHWM:"):
                        hwm = int(line.split()[1]) / 1024.0
            if rss is not None:
                self.train_mem = {"rss": round(rss, 1), "peak": round(hwm or rss, 1)}
        except OSError:
            pass

    def training_mem(self):
        with self._lock:
            return {"running": self.train_mem if self.train_proc is not None else None,
                    "last_peak": self.last_train_peak_mb,
                    "last_elapsed": self.last_train_elapsed}

    def poll_training(self):
        # called only by the inference thread, at points where it is outside
        # torch/cv2: this is where a queued fork is executed
        with self._lock:
            self._service_pending_fork_locked(from_inference_thread=True)
            if self.train_proc is None:
                return
            self._sample_train_mem_locked()
            rc = self.train_proc.poll()
            if rc is None:
                return
            if self.train_mem:
                self.last_train_peak_mb = self.train_mem.get("peak")

            close_simulation_log_handle(self.train_proc)
            elapsed = 0.0
            if self.train_start_mon is not None:
                elapsed = time.monotonic() - self.train_start_mon
            self._set_status(f"TRAINING: finished rc={rc} ({elapsed:.1f}s)", 3.0)
            self.last_train_elapsed = round(elapsed, 2)

            after = self.train_start_wall if self.train_start_wall is not None else time.time()
            self.train_proc = None
            self.train_start_wall = None
            self.train_start_mon = None

            new_ckpt = find_newest_checkpoint(self.throwaway_models_dir, after_wall_time=float(after))
            if new_ckpt is None:
                self._set_status("Training finished but no new ckpt found.", 3.0)
            else:
                try:
                    self.model_manager.load(new_ckpt)
                    self._set_status(f"Loaded new model: {new_ckpt.name} | buffer cleared | median+ema reset", 3.0)
                except Exception as e:
                    self._set_status(f"Training finished, but failed to load new model: {e}", 4.0)

            # A dump that was requested while training ran: do it now with the
            # frames collected since, before the buffer is cleared.
            pending = self.pending_dump
            self.pending_dump = None
            if pending is not None:
                self._set_status(f"Running deferred dump (source={pending})", 3.0)
                self._dump_locked(pending)

            self.buffer_data.clear()
            self.pred_filter.reset()
            self.ema_filter.reset()

    def training_status(self):
        with self._lock:
            # safety net if the inference thread is gone (called from the PC link)
            self._service_pending_fork_locked(from_inference_thread=False)
            status = {"state": "idle", "elapsed": 0.0, "rc": None, "log_tail": [],
                      "launcher": self.train_launcher}
            if self._fork_pending_since is not None and self.train_proc is None:
                status["state"] = "queued"
            if self.train_proc is not None:
                elapsed = 0.0
                if self.train_start_mon is not None:
                    elapsed = time.monotonic() - self.train_start_mon
                status["state"] = "running"
                status["elapsed"] = round(elapsed, 1)
                status["log_tail"] = tail_lines(self.train_log_path, max_bytes=20000, max_lines=self.log_tail_lines)

            status["pending_dump"] = self.pending_dump
            status["last_dump"] = self.last_dump
            status["recording"] = self.recording_active
            status["recording_saved"] = self.recording_idx
            if self.status_msg and time.time() < self.status_until:
                status["status_msg"] = self.status_msg
            return status

    def shutdown(self):
        with self._lock:
            if self.train_proc is not None and self.train_proc.poll() is None:
                print("[INFO] Terminating training subprocess...")
                try:
                    self.train_proc.terminate()
                except Exception:
                    pass
                t0 = time.time()
                while time.time() - t0 < 1.5:
                    if self.train_proc.poll() is not None:
                        break
                    time.sleep(0.05)
                if self.train_proc.poll() is None:
                    try:
                        self.train_proc.kill()
                    except Exception:
                        pass
            if self.train_proc is not None:
                close_simulation_log_handle(self.train_proc)
                self.train_proc = None
