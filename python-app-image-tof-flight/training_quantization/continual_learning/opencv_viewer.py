#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opencv-viewer.py
================
AI-deck WiFi image streamer + ToF (VL53L8A1) serial stream + GateClassifier overlay
+ ring-buffer dataset dump + (optional) fine-tuning trigger on key press.

Data sources
-----------
- Camera frames arrive via Bitcraze AI-deck socket protocol.
- ToF frames arrive via UART as CSV lines like:
    TOF8X8,SEQ,V0,V1,...,V63
  where V* are distances in **mm**.

Synchronization rule 
-----------------------------------
- When a CAMERA frame arrives, we pair it with the **most recent ToF frame received so far**
  (even if that ToF frame is older than the camera frame).

Preprocessing 
---------------------------------
- Camera:
    1) crop/resize to 168x168 uint8
    2) normalize: ((u8/255) - MEAN_IMAGE) / STD_IMAGE
- ToF:
    1) mm -> meters
    2) 8x8 -> upsample to 21x21 (NEAREST)
    3) standardize: (m - MEAN_TOF) / STD_TOF

Ring-buffer + dataset dump
--------------------------
- Keeps last N (camera_norm_168, tof_norm_21) pairs in RAM (paired on CAMERA arrival).
- On key press (--buffer_key, default 'd'):
    1) DELETE previous .npy files in collision_dataset target dirs
    2) save current buffer as:
        <collision_root>/<collision_name>/<collision_label>/camera_images/000000.npy ...
        <collision_root>/<collision_name>/<collision_label>/tof_distance_array/000000.npy ...
       Arrays are saved exactly as model inputs (float32).

Continuous recording to disk
----------------------------
- Press --record_start_key (default 'a') to START recording continuously.
- Press --record_stop_key  (default 'b') to STOP recording.
- During recording, every incoming synchronized pair is saved immediately to disk as:
    <record_root>/<record_name>/<session_timestamp>/camera_images/000000.npy ...
    <record_root>/<record_name>/<session_timestamp>/tof_distance_array/000000.npy ...
- Arrays are saved exactly as model inputs (float32).
- This writes directly to disk to avoid growing RAM usage.

Fine-tuning trigger (no threads; no GUI freeze)
----------------------------------------------
- If --finetune_on_dump is enabled:
    - After saving the buffer, we launch:
        python -m training_quantization.continual_learning.simulation --cfg <cfg>
      as a subprocess (stdout+stderr -> log file).
    - While training runs:
        - Streaming + inference continues
        - GUI shows TRAINING status + tail of simulation log
    - When training finishes:
        - we pick the newest .pt/.pth inside training_quantization/throwaway_models
          produced after training started
        - load it as new model (predictions switch immediately)
        - clear the RAM buffer (so you start collecting new samples)

Extra debug visualization
-------------------------
- If --show_model_inputs is enabled:
    - shows an additional window with 4 panels:
        1) camera decoded/raw-for-display
        2) camera model input visualization
        3) ToF raw 8x8 (mm)
        4) ToF model input visualization (21x21 standardized)

execution:
python3 opencv-viewer.py --ckpt ../throwaway_models/original_model2.pt --save_collision --buffer_n 90 --collision_name collisione_0 --collision_label no_gate --plot --finetune_on_dump --median_k 7 --show_model_inputs
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional, Tuple
import threading
import matplotlib.pyplot as plt


from logger.camera_tof_pairing import paired_buffer, buffer_lock
import training_quantization.continual_learning.img_preprocessing as img_preprocessing
import training_quantization.continual_learning.tof_preprocessing as tof_preprocessing

import cv2
import numpy as np

# Local import (script is inside continual_learning/)
import training_quantization.continual_learning.compat as compat

try:
    import torch
except Exception as e:
    raise ImportError("This script requires PyTorch (torch). Install it in your environment.") from e

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
def infer_gate_probability(model, cam_168_norm: np.ndarray, tof_21_norm: np.ndarray, device: torch.device) -> float:
    cam_t = torch.from_numpy(cam_168_norm).unsqueeze(0).unsqueeze(0).to(device)  # [1,1,168,168]
    tof_t = torch.from_numpy(tof_21_norm).unsqueeze(0).unsqueeze(0).to(device)   # [1,1,21,21]
    model.eval()
    with torch.no_grad():
        out = model(cam_t, tof_t)
        v = float(out.float().view(-1)[0].item())
    return max(0.0, min(1.0, v))


# =============================================================================
# UI helpers
# =============================================================================
def overlay_text(img_bgr: np.ndarray, lines: List[str]) -> np.ndarray:
    out = img_bgr.copy()
    y = 26
    for line in lines:
        cv2.putText(out, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
        y += 28
    return out


def render_tof_heatmap_panel(
    tof_2d: np.ndarray,
    *,
    panel_size: int = 320,
    vmin: float,
    vmax: float,
    draw_grid: bool = True,
    title: str = "ToF",
    bottom_text: Optional[str] = None,
) -> np.ndarray:
    arr = tof_2d.astype(np.float32, copy=False)
    arr = np.clip(arr, vmin, vmax)

    u = (arr - float(vmin)) / max(1e-9, float(vmax - vmin))
    u8 = np.clip(u * 255.0, 0.0, 255.0).astype(np.uint8)

    color = cv2.applyColorMap(u8, cv2.COLORMAP_TURBO)
    panel = cv2.resize(color, (panel_size, panel_size), interpolation=cv2.INTER_NEAREST)

    if draw_grid and tof_2d.shape[0] <= 32 and tof_2d.shape[1] <= 32:
        step_y = panel_size // max(1, int(tof_2d.shape[0]))
        step_x = panel_size // max(1, int(tof_2d.shape[1]))
        for i in range(1, int(tof_2d.shape[1])):
            x = i * step_x
            cv2.line(panel, (x, 0), (x, panel_size - 1), (0, 0, 0), 1)
        for i in range(1, int(tof_2d.shape[0])):
            y = i * step_y
            cv2.line(panel, (0, y), (panel_size - 1, y), (0, 0, 0), 1)

    cv2.rectangle(panel, (0, 0), (panel_size - 1, 28), (0, 0, 0), -1)
    cv2.putText(panel, title, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    if bottom_text:
        cv2.rectangle(panel, (0, panel_size - 28), (panel_size - 1, panel_size - 1), (0, 0, 0), -1)
        cv2.putText(panel, bottom_text, (10, panel_size - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    return panel

def render_tof_heatmap_panel_mm(
    tof_8x8_mm: np.ndarray,
    *,
    panel_size: int = 320,
    vmin_mm: float = 200.0,
    vmax_mm: float = 4000.0,
    draw_grid: bool = True,
    title: str = "ToF 8x8 (mm)",
    bottom_text: Optional[str] = None,
) -> np.ndarray:
    return render_tof_heatmap_panel(
        tof_8x8_mm,
        panel_size=panel_size,
        vmin=vmin_mm,
        vmax=vmax_mm,
        draw_grid=draw_grid,
        title=title,
        bottom_text=bottom_text,
    )

def resize_keep_aspect(img: np.ndarray, target_h: int) -> np.ndarray:
    h, w = img.shape[:2]
    if h == target_h:
        return img
    new_w = int(round(w * (target_h / float(h))))
    return cv2.resize(img, (new_w, target_h), interpolation=cv2.INTER_AREA)


def gray_to_bgr(gray_2d: np.ndarray) -> np.ndarray:
    g = gray_2d.astype(np.uint8, copy=False)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def render_camera_input_panel(
    cam_uint8_168: np.ndarray,
    *,
    panel_size: int = 320,
    title: str = "Camera model input (168x168)",
    bottom_text: Optional[str] = None,
) -> np.ndarray:
    img = gray_to_bgr(cam_uint8_168)
    panel = cv2.resize(img, (panel_size, panel_size), interpolation=cv2.INTER_AREA)
    cv2.rectangle(panel, (0, 0), (panel_size - 1, 28), (0, 0, 0), -1)
    cv2.putText(panel, title, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)

    if bottom_text:
        cv2.rectangle(panel, (0, panel_size - 28), (panel_size - 1, panel_size - 1), (0, 0, 0), -1)
        cv2.putText(panel, bottom_text, (10, panel_size - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return panel


def make_debug_grid_2x2(
    p00: np.ndarray,
    p01: np.ndarray,
    p10: np.ndarray,
    p11: np.ndarray,
) -> np.ndarray:
    target_h = max(p00.shape[0], p01.shape[0], p10.shape[0], p11.shape[0])
    a = resize_keep_aspect(p00, target_h)
    b = resize_keep_aspect(p01, target_h)
    c = resize_keep_aspect(p10, target_h)
    d = resize_keep_aspect(p11, target_h)

    top_h = max(a.shape[0], b.shape[0])
    bot_h = max(c.shape[0], d.shape[0])

    a = resize_keep_aspect(a, top_h)
    b = resize_keep_aspect(b, top_h)
    c = resize_keep_aspect(c, bot_h)
    d = resize_keep_aspect(d, bot_h)

    top = np.hstack([a, b])
    bottom = np.hstack([c, d])

    if top.shape[1] != bottom.shape[1]:
        target_w = max(top.shape[1], bottom.shape[1])
        top = cv2.resize(top, (target_w, top.shape[0]), interpolation=cv2.INTER_AREA)
        bottom = cv2.resize(bottom, (target_w, bottom.shape[0]), interpolation=cv2.INTER_AREA)

    return np.vstack([top, bottom])


def hstack_resize_to_height(left_bgr: np.ndarray, right_bgr: np.ndarray, height: int) -> np.ndarray:
    def resize_keep_aspect(img: np.ndarray, target_h: int) -> np.ndarray:
        h, w = img.shape[:2]
        if h == target_h:
            return img
        new_w = int(round(w * (target_h / float(h))))
        return cv2.resize(img, (new_w, target_h), interpolation=cv2.INTER_CUBIC)

    L = resize_keep_aspect(left_bgr, height)
    R = resize_keep_aspect(right_bgr, height)
    return np.hstack([L, R])


# =============================================================================
# Real-time plot (OpenCV-based)
# =============================================================================
class RealTimeProbabilityPlot:
    def __init__(self, *, history_s: float = 30.0, width: int = 640, height: int = 240, title: str = "p(gate) vs time") -> None:
        self.history_s = float(max(0.5, history_s))
        self.width = int(max(200, width))
        self.height = int(max(150, height))
        self.title = str(title)

        self._t: Deque[float] = deque()
        self._p: Deque[float] = deque()

        self.m_left = 55
        self.m_right = 15
        self.m_top = 30
        self.m_bottom = 35

    def add(self, t_sec: float, p: float) -> None:
        t = float(t_sec)
        pv = max(0.0, min(1.0, float(p)))
        self._t.append(t)
        self._p.append(pv)

        t_min = t - self.history_s
        while self._t and self._t[0] < t_min:
            self._t.popleft()
            self._p.popleft()

    def _map_x(self, t: float, t0: float, t1: float) -> int:
        x0, x1 = self.m_left, self.width - self.m_right
        if t1 <= t0 + 1e-9:
            return int(x1)
        u = (t - t0) / (t1 - t0)
        u = max(0.0, min(1.0, u))
        return int(x0 + u * (x1 - x0))

    def _map_y(self, p: float) -> int:
        y0, y1 = self.height - self.m_bottom, self.m_top
        pv = max(0.0, min(1.0, float(p)))
        return int(y0 - pv * (y0 - y1))

    def render(self) -> np.ndarray:
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:] = (18, 18, 18)

        x0, x1 = self.m_left, self.width - self.m_right
        y0, y1 = self.height - self.m_bottom, self.m_top

        cv2.rectangle(img, (x0, y1), (x1, y0), (80, 80, 80), 1)
        cv2.putText(img, self.title, (x0, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1, cv2.LINE_AA)

        for yt, lab in [(0.0, "0.0"), (0.5, "0.5"), (1.0, "1.0")]:
            yy = self._map_y(yt)
            cv2.line(img, (x0, yy), (x1, yy), (45, 45, 45), 1)
            cv2.putText(img, lab, (8, yy + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

        if not self._t:
            cv2.putText(img, "waiting for data...", (x0 + 10, (y0 + y1) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
            return img

        t_last = float(self._t[-1])
        t0w, t1w = t_last - self.history_s, t_last

        tick_count = 4
        for i in range(tick_count + 1):
            rel = -self.history_s + (self.history_s * i / tick_count)
            tt = t_last + rel
            xx = self._map_x(tt, t0w, t1w)
            cv2.line(img, (xx, y0), (xx, y0 + 5), (200, 200, 200), 1)
            cv2.putText(img, f"{int(rel):d}s", (xx - 16, y0 + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

        pts: List[Tuple[int, int]] = []
        for t, p in zip(self._t, self._p):
            pts.append((self._map_x(float(t), t0w, t1w), self._map_y(float(p))))

        if len(pts) >= 2:
            cv2.polylines(img, [np.array(pts, dtype=np.int32)], isClosed=False, color=(0, 255, 0), thickness=2)
        else:
            cv2.circle(img, pts[0], 2, (0, 255, 0), -1)

        p_last = float(self._p[-1])
        cv2.putText(img, f"p={p_last:.3f}", (x1 - 90, y1 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA)
        return img


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


# =============================================================================
# Fine-tuning helpers (subprocess, no threads)
# =============================================================================
def start_simulation_subprocess(
    *,
    repo_root: Path,
    cfg_path: Path,
    log_path: Path,
) -> Tuple[subprocess.Popen, float]:
    """
    Launch:
      python -m python-app-image-tof-logger.training_quantization.continual_learning.simulation --cfg <cfg>
    stdout+stderr -> log_path (truncate).
    Returns (Popen, train_start_wall_time).
    """
    ensure_dir(log_path.parent)
    # Truncate log each run 
    log_f = log_path.open("w", encoding="utf-8", buffering=1)

    env = os.environ.copy()
    # Ensure training_quantization is importable when running -m
    # (repo_root must be on PYTHONPATH; repo_root contains training_quantization/)
    prev_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + prev_pp if prev_pp else "")

    cmd = [
        sys.executable,
        "-m",
        "python-app-image-tof-flight.training_quantization.continual_learning.simulation",
        "--cfg",
        str(cfg_path),
    ]

    train_start_wall = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        text=True,  # log_f is text anyway
    )

    # Attach handle so it isn't GC'd early
    proc._opencv_viewer_log_handle = log_f  # type: ignore[attr-defined]
    return proc, train_start_wall


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


# =============================================================================
# Main
# =============================================================================
def crazyflie_viewer(shared_state) -> None:
    parser = argparse.ArgumentParser(
        description="AI-deck streamer + ToF serial (TOF8X8 CSV) + GateClassifier overlay + collision dump + optional finetune on dump + continuous model-input recording."
    )
    parser.add_argument("-n", default="192.168.4.1", metavar="ip", help="AI-deck IP (default: 192.168.4.1)")
    parser.add_argument("-p", type=int, default=5000, metavar="port", help="AI-deck port (default: 5000)")
    parser.add_argument("--ckpt", type=str, required=True, help="Path to GateClassifier checkpoint (.pt)")
    parser.add_argument("--deterministic", action="store_true", help="Enable deterministic mode (compat.set_device)")

    # Camera preprocessing
    parser.add_argument("--cam_preproc", type=str, default="crop", choices=["crop", "resize"])

    # Median + EMA on predictions
    parser.add_argument("--median_k", type=int, default=11,
                        help="Median filter window over prediction frames. Use 1 to disable. Default: 3")
    parser.add_argument("--ema_percent", type=float, default=100,
                        help="EMA alpha percentage applied after median filter. Example: 35 -> alpha=0.35. Default: 35")

    # Optional ToF orientation fixes (default OFF)
    parser.add_argument("--tof_transpose", action="store_true", help="Transpose 8x8 ToF before processing")
    parser.add_argument("--tof_flip_x", action="store_true", help="Flip ToF left-right before processing")
    parser.add_argument("--tof_flip_y", action="store_true", help="Flip ToF top-bottom before processing")

    # UI
    parser.add_argument("--show_raw", action="store_true", help="Show a raw Bayer window (if fmt=0)")
    parser.add_argument("--window", type=str, default="AI-deck + ToF + p(gate)", help="OpenCV window name")
    parser.add_argument("--thr", type=float, default=0.5)
    parser.add_argument("--panel_h", type=int, default=360, help="Height of the combined display window (default: 360)")

    # Debug/model-input visualization
    parser.add_argument("--show_model_inputs", action="store_true",
                        help="Show additional debug window with raw/decoded inputs and transformed model inputs.")
    parser.add_argument("--debug_window", type=str, default="Raw + model inputs", help="Debug window name for raw/transformed inputs")
    parser.add_argument("--debug_panel_size", type=int, default=300, help="Per-panel size for debug visualization")

    # ToF visualization scaling (mm)
    parser.add_argument("--tof_vis_min", type=float, default=200.0, help="ToF heatmap min (mm) (default: 200)")
    parser.add_argument("--tof_vis_max", type=float, default=4000.0, help="ToF heatmap max (mm) (default: 4000)")
    parser.add_argument("--tof_panel_size", type=int, default=320, help="ToF panel size (px) (default: 320)")

    # Plot
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--plot_window", type=str, default="p(gate) realtime")
    parser.add_argument("--plot_history_s", type=float, default=30.0)
    parser.add_argument("--plot_w", type=int, default=640)
    parser.add_argument("--plot_h", type=int, default=240)

    # Ring-buffer + collision dump
    parser.add_argument("--buffer_n", type=int, default=0, help="Keep last N samples (camera+tof) in RAM. 0 disables.")
    parser.add_argument("--buffer_key", type=str, default="d", help="Press this key to dump buffered samples to collision_dataset.")
    parser.add_argument("--save_collision", action="store_true", help="Enable collision dataset dump feature (requires --buffer_n > 0).")

    # Continuous recording to another dataset-like directory
    parser.add_argument("--record_root", type=str, default=None,
                        help="Root folder for continuous recorded model-input pairs. Default: <training_quantization>/recorded_dataset/train")
    parser.add_argument("--record_name", type=str, default="live_recording",
                        help="Logical recording name under record_root. A timestamped session is created inside it.")
    parser.add_argument("--record_start_key", type=str, default="a",
                        help="Key to start continuous recording. Default: a")
    parser.add_argument("--record_stop_key", type=str, default="b",
                        help="Key to stop continuous recording. Default: b")

    # Collision dataset destination 
    this_dir = Path(__file__).resolve().parent                 # .../continual_learning/
    tq_dir = this_dir.parent.resolve()                          # .../training_quantization
    python_dir = tq_dir.parent.resolve()                      # .../python-app-image-tof-logger/
    repo_root =  python_dir.parent.resolve()                    # .../tof-camera-logger
    default_collision_root = tq_dir / "collision_dataset" / "train"
    default_record_root = tq_dir / "recorded_dataset" / "train"

    parser.add_argument("--collision_root", type=str, default=str(default_collision_root))
    parser.add_argument("--collision_name", type=str, default="collision_0")
    parser.add_argument("--collision_label", type=str, default="no_gate", choices=["no_gate", "gate"])

    # Fine-tuning on dump
    parser.add_argument("--finetune_on_dump", action="store_true",
                        help="If set, pressing buffer_key will also start simulation.py fine-tuning (as subprocess).")
    parser.add_argument("--sim_cfg", type=str, default=str(this_dir / "config.json"),
                        help="Path to continual_learning/config.json used by simulation.py (default: continual_learning/config.json)")
    parser.add_argument("--train_log", type=str, default=str(python_dir / "simulation_last.log"),
                        help="Where to write simulation.py stdout/stderr (default: continual_learning/simulation_last.log)")
    parser.add_argument("--throwaway_models_dir", type=str, default=str( python_dir/ "training_quantization" / "throwaway_models"),
                        help="Directory where new fine-tuned checkpoints are created (default: training_quantization/throwaway_models)")
    parser.add_argument("--log_tail_lines", type=int, default=10, help="How many simulation log lines to show in overlay (default: 10)")

    args, _ = parser.parse_known_args()

    if args.record_root is None:
        args.record_root = str(default_record_root)

    # Validate single-char keys
    for key_name in ("buffer_key", "record_start_key", "record_stop_key"):
        if len(getattr(args, key_name)) != 1:
            raise ValueError(f"--{key_name} must be a single character.")
        
    # Avoid key conflicts
    keys_used = {
        "buffer_key": args.buffer_key,
        "record_start_key": args.record_start_key,
        "record_stop_key": args.record_stop_key,
    }
    if len(set(keys_used.values())) != len(keys_used):
        raise ValueError(
            f"Key conflict detected: {keys_used}. "
            "Use different keys for collision dump, record start, and record stop."
        )

    if int(args.median_k) <= 0:
        raise ValueError("--median_k must be >= 1")
    if int(args.median_k) % 2 == 0:
        raise ValueError("--median_k should be odd for a true median filter (e.g. 1, 3, 5)")
    if float(args.ema_percent) <= 0.0 or float(args.ema_percent) > 100.0:
        raise ValueError("--ema_percent must be in the range (0, 100]. Example: 35")

    device = robust_set_device(deterministic=args.deterministic)
    print(f"[INFO] Using device: {device}")

    ckpt_path = Path(args.ckpt).resolve()
    if not ckpt_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")
    print(f"[INFO] Loading checkpoint: {ckpt_path}")
    model = load_gate_model(str(ckpt_path), device)
    current_model_path = ckpt_path

    pred_filter = MedianProbabilityFilter(window_size=int(args.median_k))
    ema_filter = EMAProbabilityFilter(alpha=float(args.ema_percent) / 100.0)
    print(f"[INFO] Prediction median filter ON -> k={args.median_k}")
    print(f"[INFO] Prediction EMA filter ON -> alpha={float(args.ema_percent) / 100.0:.3f} ({args.ema_percent:.1f}%)")

    # Plotter
    plotter: Optional[RealTimeProbabilityPlot] = None
    if args.plot:
        if int(args.median_k) > 1:
            plot_title = f"p(gate) vs time (median k={args.median_k} + ema {args.ema_percent:.0f}%)"
        else:
            plot_title = f"p(gate) vs time (ema {args.ema_percent:.0f}%)"
        plotter = RealTimeProbabilityPlot(
            history_s=float(args.plot_history_s),
            width=int(args.plot_w),
            height=int(args.plot_h),
            title=plot_title,
        )
        print(f"[INFO] Plot ON -> window='{args.plot_window}'")

    # Collision dataset dirs
    collision_cam_dir: Optional[Path] = None
    collision_tof_dir: Optional[Path] = None

    if args.save_collision:
        if int(args.buffer_n) <= 0:
            raise ValueError("--save_collision requires --buffer_n > 0 (buffer is the thing you dump).")

        base = Path(args.collision_root) / args.collision_name / args.collision_label
        collision_cam_dir = base / "camera_images"
        collision_tof_dir = base / "tof_distance_array"
        ensure_dir(collision_cam_dir)
        ensure_dir(collision_tof_dir)

        print(f"[INFO] Collision dump enabled -> {base}")
        print(f"[INFO] Dump key: '{args.buffer_key}'")
        print("[INFO] Dump behavior: wipes old .npy then saves buffer starting from 000000.npy")
        if args.finetune_on_dump:
            print("[INFO] Fine-tune ON: after dump, starts simulation.py (subprocess), shows log tail, reloads newest ckpt on finish.")
    
    # Continuous recording config
    record_root = Path(args.record_root).resolve()
    ensure_dir(record_root)
    print(f"[INFO] Continuous recording root: {record_root}")
    print(f"[INFO] Recording keys: start='{args.record_start_key}', stop='{args.record_stop_key}'")

    # Ring buffer of (cam_norm_168, tof_norm_21) to dump as npy
    buffer_data: Deque[Tuple[np.ndarray, np.ndarray]] = deque(maxlen=max(0, int(args.buffer_n)))
    plot_history_18s: Deque[Tuple[float, float]] = deque()

    # Continuous recording state
    recording_active = False
    recording_session_dir: Optional[Path] = None
    recording_cam_dir: Optional[Path] = None
    recording_tof_dir: Optional[Path] = None
    recording_idx = 0

    # Camera FPS
    start_time = time.time()
    frame_count = 0
    last_time = time.time()

    # Training state (subprocess)
    train_proc: Optional[subprocess.Popen] = None
    train_start_wall: Optional[float] = None
    train_start_mon: Optional[float] = None
    train_log_path = Path(args.train_log).resolve()
    sim_cfg_path = Path(args.sim_cfg).resolve()
    throwaway_models_dir = Path(args.throwaway_models_dir).resolve()

    status_msg = ""
    status_until = 0.0
    status_crash = shared_state['crash']
    last_combined_frame: Optional[np.ndarray] = None

    def set_status(msg: str, seconds: float = 2.0) -> None:
        nonlocal status_msg, status_until
        status_msg = msg
        status_until = time.time() + float(seconds)

    def clear_crash_flag() -> None:
        with shared_state['lock']:
            shared_state['crash'] = 0

    def handle_collision_dump_and_training(*, trigger_reason: str, combined_frame: Optional[np.ndarray]) -> bool:
        nonlocal train_proc, train_start_wall, train_start_mon, current_model_path

        if collision_cam_dir is None or collision_tof_dir is None:
            set_status("Collision saving is disabled; cannot retrain.", seconds=3.0)
            return False

        # If training is running, keep a crash trigger pending so it can be handled
        # after the current training subprocess finishes.
        if train_proc is not None:
            set_status("Training already running: dump deferred.", seconds=2.0)
            return False

        if len(buffer_data) == 0:
            set_status("Buffer empty (nothing to save)", seconds=2.0)
            return False

        # Wipe old data on disk and save from 0
        try:
            wipe_collision_leaf_dirs(collision_cam_dir, collision_tof_dir)
        except Exception as e:
            print(f"[WARN] Failed to wipe collision dirs: {e}")
            set_status("Failed to wipe dataset dirs (see terminal).", seconds=3.0)
            return False

        frames_to_skip = 20
        buffer_list = list(buffer_data)
        if len(buffer_list) > frames_to_skip:
            data_to_dump = buffer_list[:-frames_to_skip]
            skipped_n = frames_to_skip
        else:
            data_to_dump = buffer_list
            skipped_n = 0
            print(f"[WARN] Buffer too short to skip {frames_to_skip} frames.")

        saved_n = dump_collision_buffer_zero_index(
            buffer_data=data_to_dump,
            cam_dir=collision_cam_dir,
            tof_dir=collision_tof_dir,
        )
        print(f"[INFO] Collision dump: saved {saved_n}(skipped {skipped_n}) samples -> {collision_cam_dir.parent}")
        set_status(f"Saved {saved_n} samples (skipped {skipped_n})(index reset to 0)", seconds=2.5)

        # log crash/manual event
        crash_log_path = this_dir / "crash_events.log"

        crash_id = time.strftime("%Y%m%d_%H%M%S")
        last_frame_idx = max(0, saved_n - 1)

        plot_frames_count = len(plot_history_18s)
        plot_start_frame = max(1, frame_count - plot_frames_count + 1)
        plot_end_frame = frame_count

        collision_end_frame = frame_count - skipped_n
        collision_start_frame = max(1, frame_count - saved_n + 1)

        log_msg = (
            f"{trigger_reason.upper()} DUMP TRIGGERED: {crash_id}\n"
            f"  - Target: {args.collision_name}/{args.collision_label}\n"
            f"  - Total Frames: {saved_n}\n"
            f"  - Dumped Files: {args.collision_root}/{args.collision_name} -> 000000.npy to {last_frame_idx:06d}.npy\n"
            f"  - Collision Frames: {collision_start_frame} to {collision_end_frame}\n"
            f"  - Plot Frames (18s context): {plot_start_frame} to {plot_end_frame}\n"
            f"  - Model in use: {current_model_path.name}\n"
            f"--------------------------------------------------\n"
        )

        try:
            with open(crash_log_path, "a", encoding="utf-8") as f:
                f.write(log_msg)
            print(f"[INFO] Crash event logged to {crash_log_path}")
        except Exception as e:
            print(f"[WARN] Could not write to crash log: {e}")

        if combined_frame is not None:
            img_save_path = this_dir / f"crash_{crash_id}_visual.png"
            try:
                cv2.imwrite(str(img_save_path), combined_frame)
            except Exception as e:
                print(f"[WARN] Failed to save crash visual: {e}")

        # generate the confidence plot
        plot_save_path = this_dir / f"crash_{crash_id}_plot.pdf"
        try:
            # Extract timestamps and probabilities
            t_vals = [item[0] for item in plot_history_18s]
            p_vals = [item[1] for item in plot_history_18s]

            # Normalize time so the graph starts at 0.0s
            if t_vals:
                t0 = t_vals[0]
                t_vals = [t - t0 for t in t_vals]

            plot_frames_count = len(t_vals)
            plot_start_frame = max(1, frame_count - plot_frames_count + 1)
            avg_fps_18s = plot_frames_count / 18.0 if plot_frames_count > 0 else 0.0

            plt.figure(figsize=(10, 4))
            plt.plot(t_vals, p_vals, label="p(gate) EMA", color='#4c72b0') # standard blue
            plt.axhline(y=0.5, color='steelblue', linestyle='--', linewidth=1)
            plt.ylim(-0.05, 1.05)

            # Match the title and labels from the Vicon table exactly
            plt.title(f"Confidence vs Time | frames {plot_start_frame}-{frame_count} @ {avg_fps_18s:.1f} fps", fontsize=10)
            plt.xlabel("Tempo [s] (t=0 all frame start)", fontsize=9)
            plt.ylabel("p(gate)", fontsize=9)

            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(str(plot_save_path), dpi=150)
            plt.close()
        except Exception as e:
            print(f"[WARN] Failed to save crash plot: {e}")

        # Start fine-tuning if requested
        if args.finetune_on_dump:
            if not sim_cfg_path.exists():
                print(f"[WARN] sim_cfg not found: {sim_cfg_path}")
                set_status("Config.json not found for simulation.py", seconds=3.0)
                return True

            try:
                train_proc, train_start_wall = start_simulation_subprocess(
                    repo_root=repo_root,
                    cfg_path=sim_cfg_path,
                    log_path=train_log_path,
                )
                train_start_mon = time.monotonic()
                print("================================================================")
                print("[OPENCV-VIEWER] TRAINING STARTED (simulation.py)")
                print(f"  cfg = {sim_cfg_path}")
                print(f"  log = {train_log_path}")
                print("================================================================")
                set_status("TRAINING STARTED (see log tail in overlay)", seconds=3.0)
            except Exception as e:
                print(f"[WARN] Failed to start training: {e}")
                set_status("Failed to start training (see terminal).", seconds=3.0)

        return True

    try:
        while True:
            pair = None
            with buffer_lock:
                if len(paired_buffer) > 0:
                    pair = paired_buffer[-1]
                    paired_buffer.clear()

            with shared_state['lock']:
                status_crash = shared_state['crash']
            

            if pair is None:
                if status_crash == 1:
                    handled = handle_collision_dump_and_training(
                        trigger_reason="crash",
                        combined_frame=last_combined_frame,
                    )
                    if handled:
                        clear_crash_flag()
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            cam_decoded, latest_tof_mm, meta = pair

            frame_count += 1
            
            latest_tof_seq = meta['seq']
            tof_fps_i = meta['fps_inst']
            tof_fps_a = meta['fps_avg']
            latest_tof_t_mon = meta['t_mon']

            try:
                cam_uint8 = img_preprocessing.camera_uint8_168(cam_decoded, preproc=args.cam_preproc)
                cam_norm = img_preprocessing.camera_norm_168(cam_decoded, preproc=args.cam_preproc)
            except Exception as e:
                raise RuntimeError(
                    f"Camera preprocessing failed with cam_preproc='{args.cam_preproc}'. "
                    f"Try --cam_preproc resize.\nError: {e}"
                ) from e
            
            tof_norm = tof_preprocessing.tof_norm_21x21_from_8x8_mm(latest_tof_mm)

            # RAM ring buffer for collision dump
            if args.save_collision and int(args.buffer_n) > 0:
                buffer_data.append((cam_norm, tof_norm))
            
            # Continuous recording directly to disk
            if recording_active and recording_cam_dir is not None and recording_tof_dir is not None:
                save_pair_at_index(
                    cam_arr=cam_norm,
                    tof_arr=tof_norm,
                    cam_dir=recording_cam_dir,
                    tof_dir=recording_tof_dir,
                    idx=recording_idx,
                )
                recording_idx += 1

            # Inference + median filter + EMA filter
            p_gate_raw = infer_gate_probability(model, cam_norm, tof_norm, device=device)
            p_gate_med = pred_filter.update(p_gate_raw)
            p_gate_ema = ema_filter.update(p_gate_med)
            pred = "GATE" if p_gate_ema >= float(args.thr) else "NO_GATE"
            
            with shared_state['lock']:
                shared_state['p_gate'] = p_gate_ema
                status_crash = shared_state['crash']


            # Camera FPS
            now = time.time()
            dt = now - last_time
            last_time = now
            cam_fps_inst = (1.0 / dt) if dt > 1e-6 else 0.0
            cam_fps_avg = frame_count / max(1e-6, (now - start_time))

            plot_history_18s.append((now, p_gate_ema))
            while plot_history_18s and (now-plot_history_18s[0][0]) > 18.0:
                plot_history_18s.popleft()

            # Plot update 
            if plotter is not None:
                plotter.add(now - start_time, p_gate_ema)
                cv2.imshow(args.plot_window, plotter.render())
                cv2.waitKey(1)

            # Add ToF seq + age + tof fps on the ToF panel
            age_ms: Optional[float] = None
            if latest_tof_t_mon is not None:
                age_ms = (time.monotonic() - latest_tof_t_mon) * 1000.0

            seq_str = "seq=NA" if latest_tof_seq is None else f"seq={latest_tof_seq}"
            age_str = "age=NA" if age_ms is None else f"age={age_ms:.0f}ms"

            # ToF visualization panel (display uses mm, not standardized)
            tof_panel = render_tof_heatmap_panel_mm(
                latest_tof_mm,
                panel_size=int(args.tof_panel_size),
                vmin_mm=float(args.tof_vis_min),
                vmax_mm=float(args.tof_vis_max),
                draw_grid=True,
                title="ToF 8x8 (mm)",
                bottom_text=f"{seq_str}  {age_str}  tof_fps={tof_fps_i:.1f}Hz (avg {tof_fps_a:.1f})",
            )

            # --- Safety before processing ---
            if cam_decoded is None or cam_decoded.size == 0:
                print("[WARN] Received empty camera frame. Skipping stack.")
                continue

            if cam_decoded.ndim == 2:
                cam3d = cv2.cvtColor(cam_decoded, cv2.COLOR_GRAY2BGR)
            else:
                cam3d = cam_decoded

            if tof_panel is None or tof_panel.size == 0:
                print("[WARN] ToF panel generation failed. Skipping stack.")
                continue

            # --- Combine camera + ToF in ONE window ---
            try :
                combined = hstack_resize_to_height(cam3d, tof_panel, height=int(args.panel_h))
                last_combined_frame = combined
            except Exception as e:
                print(f"[ERROR] hstack failed : {e}")
                continue

            # --- Training state update (non-blocking) ---
            training_state_line = "TRAINING: idle"
            log_tail: List[str] = []

            if train_proc is not None:
                rc = train_proc.poll()
                if rc is None:
                    elapsed = 0.0
                    if train_start_mon is not None:
                        elapsed = time.monotonic() - train_start_mon
                    training_state_line = f"TRAINING: running ({elapsed:.1f}s)"
                    log_tail = tail_lines(train_log_path, max_bytes=20000, max_lines=int(args.log_tail_lines))
                else:
                    close_simulation_log_handle(train_proc)
                    elapsed = 0.0
                    if train_start_mon is not None:
                        elapsed = time.monotonic() - train_start_mon

                    training_state_line = f"TRAINING: finished rc={rc} ({elapsed:.1f}s)"
                    set_status(training_state_line, seconds=3.0)

                    # Try to load newest checkpoint
                    if train_start_wall is None:
                        train_start_wall = now

                    new_ckpt = find_newest_checkpoint(throwaway_models_dir, after_wall_time=float(train_start_wall))
                    if new_ckpt is None:
                        print("[WARN] Training finished but no checkpoint found in throwaway_models.")
                        set_status("Training finished but no new ckpt found.", seconds=3.0)
                    else:
                        try:
                            print(f"[INFO] Loading NEW checkpoint: {new_ckpt}")
                            model = load_gate_model(str(new_ckpt), device)
                            current_model_path = new_ckpt
                            buffer_data.clear()
                            pred_filter.reset()
                            ema_filter.reset()
                            set_status(
                                f"Loaded new model: {new_ckpt.name} | buffer cleared | median+ema reset", 
                                seconds=3.0,
                            )
                            print("[INFO] loaded model")
                        except Exception as e:
                            print(f"[WARN] Failed to load new checkpoint '{new_ckpt}': {e}")
                            set_status("Training finished, but failed to load new model (see terminal).", seconds=4.0)

                    train_proc = None
                    train_start_wall = None
                    train_start_mon = None

            if recording_active:
                rec_line = f"RECORDING: ON  saved={recording_idx}"
            else:
                rec_line = "RECORDING: OFF"

            overlay_lines = [
                f"p(gate) raw={p_gate_raw:.3f}   median{args.median_k}={p_gate_med:.3f}   ema{args.ema_percent:.0f}%={p_gate_ema:.3f}   pred@{args.thr:.2f}={pred}",
                f"CAM FPS inst/avg = {cam_fps_inst:.1f} / {cam_fps_avg:.1f}",
                f"TOF FPS inst/avg = {tof_fps_i:.1f} / {tof_fps_a:.1f}",
                f"ToF: {seq_str}, {age_str}  (paired as: camera_frame + latest_ToF)",
                f"Model: {current_model_path.name}",
                rec_line,
                training_state_line,
            ]

            if args.show_model_inputs:
                overlay_lines.append("Debug view ON: raw + transformed model inputs")

            if log_tail:
                overlay_lines.append("--- simulation.py tail ---")
                overlay_lines.extend(log_tail)

            keys_line = f"Keys: q=quit, {args.record_start_key}=start_rec, {args.record_stop_key}=stop_rec"
            if args.save_collision and int(args.buffer_n) > 0:
                keys_line += f", {args.buffer_key}=dump_buffer"
                if args.finetune_on_dump:
                    keys_line += "+finetune"
            if args.plot:
                keys_line += ", (plot ON)"
            if args.show_model_inputs:
                keys_line += ", (debug inputs ON)"
            overlay_lines.append(keys_line)

            if status_msg and now < status_until:
                overlay_lines.append(status_msg)

            shown = overlay_text(combined, overlay_lines)
            cv2.imshow(args.window, shown)

            if args.show_model_inputs:
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

                debug_grid = make_debug_grid_2x2(
                    cam_raw_panel,
                    cam_model_panel,
                    tof_raw_panel,
                    tof_model_panel,
                )
                cv2.imshow(args.debug_window, debug_grid)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            
            # Start continuous recording
            if key == ord(args.record_start_key):
                if recording_active:
                    set_status("Recording already active.", seconds=2.0)
                else:
                    session_name = make_session_stamp()
                    recording_session_dir = record_root / args.record_name / session_name
                    recording_cam_dir = recording_session_dir / "camera_images"
                    recording_tof_dir = recording_session_dir / "tof_distance_array"

                    wipe_leaf_dirs(recording_cam_dir, recording_tof_dir)

                    recording_idx = 0
                    recording_active = True

                    print(f"[INFO] Recording started -> {recording_session_dir}")
                    set_status(f"Recording started: {session_name}", seconds=2.5)
            
             # Stop continuous recording
            if key == ord(args.record_stop_key):
                if not recording_active:
                    set_status("Recording is not active.", seconds=2.0)
                else:
                    recording_active = False
                    saved_path = str(recording_session_dir) if recording_session_dir is not None else "NA"
                    print(f"[INFO] Recording stopped -> saved {recording_idx} samples in {saved_path}")
                    set_status(f"Recording stopped: saved {recording_idx} samples", seconds=3.0)


            # --- Dump ring buffer to collision_dataset on key press ---
            if (args.save_collision and int(args.buffer_n) > 0 and key == ord(args.buffer_key)) or (status_crash == 1):
                trigger_reason = "crash" if status_crash == 1 else "manual"
                handled = handle_collision_dump_and_training(
                    trigger_reason=trigger_reason,
                    combined_frame=combined,
                )
                if handled and status_crash == 1:
                    clear_crash_flag()

    except KeyboardInterrupt:
        pass
    finally:
        # Stop training process if still running
        try:
            if train_proc is not None and train_proc.poll() is None:
                print("[INFO] Terminating training subprocess...")
                try:
                    train_proc.terminate()
                except Exception:
                    pass
                # give it a moment
                t0 = time.time()
                while time.time() - t0 < 1.5:
                    if train_proc.poll() is not None:
                        break
                    time.sleep(0.05)
                if train_proc.poll() is None:
                    try:
                        train_proc.kill()
                    except Exception:
                        pass
            if train_proc is not None:
                close_simulation_log_handle(train_proc)
        except Exception:
            pass

        try:
            if recording_active:
                print(f"[INFO] Recording stopped on exit. Saved samples: {recording_idx}")
        except Exception:
            pass

        cv2.destroyAllWindows()
        print("[INFO] Exiting.")
