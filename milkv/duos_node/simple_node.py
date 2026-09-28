#!/usr/bin/env python3
# Minimal version of the Duo S node, without the drone.
#
# The real node (duos_node/main.py, inference_service.py, retrain_orchestrator.py)
# also talks to the AI-deck, the PC and the flight controller. This file keeps
# only the learning loop:
#
#   frame -> classifier -> p(gate) + latent -> ring buffer
#         -> navigator -> yaw rate
#         -> crash: write the buffer to disk (frames + latents), finetune on it,
#            load the new checkpoint
#
# It calls the same functions as the node (preprocessing, model, ONNX export,
# dump format), so the numbers are the same.
#
# Run from milkv/:
#   python3 -m duos_node.simple_node --ckpt training_quantization/model/gate_classifier_model.pt
#   python3 -m duos_node.simple_node --ckpt <model.pt> --frames <dir> --loop --fps 25
#   python3 -m duos_node.simple_node --ckpt <model.pt> --frames <dir> --dump_at 300 --finetune_on_dump
#
# --frames is a folder with camera_images/*.npy and tof_distance_array/*.npy
# (normalized float32 168x168 and 21x21, the format of every dataset in this
# repo). Without it random frames are used. Type d + Enter to simulate a crash,
# q + Enter to quit. --finetune_on_dump needs the dataset and a seed checkpoint
# in training_quantization/throwaway_models/, see the README.

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import training_quantization.continual_learning.env_safety  # noqa: F401,E402  single-thread BLAS, before numpy/torch

import argparse                                  # noqa: E402
import json                                      # noqa: E402
import threading                                 # noqa: E402
import time                                      # noqa: E402
from collections import deque, namedtuple        # noqa: E402

import numpy as np                               # noqa: E402
import torch                                     # noqa: E402

import training_quantization.continual_learning.img_preprocessing as img_preprocessing  # noqa: E402
import training_quantization.continual_learning.tof_preprocessing as tof_preprocessing  # noqa: E402
from training_quantization.continual_learning.compat import encoder_fingerprint, export_classifier_onnx  # noqa: E402
from training_quantization.continual_learning.runtime_utils import (  # noqa: E402
    load_gate_model, infer_gate_probability_with_latent, OnnxClassifier, onnx_sibling, onnx_is_fresh,
    MedianProbabilityFilter, EMAProbabilityFilter,
    wipe_collision_leaf_dirs, dump_collision_buffer_zero_index, save_dumped_latents, clear_dumped_latents,
    start_simulation_subprocess, close_simulation_log_handle, find_newest_checkpoint,
)

TQ_DIR = APP_ROOT / "training_quantization"
CL_DIR = TQ_DIR / "continual_learning"

MEDIAN_K = 11         # p(gate) smoothing, the node's defaults
EMA_ALPHA = 1.0       # 1.0 = no EMA
FRAMES_TO_SKIP = 20   # the last frames before a crash show the impact, not what led to it

# One entry of the ring buffer. The latent is the classifier's activation at the
# latent tap. The finetune only trains the layers after that tap, so it can start
# from these latents instead of running the encoder over the frames again. The
# fingerprint says which encoder weights produced the latent.
Frame = namedtuple("Frame", "cam tof latent encoder_fp")


class Classifier:
    """The gate classifier. Runs the .onnx next to the checkpoint with onnxruntime
    (faster than torch on the Duo S, same output). The torch model is kept for
    the encoder fingerprint and as fallback."""

    def __init__(self, ckpt_path, tap, backend="onnx"):
        self.tap = tap
        self.backend = backend
        self.generation = 0
        self.load(ckpt_path)

    def load(self, ckpt_path):
        ckpt_path = Path(ckpt_path)
        self.model = load_gate_model(str(ckpt_path), torch.device("cpu"))
        self.encoder_fp = encoder_fingerprint(self.model, self.tap)
        self.name = ckpt_path.name
        self.generation += 1
        self.onnx = None
        if self.backend == "onnx":
            try:
                self.onnx = self.load_onnx(ckpt_path)
            except Exception as e:
                print(f"[MODEL] onnxruntime not usable ({e}), using torch")
        print(f"[MODEL] {self.name}: generation {self.generation}, {self.backend_name}, "
              f"encoder {self.encoder_fp[:10]}, tap {self.tap}")

    def load_onnx(self, ckpt_path):
        # The finetune writes the .onnx together with the checkpoint. Export it
        # here if it is missing, older than the checkpoint or a different export.
        path = onnx_sibling(ckpt_path)
        if onnx_is_fresh(ckpt_path):
            try:
                return OnnxClassifier(path)
            except ImportError:
                raise
            except Exception as e:
                print(f"[MODEL] {e}, exporting again")
        t0 = time.monotonic()
        export_classifier_onnx(self.model, path, self.tap)
        print(f"[MODEL] exported {path.name} in {time.monotonic() - t0:.1f}s")
        return OnnxClassifier(path)

    @property
    def backend_name(self):
        return "onnxruntime" if self.onnx is not None else "torch"

    def infer(self, cam, tof):
        # returns (p_gate, latent), both from one forward pass
        if self.onnx is not None:
            return self.onnx.infer(cam, tof)
        return infer_gate_probability_with_latent(self.model, cam, tof, device=torch.device("cpu"), tap=self.tap)


def dump_buffer(buffer, dump_dir, clf):
    """Writes the buffer as a collision dump: camera_images/000000.npy ...,
    tof_distance_array/000000.npy ..., latents.npy and latents_meta.json.
    The finetune uses the latents only if they all come from the same encoder
    weights and that encoder is the one it loads; otherwise it recomputes them."""
    frames = list(buffer)
    if len(frames) > FRAMES_TO_SKIP:
        frames = frames[:-FRAMES_TO_SKIP]
    if not frames:
        print("[DUMP] buffer empty, nothing to save")
        return 0
    cam_dir, tof_dir = dump_dir / "camera_images", dump_dir / "tof_distance_array"
    wipe_collision_leaf_dirs(cam_dir, tof_dir)
    n = dump_collision_buffer_zero_index(buffer_data=[(f.cam, f.tof) for f in frames], cam_dir=cam_dir, tof_dir=tof_dir)
    clear_dumped_latents(dump_dir)
    fingerprints = {f.encoder_fp for f in frames}
    if len(fingerprints) == 1:
        save_dumped_latents(dump_dir, [f.latent for f in frames], tap=clf.tap, encoder_fp=fingerprints.pop(), model_name=clf.name)
        print(f"[DUMP] {n} frames with latents -> {dump_dir}")
    else:
        print(f"[DUMP] {n} frames, latents from {len(fingerprints)} different models so not saved -> {dump_dir}")
    return n


class Finetune:
    """Runs simulation.py, the continual-learning pipeline, in a subprocess.
    The node forks itself instead because that starts faster on the board;
    the training itself is the same."""

    def __init__(self, cfg_path, log_path, models_dir):
        self.cfg_path = Path(cfg_path)
        self.log_path = Path(log_path)
        self.models_dir = Path(models_dir)
        self.proc = None

    @property
    def running(self):
        return self.proc is not None

    def done(self):
        return self.proc is not None and self.proc.poll() is not None

    def start(self):
        self.proc, self.started_at = start_simulation_subprocess(
            app_root=APP_ROOT, cfg_path=self.cfg_path, log_path=self.log_path)
        print(f"[TRAIN] started, pid {self.proc.pid}, log {self.log_path}")

    def finish(self):
        """Call once done(). Returns the checkpoint the training wrote, or None."""
        rc = self.proc.returncode
        close_simulation_log_handle(self.proc)
        self.proc = None
        new_ckpt = find_newest_checkpoint(self.models_dir, after_wall_time=self.started_at)
        if new_ckpt is not None and new_ckpt.stat().st_mtime < self.started_at - 1:
            new_ckpt = None     # an old checkpoint, the training did not write one
        print(f"[TRAIN] finished after {time.time() - self.started_at:.0f}s, exit code {rc}, "
              f"{'new checkpoint ' + new_ckpt.name if new_ckpt else 'no new checkpoint'}")
        return new_ckpt

    def stop(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
            close_simulation_log_handle(self.proc)
            self.proc = None


def preprocess(gray_u8, tof_8x8_mm, cam_preproc="crop"):
    """Turns a camera frame and an 8x8 ToF matrix (mm, <= 0 = invalid) into the
    two normalized arrays the models take. Use this when reading a live camera.
    'crop' takes the 168x168 window the training data used, 'resize' scales."""
    cam = img_preprocessing.camera_norm_168(gray_u8, preproc=cam_preproc)
    tof = tof_preprocessing.tof_norm_21x21_from_8x8_mm(tof_8x8_mm)
    return cam, tof


def npy_frames(root):
    cams = sorted((root / "camera_images").glob("*.npy"))
    tofs = sorted((root / "tof_distance_array").glob("*.npy"))
    if not cams or len(cams) != len(tofs):
        sys.exit(f"{root}: need the same number of camera_images/*.npy and tof_distance_array/*.npy, "
                 f"found {len(cams)} and {len(tofs)}")
    for c, t in zip(cams, tofs):
        cam, tof = np.load(c).astype(np.float32), np.load(t).astype(np.float32)
        if cam.shape != (168, 168) or tof.shape != (21, 21):
            sys.exit(f"{c.name}: expected a 168x168 camera and a 21x21 ToF array, got {cam.shape} and {tof.shape}")
        yield cam, tof


def random_frames(n):
    # right shapes, meaningless content: enough to run the loop with just a checkpoint
    rng = np.random.default_rng(0)
    for _ in range(n):
        yield rng.standard_normal((168, 168), dtype=np.float32), rng.standard_normal((21, 21), dtype=np.float32)


def frames(args):
    while True:
        if args.frames:
            yield from npy_frames(Path(args.frames))
        else:
            yield from random_frames(args.n_random)
        if not args.loop:
            return


def start_key_reader():
    """Returns a set that gets the first character of every line typed in the terminal."""
    keys = set()
    if sys.stdin.isatty():
        def read():
            for line in sys.stdin:
                keys.add(line.strip()[:1].lower())
        threading.Thread(target=read, daemon=True).start()
    return keys


def load_navigator():
    # int8 tflite model; on the board it runs through onnxruntime (no tflite-runtime for riscv64)
    try:
        from training_quantization.inference_gate_navigator_in_loop import InferenceGateNavigatorInLoop
        nav = InferenceGateNavigatorInLoop()
        print(f"[NAV] gate navigator loaded, backend {nav.backend_name}")
        return nav
    except Exception as e:
        print(f"[NAV] no gate navigator ({e}), yaw stays 0")
        return None


def latent_tap_from(cfg_path):
    # the finetune trains from this tap, so the latents in the buffer must be taken there
    try:
        with open(cfg_path) as f:
            return json.load(f).get("latent_tap", "post_comb1")
    except (OSError, ValueError):
        print(f"[WARN] cannot read {cfg_path}, assuming latent_tap post_comb1")
        return "post_comb1"


def parse_args():
    p = argparse.ArgumentParser(description="Minimal Duo S node: inference, latent ring buffer, crash dump, finetune, hot-swap")
    p.add_argument("--ckpt", required=True, help="GateClassifier checkpoint (.pt)")
    p.add_argument("--frames", help="folder with camera_images/*.npy and tof_distance_array/*.npy")
    p.add_argument("--n_random", type=int, default=300, help="random frames to run when --frames is not given")
    p.add_argument("--loop", action="store_true", help="replay the frames until q + Enter")
    p.add_argument("--fps", type=float, default=0.0, help="frame rate, 0 = as fast as possible")
    p.add_argument("--backend", choices=["onnx", "torch"], default="onnx", help="classifier runtime")
    p.add_argument("--no_navigator", action="store_true")
    p.add_argument("--navigator_every", type=int, default=2, help="run the navigator on every n-th frame")
    p.add_argument("--thr", type=float, default=0.5, help="p(gate) threshold")
    p.add_argument("--buffer_n", type=int, default=90, help="ring buffer length in frames")
    p.add_argument("--dump_at", type=int, nargs="*", default=[], help="frame numbers at which to simulate a crash")
    p.add_argument("--dump_dir", default=str(TQ_DIR / "collision_dataset" / "train" / "collision_0" / "no_gate"))
    p.add_argument("--finetune_on_dump", action="store_true", help="run the finetune after every dump")
    p.add_argument("--sim_cfg", default=str(CL_DIR / "config.json"))
    p.add_argument("--train_log", default=str(APP_ROOT / "simulation_last.log"))
    p.add_argument("--models_dir", default=str(TQ_DIR / "throwaway_models"), help="where the finetune writes checkpoints")
    p.add_argument("--print_every", type=int, default=10)
    return p.parse_args()


def main():
    args = parse_args()

    clf = Classifier(args.ckpt, latent_tap_from(args.sim_cfg), args.backend)
    navigator = None if args.no_navigator else load_navigator()
    median = MedianProbabilityFilter(window_size=MEDIAN_K)
    ema = EMAProbabilityFilter(alpha=EMA_ALPHA)
    buffer = deque(maxlen=max(1, args.buffer_n))
    finetune = Finetune(args.sim_cfg, args.train_log, args.models_dir) if args.finetune_on_dump else None
    dump_dir = Path(args.dump_dir)
    dump_at = set(args.dump_at)
    keys = start_key_reader()

    def crash():
        dump_buffer(buffer, dump_dir, clf)
        if finetune is not None:
            finetune.start()

    pending_dump = False
    yaw = 0.0
    n_frames = 0
    t_start = time.perf_counter()
    times = deque(maxlen=200)
    print(f"[LOOP] {args.frames or f'{args.n_random} random frames'}{' (looping)' if args.loop else ''}, "
          f"buffer {buffer.maxlen} frames, crash at {sorted(dump_at) or 'd + Enter'}")
    try:
        for i, (cam, tof) in enumerate(frames(args)):
            t0 = time.perf_counter()
            n_frames = i + 1

            p_raw, latent = clf.infer(cam, tof)
            buffer.append(Frame(cam, tof, latent, clf.encoder_fp))
            p = ema.update(median.update(p_raw))
            gate = p >= args.thr

            if navigator is not None and i % args.navigator_every == 0:
                navigator.set_sample_from_normalized(cam, tof)
                yaw = float(navigator.predict_navigation()[0])
            yaw_used = yaw if gate else 0.0     # the controller only uses the yaw while it sees a gate
            times.append(time.perf_counter() - t0)

            if i % args.print_every == 0:
                training = "running" if finetune is not None and finetune.running else "idle"
                print(f"frame {i:6d}  p={p:.3f} {'GATE   ' if gate else 'no gate'}  yaw={yaw_used:+.3f}  "
                      f"{clf.backend_name} {1000 * np.mean(times):5.1f} ms  buffer {len(buffer):3d}/{buffer.maxlen}  "
                      f"training {training}")

            # crash? A dump during a finetune waits until the finetune is done, like in the node.
            if i in dump_at or "d" in keys or pending_dump:
                keys.discard("d")
                if finetune is not None and finetune.running:
                    if not pending_dump:
                        print("[DUMP] finetune running, dump postponed")
                    pending_dump = True
                else:
                    pending_dump = False
                    crash()

            # finetune done? Load its checkpoint and start over with an empty buffer.
            if finetune is not None and finetune.done():
                new_ckpt = finetune.finish()
                if new_ckpt is not None:
                    clf.load(new_ckpt)
                if pending_dump:
                    pending_dump = False
                    crash()
                buffer.clear()
                median.reset()
                ema.reset()

            if "q" in keys:
                break
            if args.fps > 0:
                time.sleep(max(0.0, n_frames / args.fps - (time.perf_counter() - t_start)))

        if finetune is not None and finetune.running:
            print("[TRAIN] no more frames, waiting for the finetune (Ctrl-C aborts it)")
            finetune.proc.wait()
            new_ckpt = finetune.finish()
            if new_ckpt is not None:
                clf.load(new_ckpt)
            if pending_dump:
                dump_buffer(buffer, dump_dir, clf)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        if finetune is not None:
            finetune.stop()

    elapsed = time.perf_counter() - t_start
    print(f"[LOOP] {n_frames} frames in {elapsed:.1f}s ({n_frames / max(elapsed, 1e-6):.1f} fps), "
          f"{clf.backend_name} {1000 * np.mean(times) if times else 0:.1f} ms per frame, model {clf.name}")


if __name__ == "__main__":
    main()
