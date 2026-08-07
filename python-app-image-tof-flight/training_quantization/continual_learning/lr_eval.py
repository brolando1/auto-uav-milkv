from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

try:
    from .lr_infer import collision_stems_probs_labels
except ImportError:
    from lr_infer import collision_stems_probs_labels


@torch.no_grad()
def bce_from_probs(probs_np: np.ndarray, labels_np: np.ndarray) -> float:
    if probs_np.size == 0:
        return float("nan")
    p = torch.from_numpy(probs_np.astype(np.float64, copy=False))
    y = torch.from_numpy(labels_np.astype(np.float64, copy=False))
    eps = 1e-12
    p = torch.clamp(p, eps, 1.0 - eps)
    loss = -(y * torch.log(p) + (1.0 - y) * torch.log(1.0 - p)).mean()
    return float(loss.item())


@torch.no_grad()
def confusion_from_probs(probs: np.ndarray, labels: np.ndarray, thr: float):
    if probs.size == 0 or labels.size == 0:
        return 0.0, 0, 0, 0, 0
    p = torch.from_numpy(probs.astype(np.float32, copy=False))
    y = torch.from_numpy(labels.astype(np.int64, copy=False))
    yhat = (p >= float(thr)).to(torch.int64)
    tp = int(((yhat == 1) & (y == 1)).sum().item())
    tn = int(((yhat == 0) & (y == 0)).sum().item())
    fp = int(((yhat == 1) & (y == 0)).sum().item())
    fn = int(((yhat == 0) & (y == 1)).sum().item())
    acc = (tp + tn) / max(1, y.numel())
    return acc, tp, tn, fp, fn


@torch.no_grad()
def eval_collisions_full(
    model,
    root: str | Path,
    cfg_like: Any,
    device: torch.device,
    threshold: float = 0.5,
):
    _, probs_np, labels_np = collision_stems_probs_labels(model, root, cfg_like, device)

    total = int(probs_np.shape[0])
    if total == 0:
        return {"Total": 0, "TN": 0, "FP": 0, "ACC_no_gate": 0.0, "FPR": 0.0}

    p = torch.from_numpy(probs_np.astype(np.float32, copy=False))
    y = torch.from_numpy(labels_np.astype(np.int64, copy=False))
    pred = (p >= float(threshold)).to(torch.int64)

    fp = int(((pred == 1) & (y == 0)).sum().item())
    tn = total - fp
    return {"Total": total, "TN": tn, "FP": fp, "ACC_no_gate": tn / total, "FPR": fp / total}
