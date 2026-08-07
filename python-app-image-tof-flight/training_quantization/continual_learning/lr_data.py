from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset

try:
    from .lr_utils import sort_numeric_then_lex
except ImportError:
    from lr_utils import sort_numeric_then_lex

try:
    from .samples import GateSample, NoGateSample
except ImportError:
    from samples import GateSample, NoGateSample


# Expected shapes for the model
IMG_H, IMG_W = 168, 168
TOF_H, TOF_W = 21, 21


def _as_hw(arr: np.ndarray, *, name: str) -> np.ndarray:
    """
    Accepts ONLY:
      - (H, W)
      - (1, H, W)
      - (H, W, 1)
    Returns a 2D view (H, W) WITHOUT changing values.
    """
    a = np.asarray(arr)

    if a.ndim == 2:
        return a
    if a.ndim == 3 and a.shape[0] == 1:
        return a[0]
    if a.ndim == 3 and a.shape[-1] == 1:
        return a[..., 0]

    raise ValueError(f"{name}: unsupported shape {a.shape}. Expected (H,W) or (1,H,W) or (H,W,1).")


def _to_tensor_1hw(arr: np.ndarray, *, exp_h: int, exp_w: int, name: str) -> torch.Tensor:
    """
    Converts to torch.Tensor [1, H, W] float32 WITHOUT modifying values.
    Performs ONLY shape checks.
    """
    hw = _as_hw(arr, name=name)

    if hw.shape != (exp_h, exp_w):
        raise ValueError(f"{name}: shape {hw.shape} != expected {(exp_h, exp_w)}. Data is not 'ready'.")

    hw = hw.astype(np.float32, copy=False)
    return torch.from_numpy(hw).unsqueeze(0)


def list_pairs_under(root: Path) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    root = Path(root)
    for run_dir in sort_numeric_then_lex(root.glob("*")):
        if not run_dir.is_dir():
            continue
        img_dir = run_dir / "camera_images"
        tof_dir = run_dir / "tof_distance_array"
        if not (img_dir.is_dir() and tof_dir.is_dir()):
            continue
        for img in sort_numeric_then_lex(img_dir.glob("*.npy")):
            tof = tof_dir / f"{img.stem}.npy"
            if tof.exists():
                pairs.append((str(img), str(tof)))
    return pairs


def list_pairs_recursive(root: Path) -> List[Tuple[str, str]]:
    root = Path(root)
    triples: list[tuple[str, Path, Path]] = []
    for cam in root.rglob("camera_images/*.npy"):
        tof = cam.parent.parent / "tof_distance_array" / cam.name
        if tof.exists():
            rel = cam.relative_to(root).as_posix()
            triples.append((rel, cam, tof))
    triples.sort(key=lambda t: t[0])
    return [(str(c), str(t)) for _, c, t in triples]


def list_pairs_gate_no_gate(root: Path) -> List[Tuple[str, str, int]]:
    root = Path(root)
    pairs: list[tuple[str, str, int]] = []
    gate_dir = root / "gate"
    nog_dir = root / "no_gate"

    if gate_dir.exists():
        g = list_pairs_under(gate_dir)
        if not g:
            g = list_pairs_recursive(gate_dir)
        pairs += [(ip, tp, 1) for (ip, tp) in g]

    if nog_dir.exists():
        n = list_pairs_under(nog_dir)
        if not n:
            n = list_pairs_recursive(nog_dir)
        pairs += [(ip, tp, 0) for (ip, tp) in n]

    return pairs


def list_samples_gate_no_gate(root: Path) -> Tuple[List[GateSample], List[NoGateSample]]:
    root = Path(root)
    gate_dir = root / "gate"
    nog_dir = root / "no_gate"

    gates: List[GateSample] = []
    nogs: List[NoGateSample] = []

    if gate_dir.exists():
        g = list_pairs_under(gate_dir)
        if not g:
            g = list_pairs_recursive(gate_dir)
        for (ip, tp) in g:
            gates.append(GateSample(id=len(gates), img_path=ip, tof_path=tp, label=1))

    if nog_dir.exists():
        n = list_pairs_under(nog_dir)
        if not n:
            n = list_pairs_recursive(nog_dir)
        for (ip, tp) in n:
            nogs.append(NoGateSample(id=len(nogs), img_path=ip, tof_path=tp, label=0))

    return gates, nogs


def list_pairs_collision(root: Path) -> List[Tuple[str, str, int]]:
    root = Path(root)
    pairs: list[tuple[str, str, int]] = []

    ci = root / "camera_images"
    td = root / "tof_distance_array"
    if ci.exists() and td.exists():
        for ip in sort_numeric_then_lex(ci.glob("*.npy")):
            tp = td / ip.name
            if tp.exists():
                pairs.append((str(ip), str(tp), 0))
        return pairs

    for cam in root.rglob("camera_images/*.npy"):
        tof = cam.parent.parent / "tof_distance_array" / cam.name
        if tof.exists():
            pairs.append((str(cam), str(tof), 0))
    pairs.sort(key=lambda p: Path(p[0]).stem)
    return pairs


class RawPairsDataset(Dataset):
    """
    RAW Dataset:
      - loads .npy files
      - checks shape
      - returns (img, tof, label)
    No transformations applied.
    """

    def __init__(self, items: list[tuple[str, str, int]]):
        self.items = items

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        ip, tp, y = self.items[idx]
        img = np.load(ip, allow_pickle=False)
        tof = np.load(tp, allow_pickle=False)

        I = _to_tensor_1hw(img, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA")
        T = _to_tensor_1hw(tof, exp_h=TOF_H, exp_w=TOF_W, name="TOF")
        return I, T, torch.tensor(float(y), dtype=torch.float32)