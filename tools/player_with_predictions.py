#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
player.py — RAW float32 viewer con range GLOBALI auto-calcolati (no per-frame)
+ pannello predizioni p(gate) al posto delle matrici RAW.

Supporta:
A) Dataset splittato:
root/
  training/ (o train/)
    gate/camera_images/*.npy
    gate/tof_distance_array/*.npy
    no_gate/...
  validation/...
  test/...

B) Singolo run:
root/
  camera_images/*.npy
  tof_distance_array/*.npy

C) Collezione di run:
root/
  1/camera_images/*.npy
  1/tof_distance_array/*.npy
  2/...

Mostra:
- sinistra: CAMERA + TOF visualizzati con mapping lineare a uint8 usando range globali
- destra  : grafico predizioni p(gate) stile opencv-viewer.py + info campione corrente

Tasti:
  s   -> avanti
  q   -> indietro
  ESC -> esci

Note predizioni:
- Per avere il grafico reale delle predizioni serve passare --ckpt.
- Gli .npy vengono usati come input modello. Questo è coerente con i dataset registrati
  da opencv-viewer.py, dove camera e ToF sono già preprocessati/standardizzati.
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Iterable, List, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt

try:
    import cv2
except Exception:
    print("ERRORE: OpenCV (cv2) non disponibile. Installa con: pip install opencv-python")
    raise

try:
    import torch
except Exception:
    torch = None  # type: ignore[assignment]


# -----------------------------
# Model input constants
# -----------------------------
IMG_ROWS_CNN = 168
IMG_COLS_CNN = 168
TOF_ROWS_CNN = 21
TOF_COLS_CNN = 21


# -----------------------------
# Data structures
# -----------------------------
@dataclass(frozen=True)
class Item:
    group: str
    cam_path: Path
    tof_path: Optional[Path]


@dataclass(frozen=True)
class Prediction:
    raw: float
    median: float
    ema: float
    pred: str
    error: Optional[str] = None


def _natural_key(p: Path) -> Tuple:
    try:
        return (int(p.stem),)
    except Exception:
        return (p.stem,)


# -----------------------------
# Saves frames and probability plot
# -----------------------------
def save_as_pdf(img_bgr: np.ndarray, filename: str):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    h,w,_ = img_rgb.shape
    dpi = 100
    figsize = (w / dpi, h / dpi)

    fig = plt.figure(figsize=figsize, dpi=dpi)
    ax = plt.Axes(fig, [0.,0.,1.,1.])
    ax.set_axis_off()
    fig.add_axes(ax)

    ax.imshow(img_rgb)
    plt.savefig(filename, format='pdf', bbox_inches='tight', pad_inches= 0)
    plt.close()
    print(f"saved: {filename}")


# -----------------------------
# Raw shape handling (NO changes to values for display/stats)
# -----------------------------
def squeeze_to_hw(arr: np.ndarray, *, name: str) -> np.ndarray:
    """Accetta (H,W), (1,H,W), (H,W,1) -> (H,W) senza modificare i valori."""
    a = np.asarray(arr)
    if a.ndim == 2:
        return a
    if a.ndim == 3 and a.shape[0] == 1:
        return a[0]
    if a.ndim == 3 and a.shape[-1] == 1:
        return a[..., 0]
    raise ValueError(f"{name}: shape non supportata: {a.shape}")


def stats(arr: np.ndarray) -> Tuple[float, float, float, float]:
    a = np.asarray(arr)
    return float(a.min()), float(a.max()), float(a.mean()), float(a.std())


def finite_minmax(arr: np.ndarray) -> Optional[Tuple[float, float]]:
    """
    Min/max ignorando NaN/Inf se float.
    Ritorna None se non ci sono valori finiti.
    """
    a = np.asarray(arr)
    if np.issubdtype(a.dtype, np.floating):
        m = np.isfinite(a)
        if not np.any(m):
            return None
        vmin = float(a[m].min())
        vmax = float(a[m].max())
        return vmin, vmax
    return float(a.min()), float(a.max())


# -----------------------------
# Display mapping (GLOBAL, NO per-frame normalization)
# -----------------------------
def map_float_to_u8(x_hw: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """
    Mapping lineare a uint8 con scala FISSA globale:
      u8 = clip((x - vmin) / (vmax - vmin) * 255)

    Questo è SOLO per VISUALIZZARE.
    """
    x = np.asarray(x_hw, dtype=np.float32)

    if not np.isfinite(vmin) or not np.isfinite(vmax) or float(vmax) <= float(vmin):
        return np.zeros_like(x, dtype=np.uint8)

    den = float(vmax) - float(vmin)
    y = (x - float(vmin)) / den
    y = np.clip(y, 0.0, 1.0) * 255.0
    return y.astype(np.uint8, copy=False)


# -----------------------------
# Image stacking helpers
# -----------------------------
def stack_h(left: np.ndarray, right: np.ndarray, bg: int = 240) -> np.ndarray:
    h = max(left.shape[0], right.shape[0])
    out = np.full((h, left.shape[1] + right.shape[1], 3), bg, dtype=np.uint8)
    out[:left.shape[0], :left.shape[1]] = left
    out[:right.shape[0], left.shape[1]:] = right
    return out


def stack_v(top: np.ndarray, bottom: np.ndarray, bg: int = 240) -> np.ndarray:
    w = max(top.shape[1], bottom.shape[1])
    out = np.full((top.shape[0] + bottom.shape[0], w, 3), bg, dtype=np.uint8)
    out[:top.shape[0], :top.shape[1]] = top
    out[top.shape[0]:top.shape[0] + bottom.shape[0], :bottom.shape[1]] = bottom
    return out


# -----------------------------
# Dataset discovery
# -----------------------------
def _iter_run_roots(root: Path) -> Iterable[Path]:
    """
    - se root contiene camera_images/ -> è un run
    - altrimenti, se root ha sottodir con camera_images/ -> collezione di run
    """
    root = root.resolve()
    if (root / "camera_images").is_dir():
        yield root
        return

    subs = [d for d in root.iterdir() if d.is_dir() and (d / "camera_images").is_dir()]
    subs.sort(key=_natural_key)
    for d in subs:
        yield d


import os

def is_valid_npy(path: Path) -> bool:
    """Check if the file exists and is larger than a standard NumPy header (usually ~128 bytes)."""
    return path.is_file() and os.path.getsize(path) > 128

def collect_items(root: Path, split: str, cls: str) -> List[Item]:
    root = root.resolve()

    # split-mode?
    split_dirs = [p for p in ("training", "validation", "test", "train") if (root / p).is_dir()]
    if split_dirs:
        split_candidates = ["training", "validation", "test", "train"] if split == "all" else [split]
        cls_candidates = ["gate", "no_gate"] if cls == "all" else [cls]

        items: List[Item] = []
        for sp in split_candidates:
            sp_dir = root / sp
            if not sp_dir.is_dir():
                continue
            for c in cls_candidates:
                cam_dir = sp_dir / c / "camera_images"
                tof_dir = sp_dir / c / "tof_distance_array"
                if not cam_dir.is_dir():
                    continue

                cam_files = sorted(cam_dir.glob("*.npy"), key=_natural_key)
                for cam_path in cam_files:
                    tof_path = tof_dir / cam_path.name
                    
                    # NEW: Validate files before adding
                    if not is_valid_npy(cam_path):
                        print(f"[WARN] Skipping corrupted camera file: {cam_path}")
                        continue
                        
                    tof_is_valid = tof_path is not None and is_valid_npy(tof_path)
                    
                    items.append(
                        Item(
                            group=f"{sp}/{c}",
                            cam_path=cam_path,
                            tof_path=tof_path if tof_is_valid else None,
                        )
                    )
        return items

    # run(s)-mode
    items: List[Item] = []
    for run_root in _iter_run_roots(root):
        cam_dir = run_root / "camera_images"
        tof_dir = run_root / "tof_distance_array"
        cam_files = sorted(cam_dir.glob("*.npy"), key=_natural_key)

        group = str(run_root.relative_to(root)) if run_root != root else str(root.name)

        for cam_path in cam_files:
            tof_path = tof_dir / cam_path.name
            
            # NEW: Validate files before adding
            if not is_valid_npy(cam_path):
                print(f"[WARN] Skipping corrupted camera file: {cam_path}")
                continue
                
            tof_is_valid = tof_path is not None and is_valid_npy(tof_path)

            items.append(
                Item(
                    group=f"run:{group}",
                    cam_path=cam_path,
                    tof_path=tof_path if tof_is_valid else None,
                )
            )
    return items

    # run(s)-mode
    items: List[Item] = []
    for run_root in _iter_run_roots(root):
        cam_dir = run_root / "camera_images"
        tof_dir = run_root / "tof_distance_array"
        cam_files = sorted(cam_dir.glob("*.npy"), key=_natural_key)

        group = str(run_root.relative_to(root)) if run_root != root else str(root.name)

        for cam_path in cam_files:
            tof_path = tof_dir / cam_path.name
            items.append(
                Item(
                    group=f"run:{group}",
                    cam_path=cam_path,
                    tof_path=tof_path if tof_path.is_file() else None,
                )
            )
    return items


def compute_global_ranges(items: List[Item]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Scansiona TUTTO una volta e trova min/max globali di camera e tof.
    NESSUNA normalizzazione per-frame.
    """
    cam_min = float("inf")
    cam_max = float("-inf")
    tof_min = float("inf")
    tof_max = float("-inf")
    has_tof = False

    n = len(items)
    for i, it in enumerate(items, 1):
        cam = np.load(it.cam_path, allow_pickle=False, mmap_mode="r")
        cam_hw = squeeze_to_hw(cam, name="CAMERA")
        mm = finite_minmax(cam_hw)
        if mm is not None:
            cam_min = min(cam_min, mm[0])
            cam_max = max(cam_max, mm[1])

        if it.tof_path is not None:
            tof = np.load(it.tof_path, allow_pickle=False, mmap_mode="r")
            tof_hw = squeeze_to_hw(tof, name="TOF")
            mm2 = finite_minmax(tof_hw)
            if mm2 is not None:
                tof_min = min(tof_min, mm2[0])
                tof_max = max(tof_max, mm2[1])
                has_tof = True

        if (i % 200) == 0 or i == n:
            print(f"[scan ranges] {i}/{n}", end="\r")

    print()

    if not np.isfinite(cam_min) or not np.isfinite(cam_max):
        raise RuntimeError("Impossibile calcolare range globali CAMERA valori non finiti?.")

    if not has_tof:
        tof_min, tof_max = 0.0, 1.0

    if cam_max <= cam_min:
        cam_max = cam_min + 1e-6
    if tof_max <= tof_min:
        tof_max = tof_min + 1e-6

    return (cam_min, cam_max), (tof_min, tof_max)


# -----------------------------
# Model loading / inference
# -----------------------------
MILKV_DIR = Path(__file__).resolve().parent.parent / "milkv"   # training code lives in milkv/


def _ensure_sys_path_for_models() -> None:
    """
    GateClassifier è atteso in milkv/training_quantization/model/.
    """
    if str(MILKV_DIR) not in sys.path:
        sys.path.insert(0, str(MILKV_DIR))


def import_gate_classifier_cls():
    _ensure_sys_path_for_models()
    try:
        from training_quantization.model.gate_classifier_PyTorch_model import GateClassifier  # type: ignore
        return GateClassifier
    except Exception as e:
        raise ImportError(
            "Impossibile importare GateClassifier. Atteso modulo: "
            "training_quantization/models/gate_classifier_PyTorch_model.py"
        ) from e


def robust_set_device(deterministic: bool) -> "torch.device":
    if torch is None:
        raise ImportError("Questo script richiede PyTorch per usare --ckpt. Installa torch nell'ambiente.")

    if deterministic:
        try:
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
        except Exception:
            pass

    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def load_gate_model(ckpt_path: str, device: "torch.device"):
    if torch is None:
        raise ImportError("Questo script richiede PyTorch per usare --ckpt. Installa torch nell'ambiente.")

    GateClassifierCls = import_gate_classifier_cls()
    ckpt = torch.load(str(ckpt_path), map_location=device)

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


def ensure_model_hw(arr_hw: np.ndarray, *, target_hw: Tuple[int, int], name: str) -> np.ndarray:
    """
    Rende l'array compatibile con il modello.
    Se la shape è già corretta non modifica i valori; altrimenti fa resize solo per inferenza.
    """
    x = np.asarray(arr_hw, dtype=np.float32)
    target_h, target_w = target_hw

    if x.shape == (target_h, target_w):       
        return x

    interp = cv2.INTER_AREA if name == "CAMERA" else cv2.INTER_NEAREST
    return cv2.resize(x, (target_w, target_h), interpolation=interp).astype(np.float32, copy=False)


def infer_gate_probability(model, cam_hw: np.ndarray, tof_hw: np.ndarray, device: "torch.device") -> float:
    if torch is None:
        raise ImportError("PyTorch non disponibile.")

    cam_in = ensure_model_hw(cam_hw, target_hw=(IMG_ROWS_CNN, IMG_COLS_CNN), name="CAMERA")
    tof_in = ensure_model_hw(tof_hw, target_hw=(TOF_ROWS_CNN, TOF_COLS_CNN), name="TOF")

    cam_t = torch.from_numpy(cam_in).unsqueeze(0).unsqueeze(0).to(device)
    tof_t = torch.from_numpy(tof_in).unsqueeze(0).unsqueeze(0).to(device)

    model.eval()

    with torch.no_grad():
        out = model(cam_t, tof_t)
        v = float(out.float().view(-1)[0].item())

    return max(0.0, min(1.0, v))


# -----------------------------
# Prediction smoothing, same logic as opencv-viewer.py
# -----------------------------
class MedianProbabilityFilter:
    def __init__(self, window_size: int = 3) -> None:
        self.window_size = int(max(1, window_size))
        self.values: Deque[float] = deque(maxlen=self.window_size)

    def reset(self) -> None:
        self.values.clear()

    def update(self, value: float) -> float:
        v = max(0.0, min(1.0, float(value)))
        self.values.append(v)
        return float(np.median(np.array(self.values, dtype=np.float32)))


class EMAProbabilityFilter:
    def __init__(self, alpha: float = 0.35) -> None:
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


# -----------------------------
# Offline prediction plot, same OpenCV style as opencv-viewer.py
# -----------------------------
class DatasetProbabilityPlot:
    def __init__(
        self,
        *,
        width: int = 820,
        height: int = 360,
        title: str = "p(gate) vs sample",
        history_n: int = 250,
        t0: int=0,
        fps: float=26.0
    ) -> None:
        self.width = int(max(300, width))
        self.height = int(max(180, height))
        self.title = str(title)
        self.history_n = int(max(10, history_n))
        self.t0 = t0
        self.fps = fps

        self.m_left = 55
        self.m_right = 15
        self.m_top = 30
        self.m_bottom = 35

    def _map_x(self, idx: int, i0: int, i1: int) -> int:
        x0, x1 = self.m_left, self.width - self.m_right
        if i1 <= i0:
            return int(x1)
        u = (float(idx) - float(i0)) / float(i1 - i0)
        u = max(0.0, min(1.0, u))
        return int(x0 + u * (x1 - x0))

    def _map_y(self, p: float) -> int:
        y0, y1 = self.height - self.m_bottom, self.m_top
        pv = max(0.0, min(1.0, float(p)))
        return int(y0 - pv * (y0 - y1))

    def render(
        self,
        *,
        predictions: List[Prediction],
        current_idx: int,
        threshold: float,
        line_kind: str = "ema",
    ) -> np.ndarray:
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

        thr = max(0.0, min(1.0, float(threshold)))
        y_thr = self._map_y(thr)
        cv2.line(img, (x0, y_thr), (x1, y_thr), (90, 90, 90), 1)
        cv2.putText(img, f"thr={thr:.2f}", (x1 - 80, y_thr + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (210, 210, 210), 1, cv2.LINE_AA)

        n = len(predictions)
        if n == 0:
            cv2.putText(img, "No predictions. Passa --ckpt per abilitarle.", (x0 + 10, (y0 + y1) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
            return img

        half = self.history_n // 2
        i0 = max(0, int(current_idx) - half)
        i1 = current_idx
        i0 = i1 - self.history_n + 1

        tick_count = 6
        for k in range(tick_count + 1):
            ii = int(round(i0 + (i1 - i0) * k / max(1, tick_count)))
            xx = self._map_x(ii, i0, i1)
            cv2.line(img, (xx, y0), (xx, y0 + 5), (200, 200, 200), 1)
            time_sec = (ii-self.t0)/self.fps
            label = f"{time_sec:+.1f}s"
            cv2.putText(img, label, (xx - 20, y0 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)

        vals: List[float] = []
        for pr in predictions:
            if line_kind == "raw":
                vals.append(pr.raw)
            elif line_kind == "median":
                vals.append(pr.median)
            else:
                vals.append(pr.ema)

        pts: List[Tuple[int, int]] = []
        for ii in range(i0, i1 + 1):
            if 0 <= ii < n:    
                pts.append((self._map_x(ii, i0, i1), self._map_y(vals[ii])))

        if len(pts) >= 2:
            cv2.polylines(img, [np.array(pts, dtype=np.int32)], isClosed=False, color=(0, 255, 0), thickness=2)
        elif len(pts) == 1:
            cv2.circle(img, pts[0], 2, (0, 255, 0), -1)

        if 0 <= current_idx < n:
            cur_p = vals[current_idx]
            cur_pt = (self._map_x(current_idx, i0, i1), self._map_y(cur_p))
            # cv2.circle(img, cur_pt, 5, (0, 255, 255), -1)
            cv2.putText(img, f"p={cur_p:.3f}", (x1 - 90, y1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA)

        return img


def render_prediction_side_panel(
    *,
    plot_img: np.ndarray,
    item: Item,
    idx: int,
    total: int,
    cam_hw: np.ndarray,
    tof_hw: Optional[np.ndarray],
    cam_stats: Tuple[float, float, float, float],
    tof_stats: Optional[Tuple[float, float, float, float]],
    pred: Optional[Prediction],
    ckpt_name: Optional[str],
    threshold: float,
    panel_w: int = 820,
) -> np.ndarray:
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.47
    thickness = 1
    line_h = 22

    info_h = 250
    info = np.full((info_h, panel_w, 3), 245, dtype=np.uint8)

    cam_mn, cam_mx, cam_me, cam_sd = cam_stats

    lines: List[Tuple[str, Tuple[int, int, int]]] = [
        (f"[{idx + 1}/{total}] {item.group}  file={item.cam_path.name}", (0, 0, 0)),
        (f"CAM shape={tuple(cam_hw.shape)} dtype={cam_hw.dtype}  min={cam_mn:.4f} max={cam_mx:.4f} mean={cam_me:.4f} std={cam_sd:.4f}", (0, 0, 0)),
    ]

    if tof_hw is not None and tof_stats is not None:
        tof_mn, tof_mx, tof_me, tof_sd = tof_stats
        lines.append((f"TOF shape={tuple(tof_hw.shape)} dtype={tof_hw.dtype}  min={tof_mn:.4f} max={tof_mx:.4f} mean={tof_me:.4f} std={tof_sd:.4f}", (0, 0, 0)))
    else:
        lines.append(("TOF missing: predizione non disponibile per questo sample", (0, 0, 180)))

    if ckpt_name is None:
        lines.extend([
            ("Predizioni OFF: passa --ckpt path/al/modello.pt", (0, 0, 180)),
            ("Il pannello destro mostra il grafico vuoto al posto delle matrici.", (0, 0, 0)),
        ])
    elif pred is not None and pred.error is None:
        lines.extend([
            (f"Model: {ckpt_name}", (0, 0, 0)),
            (f"p(gate) raw={pred.raw:.3f}  median={pred.median:.3f}  ema={pred.ema:.3f}  pred@{threshold:.2f}={pred.pred}", (0, 120, 0) if pred.pred == "GATE" else (0, 0, 180)),
        ])
    elif pred is not None:
        lines.extend([
            (f"Model: {ckpt_name}", (0, 0, 0)),
            (f"Predizione fallita: {pred.error}", (0, 0, 180)),
        ])
    else:
        lines.append((f"Model: {ckpt_name}; predizioni in calcolo/non disponibili", (0, 0, 0)))

    lines.extend([
        ("", (0, 0, 0)),
        ("KEYS: s=next | q=prev | ESC=exit", (0, 0, 0)),
    ])

    y = 26
    for text, color in lines:
        if text == "":
            y += line_h // 2
            continue
        cv2.putText(info, text, (10, y), font, font_scale, color, thickness, cv2.LINE_AA)
        y += line_h

    if plot_img.shape[1] != panel_w:
        plot_img = cv2.resize(plot_img, (panel_w, plot_img.shape[0]), interpolation=cv2.INTER_AREA)

    return stack_v(plot_img, info, bg=245)


def compute_predictions(
    *,
    items: List[Item],
    model,
    device: "torch.device",
    threshold: float,
    median_k: int,
    ema_alpha: float,
) -> List[Prediction]:
    preds: List[Prediction] = []
    med_filter = MedianProbabilityFilter(window_size=int(median_k))
    ema_filter = EMAProbabilityFilter(alpha=float(ema_alpha))

    n = len(items)
    for i, it in enumerate(items, 1):
        try:
            if it.tof_path is None:
                raise RuntimeError("TOF mancante")

            cam = np.load(it.cam_path, allow_pickle=False)
            tof = np.load(it.tof_path, allow_pickle=False)
            cam_hw = squeeze_to_hw(cam, name="CAMERA")
            tof_hw = squeeze_to_hw(tof, name="TOF")

            p_raw = infer_gate_probability(model, cam_hw, tof_hw, device=device)
            p_med = med_filter.update(p_raw)
            p_ema = ema_filter.update(p_med)
            pred = "GATE" if p_ema >= float(threshold) else "NO_GATE"
            preds.append(Prediction(raw=p_raw, median=p_med, ema=p_ema, pred=pred))

        except Exception as e:
            # Mantiene allineamento idx -> prediction anche se un sample fallisce.
            last = preds[-1].ema if preds else 0.0
            preds.append(Prediction(raw=last, median=last, ema=last, pred="ERR", error=str(e)))

        if (i % 50) == 0 or i == n:
            print(f"[predictions] {i}/{n}", end="\r")

    print()
    return preds


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Root dataset split o collision run/collection")
    ap.add_argument("--split", default="all", choices=["all", "training", "validation", "test", "train"])
    ap.add_argument("--cls", default="all", choices=["all", "gate", "no_gate"])
    ap.add_argument("--zoom", type=int, default=3, help="Zoom immagini default 3")
    ap.add_argument("--tof_colormap", action="store_true", help="Applica colormap solo visuale alla TOF dopo mapping globale.")

    # Predizioni / grafico
    ap.add_argument("--ckpt", type=str, default=None, help="Checkpoint GateClassifier .pt/.pth per calcolare p(gate)")
    ap.add_argument("--deterministic", action="store_true", help="Modalità torch deterministica se possibile")
    ap.add_argument("--thr", type=float, default=0.5, help="Soglia predizione GATE default 0.5")
    ap.add_argument("--median_k", type=int, default=11, help="Filtro median come opencv-viewer default 3")
    ap.add_argument("--ema_percent", type=float, default=100.0, help="EMA percent come opencv-viewer default 35")
    ap.add_argument("--plot_w", type=int, default=820)
    ap.add_argument("--plot_h", type=int, default=360)
    ap.add_argument("--plot_history_n", type=int, default=250, help="Numero sample visibili nella finestra del grafico")
    ap.add_argument("--plot_value", choices=["raw", "median", "ema"], default="ema", help="Linea da mostrare nel grafico")
    ap.add_argument("--t0", type=int, default=0)
    ap.add_argument("--save_dir", type=str, default=str(MILKV_DIR / "training_quantization" / "retraining_data" / "retraining21"))

    args = ap.parse_args()


    save_path = Path(args.save_dir)
    save_path.mkdir(exist_ok=True, parents=True)
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Root non trovato: {root}")

    if int(args.median_k) <= 0:
        raise ValueError("--median_k deve essere >= 1")

    if int(args.median_k) % 2 == 0:
        raise ValueError("--median_k dovrebbe essere dispari es. 1, 3, 5, 7")

    if float(args.ema_percent) <= 0.0 or float(args.ema_percent) > 100.0:
        raise ValueError("--ema_percent deve essere nel range (0, 100]")

    items = collect_items(root, args.split, args.cls)
    if not items:
        raise RuntimeError(
            f"Nessun file trovato sotto {root}.\n"
            "Supporto: dataset split training/validation/test oppure run con camera_images/tof_distance_array."
        )

    zoom = max(1, int(args.zoom))

    # Range globali auto-calcolati PRIMA della visualizzazione.
    (cam_vmin, cam_vmax), (tof_vmin, tof_vmax) = compute_global_ranges(items)

    print("----------------------------------------------------------------")
    print("[PLAYER RAW + PREDICTIONS]")
    print(f"  root   = {root}")
    print(f"  items  = {len(items)}")
    print("  mapping display = lineare su range GLOBALI calcolati una volta")
    print(f"  CAMERA global min/max = {cam_vmin:.8f} / {cam_vmax:.8f}")
    print(f"  TOF    global min/max = {tof_vmin:.8f} / {tof_vmax:.8f}")
    print("  pannello destro = grafico predizioni, niente matrici RAW")
    print("----------------------------------------------------------------")

    model = None
    device = None
    ckpt_name: Optional[str] = None
    predictions: List[Prediction] = []

    if args.ckpt is not None:
        ckpt_path = Path(args.ckpt).expanduser().resolve()
        if not ckpt_path.exists():
            raise FileNotFoundError(f"Checkpoint non trovato: {ckpt_path}")

        device = robust_set_device(deterministic=bool(args.deterministic))
        print(f"[INFO] Using device: {device}")
        print(f"[INFO] Loading checkpoint: {ckpt_path}")
        model = load_gate_model(str(ckpt_path), device)
        ckpt_name = ckpt_path.name

        predictions = compute_predictions(
            items=items,
            model=model,
            device=device,
            threshold=float(args.thr),
            median_k=int(args.median_k),
            ema_alpha=float(args.ema_percent) / 100.0,
        )
    else:
        print("[WARN] --ckpt non passato: il grafico predizioni sarà vuoto.")

    plotter = DatasetProbabilityPlot(
        width=int(args.plot_w),
        height=int(args.plot_h),
        history_n=int(args.plot_history_n),
        t0 = args.t0,
        title=(
            f"p(gate) vs time (median k={args.median_k})"
            if ckpt_name is not None
            else "p(gate) vs sample"
        ),
    )

    idx = 0
    win = "Dataset Player RAW + predictions (s=next, q=prev, ESC=exit)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while True:
        it = items[idx]

        # ------- LOAD CAMERA RAW -------
        cam = np.load(it.cam_path, allow_pickle=False)
        cam_hw = squeeze_to_hw(cam, name="CAMERA")
        cam_stats = stats(cam_hw)

        cam_u8 = map_float_to_u8(cam_hw, cam_vmin, cam_vmax)
        cam_bgr = cv2.cvtColor(cam_u8, cv2.COLOR_GRAY2BGR)
        cam_bgr = cv2.resize(
            cam_bgr,
            (cam_bgr.shape[1] * zoom, cam_bgr.shape[0] * zoom),
            interpolation=cv2.INTER_NEAREST,
        )

        # ------- LOAD TOF RAW -------
        if it.tof_path is not None:
            tof = np.load(it.tof_path, allow_pickle=False)
            tof_hw = squeeze_to_hw(tof, name="TOF")
            tof_stats = stats(tof_hw)

            tof_u8 = map_float_to_u8(tof_hw, tof_vmin, tof_vmax)
            if args.tof_colormap:
                tof_bgr = cv2.applyColorMap(tof_u8, cv2.COLORMAP_TURBO)
            else:
                tof_bgr = cv2.cvtColor(tof_u8, cv2.COLOR_GRAY2BGR)

            tof_bgr = cv2.resize(
                tof_bgr,
                (cam_bgr.shape[1], cam_bgr.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        else:
            tof_hw = None
            tof_stats = None
            tof_bgr = np.full((21 * zoom, 21 * zoom, 3), 220, dtype=np.uint8)
            cv2.putText(tof_bgr, "TOF MISSING", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)

        current_pred = predictions[idx] if 0 <= idx < len(predictions) else None
        plot_img = plotter.render(
            predictions=predictions,
            current_idx=idx,
            threshold=float(args.thr),
            line_kind=str(args.plot_value),
        )

        right = render_prediction_side_panel(
            plot_img=plot_img,
            item=it,
            idx=idx,
            total=len(items),
            cam_hw=cam_hw,
            tof_hw=tof_hw,
            cam_stats=cam_stats,
            tof_stats=tof_stats,
            pred=current_pred,
            ckpt_name=ckpt_name,
            threshold=float(args.thr),
            panel_w=int(args.plot_w),
        )

        header = f"frame[{idx + 1}] file={it.cam_path.name}"
        cv2.putText(cam_bgr, header, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
        left = stack_h(cam_bgr, tof_bgr)
        frame = stack_v(left, right)

        cv2.imshow(win, frame)
        key = cv2.waitKey(0) & 0xFF

        if key == 27:
            break
        if key in (ord("s"), ord("S")):
            idx = min(idx + 1, len(items) - 1)
        elif key in (ord("q"), ord("Q")):
            idx = max(idx - 1, 0)
        elif key == ord('p'):
            base_name = f"{root.name}_crash"
            save_as_pdf(left, save_path / f"{base_name}_frames.pdf")
            save_as_pdf(plot_img, save_path / f"{base_name}_plot.pdf")


    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
