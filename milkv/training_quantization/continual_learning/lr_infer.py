from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

import numpy as np
import torch

try:
    from .lr_data import list_pairs_under, list_pairs_gate_no_gate
    from .lr_utils import sort_numeric_then_lex
except ImportError:
    from lr_data import list_pairs_under, list_pairs_gate_no_gate
    from lr_utils import sort_numeric_then_lex


IMG_H, IMG_W = 168, 168
TOF_H, TOF_W = 21, 21


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default) if obj is not None else default


def _as_hw(arr: np.ndarray, *, name: str) -> np.ndarray:
    a = np.asarray(arr)
    if a.ndim == 2:
        return a
    if a.ndim == 3 and a.shape[0] == 1:
        return a[0]
    if a.ndim == 3 and a.shape[-1] == 1:
        return a[..., 0]
    raise ValueError(f"{name}: shape non supportata {a.shape}. Atteso (H,W) o (1,H,W) o (H,W,1).")


def _to_tensor_1hw(arr: np.ndarray, *, exp_h: int, exp_w: int, name: str) -> torch.Tensor:
    hw = _as_hw(arr, name=name)
    if hw.shape != (exp_h, exp_w):
        raise ValueError(f"{name}: shape {hw.shape} != attesa {(exp_h, exp_w)}.")
    hw = hw.astype(np.float32, copy=False)
    return torch.from_numpy(hw).unsqueeze(0)


@torch.no_grad()
def infer_probs(
    model,
    pairs: List[Tuple[str, str]],
    cfg_like: Any,
    device: torch.device,
    batch_size: int | None = None,
) -> np.ndarray:
    bs = int(batch_size if batch_size is not None else _get_attr(cfg_like, "batch_size", 128))

    probs_chunks: List[np.ndarray] = []
    buf_i: List[torch.Tensor] = []
    buf_t: List[torch.Tensor] = []

    model.eval()
    N = len(pairs)

    for i, (ip, tp) in enumerate(pairs, 1):
        img = np.load(ip, allow_pickle=False)
        tof = np.load(tp, allow_pickle=False)

        bi = _to_tensor_1hw(img, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA")
        bt = _to_tensor_1hw(tof, exp_h=TOF_H, exp_w=TOF_W, name="TOF")

        buf_i.append(bi)
        buf_t.append(bt)

        if len(buf_i) == bs or i == N:
            BI = torch.stack(buf_i, 0).to(device, dtype=torch.float32)
            BT = torch.stack(buf_t, 0).to(device, dtype=torch.float32)
            p = model(BI, BT).view(-1).detach().cpu().numpy()
            probs_chunks.append(p)
            buf_i, buf_t = [], []

    return np.concatenate(probs_chunks, axis=0) if probs_chunks else np.empty((0,), np.float32)


@torch.no_grad()
def collision_stems_probs_labels(
    model,
    root: str | Path,
    cfg_like: Any,
    device: torch.device,
    batch_size: int | None = None,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    root = Path(root)
    img_dir = root / "camera_images"
    tof_dir = root / "tof_distance_array"

    stems: list[str] = []
    for f in sort_numeric_then_lex(img_dir.glob("*.npy")):
        s = f.stem
        if (tof_dir / f"{s}.npy").exists():
            stems.append(s)

    if not stems:
        return [], np.empty((0,), np.float32), np.empty((0,), np.int32)

    bs = int(batch_size if batch_size is not None else _get_attr(cfg_like, "batch_size", 128))

    probs_chunks: list[torch.Tensor] = []
    buf_i: list[torch.Tensor] = []
    buf_t: list[torch.Tensor] = []

    model.eval()
    N = len(stems)

    for i, s in enumerate(stems, 1):
        img_np = np.load(img_dir / f"{s}.npy", allow_pickle=False)
        tof_np = np.load(tof_dir / f"{s}.npy", allow_pickle=False)

        bi = _to_tensor_1hw(img_np, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA")
        bt = _to_tensor_1hw(tof_np, exp_h=TOF_H, exp_w=TOF_W, name="TOF")

        buf_i.append(bi)
        buf_t.append(bt)

        if len(buf_i) == bs or i == N:
            BI = torch.stack(buf_i, 0).to(device, dtype=torch.float32)
            BT = torch.stack(buf_t, 0).to(device, dtype=torch.float32)
            P = model(BI, BT).view(-1).detach().cpu()
            probs_chunks.append(P)
            buf_i, buf_t = [], []

    probs_t = torch.cat(probs_chunks, dim=0) if probs_chunks else torch.empty((0,), dtype=torch.float32)
    probs_np = probs_t.numpy().astype(np.float32, copy=False)
    labels_np = np.zeros_like(probs_np, dtype=np.int32)

    return stems, probs_np, labels_np


@torch.no_grad()
def collect_validation_probs_labels(
    model,
    cfg_like: Any,
    device: torch.device,
    batch_size: int | None = None,
):
    dlpc = Path(str(_get_attr(cfg_like, "data_loading_path_classification", ""))).resolve()
    val_root = dlpc / "validation"

    gate_pairs = list_pairs_under(val_root / "gate")
    ng_pairs = list_pairs_under(val_root / "no_gate")

    pg = infer_probs(model, gate_pairs, cfg_like, device, batch_size=batch_size)
    pn = infer_probs(model, ng_pairs, cfg_like, device, batch_size=batch_size)

    if (pg.size + pn.size) == 0:
        return np.empty((0,), np.float32), np.empty((0,), np.int32)

    probs = np.concatenate([pg, pn], axis=0)
    labels = np.concatenate([np.ones_like(pg, dtype=np.int32), np.zeros_like(pn, dtype=np.int32)], axis=0)
    return probs, labels


@torch.no_grad()
def collect_probs_labels_from_root(
    model,
    root: Path,
    cfg_like: Any,
    device: torch.device,
    batch_size: int | None = None,
):
    pairs_all = list_pairs_gate_no_gate(Path(root))
    if not pairs_all:
        return np.empty((0,), np.float32), np.empty((0,), np.int64)

    bs = int(batch_size if batch_size is not None else _get_attr(cfg_like, "batch_size", 128))

    probs_chunks: list[torch.Tensor] = []
    labels_list: list[int] = []

    model.eval()
    buf_i: list[torch.Tensor] = []
    buf_t: list[torch.Tensor] = []
    buf_y: list[int] = []
    N = len(pairs_all)

    for i, (ip, tp, y) in enumerate(pairs_all, 1):
        img_np = np.load(ip, allow_pickle=False)
        tof_np = np.load(tp, allow_pickle=False)

        bi = _to_tensor_1hw(img_np, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA")
        bt = _to_tensor_1hw(tof_np, exp_h=TOF_H, exp_w=TOF_W, name="TOF")

        buf_i.append(bi)
        buf_t.append(bt)
        buf_y.append(int(y))

        if len(buf_i) == bs or i == N:
            BI = torch.stack(buf_i, 0).to(device, dtype=torch.float32)
            BT = torch.stack(buf_t, 0).to(device, dtype=torch.float32)
            P = model(BI, BT).view(-1).detach().cpu()
            probs_chunks.append(P)
            labels_list.extend(buf_y)
            buf_i, buf_t, buf_y = [], [], []

    probs_t = torch.cat(probs_chunks, dim=0) if probs_chunks else torch.empty((0,), dtype=torch.float32)
    labels_t = torch.tensor(labels_list, dtype=torch.int64)
    return probs_t.numpy().astype(np.float32, copy=False), labels_t.numpy().astype(np.int64, copy=False)
