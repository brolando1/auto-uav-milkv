#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Shared helpers moved out of the old opencv_viewer.py so they run headless on
# the Duo S (no cv2 windows / matplotlib in here).

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional, Tuple

import numpy as np

import training_quantization.continual_learning.compat as compat

try:
    import torch
except Exception as e:
    raise ImportError("This module requires PyTorch (torch). Install it in your environment.") from e

# =============================================================================
# Small utils
# =============================================================================

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_rmtree(path: Path) -> None:
    if not path.exists():
        return
    for _ in range(3):
        try:
            shutil.rmtree(path)
            return
        except Exception:
            time.sleep(0.1)
    shutil.rmtree(path)


def wipe_collision_leaf_dirs(cam_dir: Path, tof_dir: Path) -> None:
    safe_rmtree(cam_dir)
    safe_rmtree(tof_dir)
    ensure_dir(cam_dir)
    ensure_dir(tof_dir)


def wipe_leaf_dirs(cam_dir: Path, tof_dir: Path) -> None:
    safe_rmtree(cam_dir)
    safe_rmtree(tof_dir)
    ensure_dir(cam_dir)
    ensure_dir(tof_dir)


def tail_lines(path: Path, *, max_bytes: int = 16384, max_lines: int = 10) -> List[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(0, end - int(max_bytes)))
            data = f.read()
        txt = data.decode("utf-8", errors="ignore")
        lines = [ln.rstrip() for ln in txt.splitlines() if ln.strip()]
        return lines[-int(max_lines):]
    except Exception:
        return []


def make_session_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def save_pair_at_index(
    *,
    cam_arr: np.ndarray,
    tof_arr: np.ndarray,
    cam_dir: Path,
    tof_dir: Path,
    idx: int,
) -> None:
    np.save(str(cam_dir / f"{idx:06d}.npy"), cam_arr.astype(np.float32, copy=False))
    np.save(str(tof_dir / f"{idx:06d}.npy"), tof_arr.astype(np.float32, copy=False))

# =============================================================================
# Import GateClassifier robustly
# =============================================================================
def _ensure_sys_path_for_models() -> None:
    project_root = Path(__file__).resolve().parent

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def import_gate_classifier_cls():
    _ensure_sys_path_for_models()
    try:
        from training_quantization.model.gate_classifier_PyTorch_model import GateClassifier  # type: ignore
        return GateClassifier
    except Exception as e:
        raise ImportError(
            "Unable to import GateClassifier. Check if the path "
            "training_quantization.model.gate_classifier_PyTorch_model.py exists."
        ) from e


# =============================================================================
# Model loading / device
# =============================================================================
def load_gate_model(ckpt_path: str, device: torch.device):
    GateClassifierCls = import_gate_classifier_cls()
    ckpt_path = str(ckpt_path)

    # Try compat helper if present
    if hasattr(compat, "load_model"):
        try:
            return compat.load_model(ckpt_path, device, GateClassifierCls)
        except TypeError:
            try:
                return compat.load_model(ckpt_path, device=device, GateClassifierCls=GateClassifierCls)  # type: ignore
            except Exception:
                pass
        except Exception:
            pass

    ckpt = torch.load(ckpt_path, map_location=device)

    if isinstance(ckpt, dict) and "gate_classifier_state_dict" in ckpt:
        ncs = int(ckpt.get("num_channels_start", 4) or 4)
        dp = float(ckpt.get("dropout_p", 0.0) or 0.0)
        model = GateClassifierCls(num_channels_start=ncs, dropout_p=dp)
        state_dict = ckpt["gate_classifier_state_dict"]
    else:
        model = GateClassifierCls()
        state_dict = ckpt

    model.load_state_dict(state_dict)
    model.to(device)
    model.eval()
    return model


def robust_set_device(deterministic: bool) -> torch.device:
    if hasattr(compat, "set_device"):
        try:
            dev = compat.set_device(deterministic=deterministic)
            return torch.device(dev) if isinstance(dev, str) else dev
        except TypeError:
            try:
                dev = compat.set_device(deterministic)
                return torch.device(dev) if isinstance(dev, str) else dev
            except Exception:
                pass
        except Exception:
            pass
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

# =============================================================================
# Prediction smoothing
# =============================================================================
class MedianProbabilityFilter:
    def __init__(self, window_size: int = 1) -> None:
        self.window_size = int(max(1, window_size))
        self.values: Deque[float] = deque(maxlen=self.window_size)

    def reset(self) -> None:
        self.values.clear()

    def update(self, value: float) -> float:
        v = max(0.0, min(1.0, float(value)))
        self.values.append(v)
        return float(np.median(np.array(self.values, dtype=np.float32)))


class EMAProbabilityFilter:
    def __init__(self, alpha: float = 0.5) -> None:
        self.alpha = float(alpha)
        self.state: Optional[float] = None

    def reset(self) -> None:
        self.state = None

    def update(self, value: float) -> float:
        v = max(0.0, min(1.0, float(value)))
        if self.state is None:
            self.state = v
        else:
            self.state = self.alpha * v + (1.0 - self.alpha) * self.state
        return float(self.state)


# =============================================================================
# Inference
# =============================================================================
def infer_gate_probability_with_latent(model, cam_168_norm: np.ndarray, tof_21_norm: np.ndarray,
                                       device: torch.device, tap: str):
    """Same result as infer_gate_probability, plus the latent at `tap` as a
    float32 numpy array (no batch dim). The node keeps it in the ring buffer so
    a finetune does not have to run the encoder over the dumped frames again."""
    cam_t = torch.from_numpy(cam_168_norm).unsqueeze(0).unsqueeze(0).to(device)  # [1,1,168,168]
    tof_t = torch.from_numpy(tof_21_norm).unsqueeze(0).unsqueeze(0).to(device)   # [1,1,21,21]
    model.eval()
    out, z = compat.infer_with_latent(model, cam_t, tof_t, tap)
    v = float(out.float().view(-1)[0].item())
    return max(0.0, min(1.0, v)), z[0].detach().cpu().numpy().astype(np.float32, copy=False)


def onnx_sibling(ckpt_path) -> Path:
    return Path(ckpt_path).with_suffix(".onnx")


def onnx_is_fresh(ckpt_path) -> bool:
    """True if the .onnx next to the checkpoint exists and is not older than it."""
    ck, ox = Path(ckpt_path), onnx_sibling(ckpt_path)
    try:
        return ox.exists() and ox.stat().st_mtime >= ck.stat().st_mtime - 1.0
    except OSError:
        return False


class OnnxClassifier:
    """Classifier exported by compat.export_classifier_onnx, run with onnxruntime.
    infer() returns (p_gate, latent) exactly like infer_gate_probability_with_latent."""

    def __init__(self, onnx_path, num_threads: int = 1):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(num_threads)
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.path = str(onnx_path)
        self.session = ort.InferenceSession(self.path, so, providers=["CPUExecutionProvider"])
        names = [i.name for i in self.session.get_inputs()]
        if names != ["image", "tof"] or [o.name for o in self.session.get_outputs()] != ["p_gate", "latent"]:
            raise RuntimeError(f"{self.path}: unexpected ONNX signature {names} -> {[o.name for o in self.session.get_outputs()]}")

    def infer(self, cam_168_norm: np.ndarray, tof_21_norm: np.ndarray):
        img = np.ascontiguousarray(cam_168_norm, dtype=np.float32).reshape(1, 1, 168, 168)
        tof = np.ascontiguousarray(tof_21_norm, dtype=np.float32).reshape(1, 1, 21, 21)
        p, z = self.session.run(["p_gate", "latent"], {"image": img, "tof": tof})
        v = float(np.asarray(p, dtype=np.float32).reshape(-1)[0])
        return max(0.0, min(1.0, v)), np.asarray(z[0], dtype=np.float32)


def infer_gate_probability(model, cam_168_norm: np.ndarray, tof_21_norm: np.ndarray, device: torch.device) -> float:
    cam_t = torch.from_numpy(cam_168_norm).unsqueeze(0).unsqueeze(0).to(device)  # [1,1,168,168]
    tof_t = torch.from_numpy(tof_21_norm).unsqueeze(0).unsqueeze(0).to(device)   # [1,1,21,21]
    model.eval()
    with torch.no_grad():
        out = model(cam_t, tof_t)
        v = float(out.float().view(-1)[0].item())
    return max(0.0, min(1.0, v))


# =============================================================================
# Collision dataset saving (buffer -> dump .npy pairs)
# =============================================================================
def dump_collision_buffer_zero_index(
    *,
    buffer_data: Deque[Tuple[np.ndarray, np.ndarray]],
    cam_dir: Path,
    tof_dir: Path,
) -> int:
    """
    Dumps (oldest->newest) the current buffer to:
      cam_dir/{idx:06d}.npy   (float32 168x168 normalized)
      tof_dir/{idx:06d}.npy   (float32 21x21 standardized)
    Returns number of saved samples.
    """
    ensure_dir(cam_dir)
    ensure_dir(tof_dir)

    idx = 0
    for cam_arr, tof_arr in list(buffer_data):
        np.save(str(cam_dir / f"{idx:06d}.npy"), cam_arr.astype(np.float32, copy=False))
        np.save(str(tof_dir / f"{idx:06d}.npy"), tof_arr.astype(np.float32, copy=False))
        idx += 1
    return idx


LATENTS_FILE = "latents.npy"
LATENTS_META_FILE = "latents_meta.json"


def clear_dumped_latents(leaf_dir: Path) -> None:
    for name in (LATENTS_FILE, LATENTS_META_FILE):
        try:
            (Path(leaf_dir) / name).unlink()
        except FileNotFoundError:
            pass


def save_dumped_latents(leaf_dir: Path, latents, *, tap: str, encoder_fp: str, model_name: str) -> int:
    """Writes leaf_dir/latents.npy [N, ...] + latents_meta.json next to the
    camera_images/ and tof_distance_array/ folders of a collision dump.
    Index i of latents.npy belongs to {i:06d}.npy. Returns N."""
    import json
    leaf_dir = Path(leaf_dir)
    ensure_dir(leaf_dir)
    Z = np.stack([np.asarray(z, dtype=np.float32) for z in latents], axis=0)
    np.save(str(leaf_dir / LATENTS_FILE), Z)
    meta = {"tap": tap, "encoder_fp": encoder_fp, "n": int(Z.shape[0]),
            "shape": list(Z.shape[1:]), "model": model_name, "created": time.time()}
    with (leaf_dir / LATENTS_META_FILE).open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return int(Z.shape[0])


def load_dumped_latents(leaf_dir: Path, *, tap: str, encoder_fp: str, expected_n: int):
    """Returns the latents as np.ndarray [N, ...] if a dump with matching tap,
    encoder fingerprint and sample count exists, else (None, reason)."""
    import json
    leaf_dir = Path(leaf_dir)
    zf, mf = leaf_dir / LATENTS_FILE, leaf_dir / LATENTS_META_FILE
    if not zf.exists() or not mf.exists():
        return None, "no latents dumped by the node"
    try:
        meta = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"unreadable latents_meta.json ({e})"
    if meta.get("tap") != tap:
        return None, f"tap mismatch ({meta.get('tap')} != {tap})"
    if meta.get("encoder_fp") != encoder_fp:
        return None, "encoder fingerprint mismatch (different pre-tap weights)"
    Z = np.load(str(zf), allow_pickle=False)
    if int(meta.get("n", -1)) != int(Z.shape[0]) or int(Z.shape[0]) != int(expected_n):
        return None, f"sample count mismatch (latents={Z.shape[0]}, meta={meta.get('n')}, files={expected_n})"
    return Z, "ok"


# =============================================================================
# Fine-tuning helpers (subprocess, no threads)
# =============================================================================
def start_simulation_subprocess(
    *,
    app_root: Path,
    cfg_path: Path,
    log_path: Path,
) -> Tuple[subprocess.Popen, float]:
    """
    Launch:
      python -m training_quantization.continual_learning.simulation --cfg <cfg>
    stdout+stderr -> log_path (truncate).
    app_root is the folder that contains training_quantization/ (used as cwd and
    put on PYTHONPATH). Returns (Popen, train_start_wall_time).
    """
    ensure_dir(log_path.parent)
    # Truncate log each run
    log_f = log_path.open("w", encoding="utf-8", buffering=1)

    env = os.environ.copy()
    # Ensure training_quantization is importable when running -m
    prev_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(app_root) + (os.pathsep + prev_pp if prev_pp else "")

    cmd = [
        sys.executable,
        "-u",   # unbuffered: the log is readable while the run is in progress
        "-m",
        "training_quantization.continual_learning.simulation",
        "--cfg",
        str(cfg_path),
    ]

    def _expendable():
        # On the Duo S (411 MB RAM) the kernel OOM killer must take the training
        # child, never the node that runs the flight controller. Raising our own
        # oom_score_adj needs no privileges.
        try:
            with open("/proc/self/oom_score_adj", "w") as f:
                f.write("1000")
        except Exception:
            pass

    train_start_wall = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(app_root),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        text=True,  # log_f is text anyway
        preexec_fn=_expendable if os.name == "posix" else None,
    )

    # Attach handle so it isn't GC'd early
    proc._opencv_viewer_log_handle = log_f  # type: ignore[attr-defined]
    return proc, train_start_wall


class ForkedTraining:
    """Popen-like handle for a training run forked off the node process."""

    def __init__(self, pid: int, log_handle):
        self.pid = int(pid)
        self.returncode = None
        self._opencv_viewer_log_handle = log_handle   # same attribute the subprocess path uses

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.returncode = -1
            return self.returncode
        if pid == 0:
            return None
        self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout=None):
        t0 = time.monotonic()
        while self.poll() is None:
            if timeout is not None and time.monotonic() - t0 > timeout:
                raise subprocess.TimeoutExpired(cmd=f"forked-training[{self.pid}]", timeout=timeout)
            time.sleep(0.05)
        return self.returncode

    def _signal(self, sig):
        if self.returncode is not None:
            return
        try:
            os.kill(self.pid, sig)
        except ProcessLookupError:
            pass

    def terminate(self):
        self._signal(signal.SIGTERM)

    def kill(self):
        self._signal(signal.SIGKILL)


def preload_training_modules() -> None:
    """Import simulation.py and everything it needs in the node process, so a
    forked training child starts with torch/cv2/numpy and the pipeline already
    loaded (on the Duo S a fresh interpreter needs ~20-60 s for that)."""
    import importlib
    importlib.import_module("training_quantization.continual_learning.simulation")
    # Warm torch's lazy machinery: the first torch.optim.Adam() pulls in
    # torch._dynamo / inductor / sympy (~20 s and ~60 MB on the Duo S). Done
    # here once, the forked child inherits it and its setup() drops to ~1 s.
    try:
        import torch
        p = torch.nn.Parameter(torch.zeros(2))
        opt = torch.optim.Adam([p], lr=1e-3)
        p.grad = torch.ones(2)
        opt.step()
        del opt, p
    except Exception as e:  # pragma: no cover - warm-up only
        print(f"[WARN] torch warm-up for the fork launcher failed: {e}")
    # the child exports every new checkpoint to ONNX for the node: warm that too
    try:
        compat.warm_onnx_exporter(import_gate_classifier_cls())
    except Exception as e:  # pragma: no cover - warm-up only
        print(f"[WARN] ONNX exporter warm-up failed (finetunes will still work, node falls back to torch): {e}")


def start_simulation_forked(
    *,
    app_root: Path,
    cfg_path: Path,
    log_path: Path,
) -> Tuple[ForkedTraining, float]:
    """Run simulation.main() in a child forked from the node instead of a new
    interpreter: torch, the model and the pipeline modules are inherited
    (copy-on-write), which removes the interpreter start-up cost and most of
    the duplicated memory.

    MUST be called from a thread that is not inside a torch/cv2 call, i.e. the
    inference thread at the top of its loop: the child only gets the calling
    thread, and a mutex some other thread held inside torch at fork time would
    stay locked forever in the child. Everything else the child does not use.
    """
    import importlib
    sim_mod = importlib.import_module("training_quantization.continual_learning.simulation")

    ensure_dir(log_path.parent)
    log_f = log_path.open("w", encoding="utf-8", buffering=1)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    train_start_wall = time.time()
    pid = os.fork()
    if pid != 0:
        # ---- parent ----
        return ForkedTraining(pid, log_f), train_start_wall

    # ---- child: never return into the node's code ----
    rc = 1
    try:
        os.setsid()
        log_fd = log_f.fileno()
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        # drop the inherited sockets (AI-deck, PC link) and any other fds
        try:
            import resource
            max_fd = min(resource.getrlimit(resource.RLIMIT_NOFILE)[0], 4096)
        except Exception:
            max_fd = 1024
        for fd in range(3, max_fd):
            if fd != log_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        # fresh stream objects: the parent's may have been locked by another thread
        sys.stdout = os.fdopen(1, "w", buffering=1, encoding="utf-8", closefd=False)
        sys.stderr = os.fdopen(2, "w", buffering=1, encoding="utf-8", closefd=False)
        # the kernel must kill this child before the node if memory runs out
        try:
            with open("/proc/self/oom_score_adj", "w") as f:
                f.write("1000")
        except Exception:
            pass
        try:
            import cv2
            cv2.setNumThreads(0)
        except Exception:
            pass
        try:
            import torch
            torch.set_num_threads(1)
        except Exception:
            pass
        os.chdir(str(app_root))
        sys.argv = ["simulation", "--cfg", str(cfg_path)]
        print(f"[FORK] training child pid={os.getpid()} forked from the node (torch preloaded)")
        sim_mod.main()
        rc = 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        import traceback
        traceback.print_exc()
        rc = 1
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(rc)


def close_simulation_log_handle(proc: subprocess.Popen) -> None:
    h = getattr(proc, "_opencv_viewer_log_handle", None)
    if h is not None:
        try:
            h.flush()
        except Exception:
            pass
        try:
            h.close()
        except Exception:
            pass
        try:
            delattr(proc, "_opencv_viewer_log_handle")
        except Exception:
            pass


def find_newest_checkpoint(throwaway_dir: Path, *, after_wall_time: float, exts: Tuple[str, ...] = (".pt", ".pth")) -> Optional[Path]:
    """
    Pick newest checkpoint in throwaway_dir (recursive) whose mtime >= after_wall_time.
    If none matches, return the newest overall (still useful), or None if empty.
    """
    if not throwaway_dir.exists():
        return None

    candidates: List[Path] = []
    for ext in exts:
        candidates.extend(throwaway_dir.rglob(f"*{ext}"))

    if not candidates:
        return None

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except Exception:
            return 0.0

    newer = [p for p in candidates if mtime(p) >= float(after_wall_time)]
    pick_from = newer if newer else candidates
    pick_from.sort(key=mtime, reverse=True)
    return pick_from[0]
