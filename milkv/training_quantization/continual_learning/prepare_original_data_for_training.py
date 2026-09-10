#!/usr/bin/env python3
# swarms-drones/training_quantization/continual_learning/prepare_original_data_for_training.py

from __future__ import annotations

"""
File Purpose
============
This script prepares an "original_dataset" to be used later in the continual learning pipeline.

What it does in practice:
1) Reads the config.json
2) Loads the "original" model (latest checkpoint found)
3) Loads candidates from the original dataset (train/gate and train/no_gate) from classification_fixed_root
4) Selects a subset of original samples (K gate and K no_gate) using a strategy (data_selection)
   - optionally uses "ghost" = embedding calculated on frames of the most recent collision
5) Writes a "ready" dataset to disk in out_root:
   - always: manifest.json + meta.json
   - if latents_only=True: saves Z_all.npy + Y_all.npy (latents + labels)
   - if latents_only=False: copies the .npy files into out_root/gate and out_root/no_gate, renumbering them 000000.npy, 000001.npy, ...

Output on disk (out_root)
=========================
Case latents_only=True:
  out_root/
    manifest.json         # item list (with ORIGINAL paths and labels)
    meta.json             # metadata (ckpt used, counts, parameters)
    Z_all.npy             # latents float32 shape [N, ...] depends on the tap
    Y_all.npy             # label float32 shape [N,1]

Case latents_only=False:
  out_root/
    manifest.json         # item list (with COPIED paths in out_root + src_path)
    meta.json
    gate/
      camera_images/000000.npy ...
      tof_distance_array/000000.npy ...
    no_gate/
      camera_images/000000.npy ...
      tof_distance_array/000000.npy ...

Important Note:
- This script does NOT normalize data: it only performs shape checks and dtype conversion.
- "gss_greedy" is special: instead of latents, it uses full-gradient as embedding (very expensive).
"""

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

# -----------------------------------------------------------------------------
# Import with fallback (package vs script)
# -----------------------------------------------------------------------------
try:
    from .compat import set_device, load_model, freeze_encoder_params, extract_latent
    from .lr_utils import find_latest_checkpoint
    from .lr_data import list_samples_gate_no_gate, list_pairs_collision
    from .selection import get_strategy
    from .selection.base import SelectionInput
    from .samples import GateSample, NoGateSample, CollisionSample, BaseSample
    from ..model.gate_classifier_PyTorch_model import GateClassifier
except Exception:
    from compat import set_device, load_model, freeze_encoder_params, extract_latent
    from lr_utils import find_latest_checkpoint
    from lr_data import list_samples_gate_no_gate, list_pairs_collision
    from selection import get_strategy
    from selection.base import SelectionInput
    from samples import GateSample, NoGateSample, CollisionSample, BaseSample
    try:
        from models.gate_classifier_PyTorch_model import GateClassifier  # type: ignore
    except Exception:
        GateClassifier = None  # type: ignore

# -----------------------------------------------------------------------------
# Expected shapes from the model
# -----------------------------------------------------------------------------
IMG_H, IMG_W = 168, 168
TOF_H, TOF_W = 21, 21


# =============================================================================
# Helper: array conversion -> shape (H,W) and torch [1,H,W]
# =============================================================================
def _as_hw(arr: Any, *, name: str) -> np.ndarray:
    """
    Accepts arrays with shapes:
      - (H,W)
      - (1,H,W)
      - (H,W,1)

    ALWAYS returns a 2D view (H,W) without changing values.

    If different shapes are found, raises ValueError: it means the data is not in the expected format.
    """
    a = np.asarray(arr)

    if a.ndim == 2:
        return a
    if a.ndim == 3 and a.shape[0] == 1:
        return a[0]
    if a.ndim == 3 and a.shape[-1] == 1:
        return a[..., 0]

    raise ValueError(f"{name}: unsupported shape {a.shape}. Expected (H,W) or (1,H,W) or (H,W,1).")


def _to_tensor_1hw(arr: Any, *, exp_h: int, exp_w: int, name: str) -> torch.Tensor:
    """
    Converts a numpy array into a float32 torch.Tensor with shape [1,H,W].

    - Checks shape: must be (exp_h, exp_w)
    - Does not normalize (values remain as they are in the .npy)
    """
    hw = _as_hw(arr, name=name)
    if hw.shape != (exp_h, exp_w):
        raise ValueError(f"{name}: shape {hw.shape} != expected {(exp_h, exp_w)}. Data is not 'ready'.")
    hw = hw.astype(np.float32, copy=False)
    return torch.from_numpy(hw).unsqueeze(0)  # -> [1,H,W]


# =============================================================================
# Helper: parsing config
# =============================================================================
def _get_bool(d: Dict[str, Any], key: str, default: bool = False) -> bool:
    """
    Reads a boolean from the config dict, supporting:
      - bool
      - strings like "true/false", "1/0", "yes/no"
      - numbers
    """
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


def _resolve_path(p: Optional[str], base: Path) -> Optional[Path]:
    """
    Resolves a path read from the config:
      - if relative: base / p
      - if absolute: p
      - if None or empty string: None
    """
    if p is None:
        return None
    s = str(p).strip()
    if not s:
        return None
    pp = Path(s)
    return (base / pp).resolve() if not pp.is_absolute() else pp.resolve()


# =============================================================================
# Helper: most recent collision
# =============================================================================
def _find_last_collision_dir(ds_root: Path) -> Optional[Path]:
    """
    Searches inside dataset_training_root for collisione_* directories and returns
    the one with the "highest" suffix (numerical sorting if possible).

    Example:
      collisione_1, collisione_2, collisione_10 -> takes collisione_10

    Returns None if no collisions are found.
    """
    ds_root = ds_root.resolve()
    if not ds_root.exists():
        return None

    dirs = [d for d in ds_root.iterdir() if d.is_dir() and d.name.startswith("collision_")]

    def _key(p: Path):
        last = p.name.split("_")[-1]
        return int(last) if last.isdigit() else last

    dirs.sort(key=_key)
    return dirs[-1] if dirs else None


# =============================================================================
# Helper: latents_only mode = freeze encoder and leave post-tap trainable
# =============================================================================
def _prepare_model_for_latents_only(model: torch.nn.Module, tap: str) -> None:
    """
    Sets requires_grad so that:
      - the encoder (before the tap) is frozen
      - blocks AFTER the tap remain trainable

    supported taps:
      - post_merge -> train combined_block_1 + combined_block_2 + fully_connected
      - post_comb1 -> train combined_block_2 + fully_connected
      - post_comb2 -> train fully_connected
      - pre_fc     -> train fully_connected (latents already flattened)
    """
    freeze_encoder_params(model, True)

    for name, p in model.named_parameters():
        enable = False
        if tap == "post_merge":
            enable = (
                name.startswith("combined_block_1")
                or name.startswith("combined_block_2")
                or name.startswith("fully_connected")
            )
        elif tap == "post_comb1":
            enable = name.startswith("combined_block_2") or name.startswith("fully_connected")
        elif tap in ("post_comb2", "pre_fc"):
            enable = name.startswith("fully_connected")
        else:
            raise ValueError(f"Unsupported latent_tap: {tap}")

        if enable:
            p.requires_grad = True


# =============================================================================
# Inference: probability P (needed for strategies using "probs")
# =============================================================================
@torch.no_grad()
def _infer_probs(
    *,
    model: torch.nn.Module,
    pairs: List[Tuple[str, str]],
    device: torch.device,
    batch_size: int,
) -> np.ndarray:
    """
    Given a list of pairs (img_path, tof_path):
      - loads the .npy files
      - performs a full model forward pass
      - returns probabilities (sigmoid) as numpy float32 shape [N]

    Output:
      np.ndarray float32 of shape (N,)
    """
    if not pairs:
        return np.empty((0,), np.float32)

    bs = max(1, int(batch_size))
    model.eval()

    out_chunks: List[torch.Tensor] = []
    buf_i: List[torch.Tensor] = []
    buf_t: List[torch.Tensor] = []

    for i, (ip, tp) in enumerate(pairs, 1):
        img_np = np.load(ip, allow_pickle=False)
        tof_np = np.load(tp, allow_pickle=False)

        bi = _to_tensor_1hw(img_np, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA")  # [1,168,168]
        bt = _to_tensor_1hw(tof_np, exp_h=TOF_H, exp_w=TOF_W, name="TOF")     # [1,21,21]

        buf_i.append(bi)
        buf_t.append(bt)

        # When we reach batch_size or run out of data, run inference on the batch
        if len(buf_i) == bs or i == len(pairs):
            BI = torch.stack(buf_i, 0).to(device, dtype=torch.float32)  # [B,1,168,168]
            BT = torch.stack(buf_t, 0).to(device, dtype=torch.float32)  # [B,1,21,21]
            P = model(BI, BT).view(-1).detach().cpu()  # -> [B]
            out_chunks.append(P)
            buf_i, buf_t = [], []

    P_t = torch.cat(out_chunks, dim=0) if out_chunks else torch.empty((0,))
    return P_t.numpy().astype(np.float32, copy=False)


# =============================================================================
# Inference: latents Z at the chosen tap (needed for strategies using "latent")
# =============================================================================
@torch.no_grad()
def _infer_latents(
    *,
    model: torch.nn.Module,
    samples: List[BaseSample],
    device: torch.device,
    batch_size: int,
    tap: str,
) -> np.ndarray:
    """
    Extracts the internal embedding (latent) for each sample at the 'tap' point.

    tap (see compat.extract_latent):
      - post_merge/post_comb1/post_comb2 -> Z shape [N, C, H, W]
      - pre_fc                           -> Z shape [N, D]

    Output:
      np.ndarray float32 with shape [N, ...]
    """
    if not samples:
        return np.empty((0, 1), np.float32)

    bs = max(1, int(batch_size))
    model.eval()

    chunks: List[np.ndarray] = []
    for start in range(0, len(samples), bs):
        end = min(len(samples), start + bs)
        chunk = samples[start:end]

        imgs: List[torch.Tensor] = []
        tofs: List[torch.Tensor] = []

        for s in chunk:
            img_np = np.load(s.img_path, allow_pickle=False)
            tof_np = np.load(s.tof_path, allow_pickle=False)

            bi = _to_tensor_1hw(img_np, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA")  # [1,168,168]
            bt = _to_tensor_1hw(tof_np, exp_h=TOF_H, exp_w=TOF_W, name="TOF")     # [1,21,21]

            imgs.append(bi)
            tofs.append(bt)

        BI = torch.stack(imgs, 0).to(device, dtype=torch.float32)  # [B,1,168,168]
        BT = torch.stack(tofs, 0).to(device, dtype=torch.float32)  # [B,1,21,21]

        Z = extract_latent(model, BI, BT, tap=tap).detach().cpu().numpy()
        chunks.append(Z.astype(np.float32, copy=False))

    return np.concatenate(chunks, axis=0) if chunks else np.empty((0, 1), np.float32)


# =============================================================================
# FULL GRADIENT: embedding = full gradient d(loss)/d(theta) (very expensive)
# =============================================================================
def _infer_full_grads_slow(
    *,
    model: torch.nn.Module,
    samples: List[BaseSample],
    device: torch.device,
    y_value: float,  # 0.0 no_gate, 1.0 gate
) -> np.ndarray:
    """
    Calculates, for each sample, an "embedding" vector equal to the full gradient:
        g = d( BCE(model(x), y_value) ) / d(theta)
    concatenating all parameter gradients into a single 1D vector.

    For N samples and D parameters:
      Output shape = [N, D]

    NOTES:
    - It is slow: it performs one forward+backward pass for each sample (batch=1).
    - It is only needed for strategies like gss_greedy (which require "importance via gradient" type embeddings).
    """
    if not samples:
        return np.empty((0, 1), np.float32)

    # Force requires_grad=True on all parameters: we want gradients on EVERYTHING.
    for p in model.parameters():
        p.requires_grad_(True)

    # model.eval() to make BN "stable" with batch=1
    model.eval()

    params = [p for p in model.parameters() if p.requires_grad]
    if not params:
        raise RuntimeError("No parameters with requires_grad=True.")

    # Fixed target (1 sample at a time)
    target = torch.full((1, 1), float(y_value), device=device, dtype=torch.float32)

    grads_np: list[np.ndarray] = []

    for s in samples:
        img_np = np.load(s.img_path, allow_pickle=False)
        tof_np = np.load(s.tof_path, allow_pickle=False)

        BI = _to_tensor_1hw(img_np, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA").unsqueeze(0).to(device, dtype=torch.float32)
        BT = _to_tensor_1hw(tof_np, exp_h=TOF_H, exp_w=TOF_W, name="TOF").unsqueeze(0).to(device, dtype=torch.float32)

        model.zero_grad(set_to_none=True)

        out = model(BI, BT)  # [1,1] probability
        loss = F.binary_cross_entropy(out, target, reduction="mean")

        # gradient of loss with respect to all parameters (tuple of tensors)
        g_tuple = torch.autograd.grad(
            loss,
            params,
            retain_graph=False,
            create_graph=False,
            allow_unused=True,  # if some parameter doesn't influence output, g can be None
        )

        # Flatten + concat into a single vector
        flat_parts = []
        for g, p in zip(g_tuple, params):
            if g is None:
                flat_parts.append(torch.zeros_like(p, device="cpu").reshape(-1))
            else:
                flat_parts.append(g.detach().to("cpu", dtype=torch.float32).reshape(-1))

        g_flat = torch.cat(flat_parts, dim=0)  # [D]
        grads_np.append(g_flat.numpy())

    return np.stack(grads_np, axis=0).astype(np.float32, copy=False)


# =============================================================================
# Index selection: wrapper towards the chosen strategy
# =============================================================================
def _select_indices(
    *,
    method: str,
    Y: np.ndarray,
    Z: Optional[np.ndarray],
    P: Optional[np.ndarray],
    K: int,
    thr: float,
    seed: int,
    Z_ghost: Optional[np.ndarray],
    P_ghost: Optional[np.ndarray],
) -> np.ndarray:
    """
    Builds SelectionInput and invokes strat.select(...).

    Fundamental inputs:
      - Y: labels of candidates (shape [N])
      - Z: embedding/latents or full-grad (if strategy requires it)
      - P: model probabilities on candidates (if strategy requires it)
      - K: how many samples to select
      - Z_ghost / P_ghost: embedding/probs of "ghost set" (collision) if enabled

    Output:
      numpy int64 indices of shape [K] (positions in the candidate list)
    """
    strat = get_strategy(method)
    inp = SelectionInput(
        Z=Z if strat.needs_latent else None,
        Y=Y,
        P=P if strat.needs_probs else None,
        K=int(K),
        gate_quota=None,
        threshold=float(thr),
        Z_ghost=Z_ghost,
        P_ghost=P_ghost,
        seed=int(seed),
    )
    return np.asarray(strat.select(inp), dtype=np.int64)


# =============================================================================
# Cache check: avoid regenerating if already ready (unless --force)
# =============================================================================
def _is_original_dataset_ready(out_root: Path, *, latent_only: bool) -> bool:
    """
    "Minimal" cache: if main files exist -> consider it ready.

    Warning: there is no fingerprint. If you change:
      - checkpoint,
      - selection parameters,
      - most recent collision,
    you must pass --force to truly regenerate.
    """
    if not (out_root / "manifest.json").exists():
        return False
    if not (out_root / "meta.json").exists():
        return False

    if latent_only:
        return (out_root / "Z_all.npy").exists() and (out_root / "Y_all.npy").exists()

    gate_ok = (out_root / "gate" / "camera_images").exists() and (out_root / "gate" / "tof_distance_array").exists()
    nog_ok = (out_root / "no_gate" / "camera_images").exists() and (out_root / "no_gate" / "tof_distance_array").exists()
    return gate_ok and nog_ok


# =============================================================================
# MAIN FUNCTION: creates original_dataset in out_root
# =============================================================================
def prepare_original_dataset_from_config(
    cfg_path: str | Path,
    GateClassifierCls,
    *,
    force: bool = False,
) -> Path:
    """
    Reads config.json and produces an "original_dataset" in out_root.

    Return:
      Path(out_root) where the following were written:
        - manifest.json
        - meta.json
        - (latents_only) Z_all.npy, Y_all.npy
        - (raw) copies of .npy in gate/ and no_gate/
    """
    # ---------- load config ----------
    cfg_path = Path(cfg_path).resolve()
    base = cfg_path.parent # .../continual_learning
    cfg: Dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))

    # ---------- resolve required paths ----------
    classification_fixed_root = _resolve_path(cfg.get("classification_fixed_root"), base)
    if classification_fixed_root is None:
        raise ValueError("config.json: 'classification_fixed_root' missing.")

    dataset_training_root = _resolve_path(cfg.get("dataset_training_root", cfg.get("dataset_training_out_root")), base)
    if dataset_training_root is None:
        raise ValueError("config.json: 'dataset_training_root' missing.")

    model_original_root = _resolve_path(cfg.get("model_original"), base)
    if model_original_root is None:
        raise ValueError("config.json: 'model_original' missing.")

    # ---------- output ----------
    out_root = _resolve_path(cfg.get("original_dataset_root"), base) or (base / "original_dataset").resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # ---------- selection/dataset parameters ----------
    latent_only = _get_bool(cfg, "latents_only", True)                  # if True saves Z_all/Y_all instead of copying .npy
    latent_tap = str(cfg.get("latent_tap", "pre_fc")).strip()           # network point where latents are taken
    method = str(cfg.get("data_selection", "random")).strip().lower()   # sample selection strategy
    use_ghost = _get_bool(cfg, "use_ghost_for_selection", False)        # use collision as ghost set
    seed = int(cfg.get("seed", 42))
    deterministic = _get_bool(cfg, "deterministic", True)

    thr = float(cfg.get("threshold", 0.5))
    bs = int(cfg.get("batch_size", 128))
    n_original_gate_to_select = int(cfg.get("n_original_gate_to_select", 0))
    n_original_no_gate_to_select = int(cfg.get("n_original_no_gate_to_select", 0))

    # ---------- cache: if already exists and not force, exit ----------
    if not force and _is_original_dataset_ready(out_root, latent_only=latent_only):
        print(f"[prepare_original] already ready: {out_root}")
        return out_root

    # -------------------------------------------------------------------------
    # 1) Find most recent collision (used only as "ghost"/target in selection)
    # -------------------------------------------------------------------------
    last_coll = _find_last_collision_dir(dataset_training_root)
    coll_name = None
    coll_count = 0
    coll_dir_mtime = None
    coll_triples_all: List[Tuple[str, str, int]] = []

    if last_coll is not None:
        coll_name = last_coll.name
        coll_dir_mtime = int(last_coll.stat().st_mtime)
        nog_root = last_coll / "no_gate"

        # list (img_path, tof_path, 0) of all no_gate collision frames
        coll_triples_all = list_pairs_collision(nog_root)
        coll_count = len(coll_triples_all)

        print(f"[prepare_original] collision used for ghost/target = {coll_name}, ALL_count={coll_count}")
    else:
        print("[prepare_original] WARNING: no collision found. ghost effectively disabled.")

    # -------------------------------------------------------------------------
    # 2) Load original model (latest checkpoint) and set device
    # -------------------------------------------------------------------------
    ckpt = find_latest_checkpoint(model_original_root)     # takes the most recent .pt
    print(f"[last checkpoint] {ckpt.name}")
    device = set_device(deterministic=deterministic)
    model = load_model(str(ckpt), device, GateClassifierCls)

    # If latents_only and NOT gss_greedy, freeze encoder for consistency with latents_only training.
    # For gss_greedy DO NOT freeze because gradients are needed on all weights.
    if latent_only and method != "gss_greedy":
        _prepare_model_for_latents_only(model, latent_tap)

    # -------------------------------------------------------------------------
    # 3) Ghost set: embedding calculated on collision frames (optional)
    # -------------------------------------------------------------------------
    Z_ghost = None
    P_ghost = None

    if last_coll is not None and coll_triples_all:
        # Only some strategies use ghost; here we activate it for (kcenter_latent, gss_greedy)
        if use_ghost and method in ("kcenter_latent", "gss_greedy"):
            coll_samples = [
                CollisionSample(id=i, img_path=ip, tof_path=tp, label=0)
                for i, (ip, tp, _) in enumerate(coll_triples_all)
            ]

            # gss_greedy: ghost embedding = full gradient (target 0.0), P_ghost not used
            if method == "gss_greedy":
                Z_ghost = _infer_full_grads_slow(model=model, samples=coll_samples, device=device, y_value=0.0)
                P_ghost = None
            else:
                # kcenter_latent: ghost embedding = latents at tap
                Z_ghost = _infer_latents(model=model, samples=coll_samples, device=device, batch_size=bs, tap=latent_tap)

    # -------------------------------------------------------------------------
    # 4) Load original candidates (train/gate and train/no_gate)
    # -------------------------------------------------------------------------
    train_root = classification_fixed_root / "train"
    gates, nogs = list_samples_gate_no_gate(train_root)
    print(f"[prepare_original] original candidates: gate={len(gates)}, no_gate={len(nogs)}")

    # How many we actually select (clamped to availability)
    if n_original_gate_to_select <= 0 and n_original_no_gate_to_select <= 0:
        K_gate = 0
        K_ng_orig = 0
        print(
            "[prepare_original] WARNING: both n_original_*_to_select <=0 -> "
            "nothing selected, original_dataset will be empty."
        )
    else:
        K_gate = min(len(gates), max(0, n_original_gate_to_select))
        K_ng_orig = min(len(nogs), max(0, n_original_no_gate_to_select))
        print(
            f"[prepare_original] selection requests: "
            f"K_gate={K_gate} (requested={n_original_gate_to_select}), "
            f"K_no_gate={K_ng_orig} (requested={n_original_no_gate_to_select}) "
            f"method={method}"
        )

    # -------------------------------------------------------------------------
    # 5) Select original NO_GATE
    # -------------------------------------------------------------------------
    if K_ng_orig > 0:
        pairs_ng = [(s.img_path, s.tof_path) for s in nogs]
        strat = get_strategy(method)

        # Z_ng = embedding for each candidate no_gate (if strategy requires it)
        if strat.needs_latent:
            if method == "gss_greedy":
                Z_ng = _infer_full_grads_slow(model=model, samples=nogs, device=device, y_value=0.0)
            else:
                Z_ng = _infer_latents(model=model, samples=nogs, device=device, batch_size=bs, tap=latent_tap)
        else:
            Z_ng = None

        # P_ng = model probs on candidates (if strategy requires it)
        P_ng = _infer_probs(model=model, pairs=pairs_ng, device=device, batch_size=bs) if strat.needs_probs else None

        # Labels Y_ng (all 0)
        Y_ng = np.zeros((len(nogs),), np.int64)

        # Selected indices (positions within nogs)
        idx_ng = _select_indices(
            method=method,
            Y=Y_ng,
            Z=Z_ng,
            P=P_ng,
            K=K_ng_orig,
            thr=thr,
            seed=seed + 2000,
            Z_ghost=Z_ghost,
            P_ghost=P_ghost,
        )
        sel_nogs = [nogs[int(i)] for i in idx_ng.tolist()]
    else:
        sel_nogs = []

    # -------------------------------------------------------------------------
    # 6) Select original GATE
    # -------------------------------------------------------------------------
    if K_gate > 0:
        pairs_g = [(s.img_path, s.tof_path) for s in gates]
        strat = get_strategy(method)

        if strat.needs_latent:
            if method == "gss_greedy":
                Z_g = _infer_full_grads_slow(model=model, samples=gates, device=device, y_value=1.0)
            else:
                Z_g = _infer_latents(model=model, samples=gates, device=device, batch_size=bs, tap=latent_tap)
        else:
            Z_g = None

        P_g = _infer_probs(model=model, pairs=pairs_g, device=device, batch_size=bs) if strat.needs_probs else None

        Y_g = np.ones((len(gates),), np.int64)

        idx_g = _select_indices(
            method=method,
            Y=Y_g,
            Z=Z_g,
            P=P_g,
            K=K_gate,
            thr=thr,
            seed=seed + 3000,
            Z_ghost=Z_ghost,
            P_ghost=P_ghost,
        )
        sel_gates = [gates[int(i)] for i in idx_g.tolist()]
    else:
        sel_gates = []

    # -------------------------------------------------------------------------
    # 7) Build final list of selected samples (GateSample + NoGateSample)
    # -------------------------------------------------------------------------
    selected_items: List[BaseSample] = []

    # gates first, then no_gates (order isn't critical: training shuffles anyway)
    selected_items.extend(
        [GateSample(id=i, img_path=s.img_path, tof_path=s.tof_path, label=1) for i, s in enumerate(sel_gates)]
    )
    base_id = len(selected_items)
    selected_items.extend(
        [NoGateSample(id=base_id + i, img_path=s.img_path, tof_path=s.tof_path, label=0) for i, s in enumerate(sel_nogs)]
    )

    # -------------------------------------------------------------------------
    # 8) Clean previous output (if exists) before rewriting
    # -------------------------------------------------------------------------
    for p in [out_root / "gate", out_root / "no_gate"]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    for p in ["Z_all.npy", "Y_all.npy", "manifest.json", "meta.json"]:
        fp = out_root / p
        if fp.exists():
            fp.unlink()

    # -------------------------------------------------------------------------
    # 9) Manifest: describes items (initially points to ORIGINAL paths)
    #    If latents_only=False, it will be updated with COPIED paths in out_root.
    # -------------------------------------------------------------------------
    manifest: Dict[str, Any] = {
        "items": [
            {
                "img_path": s.img_path,
                "tof_path": s.tof_path,
                "label": int(s.label),
                "kind": "gate" if int(s.label) == 1 else "no_gate",
                "stem": Path(s.img_path).stem,
            }
            for s in selected_items
        ]
    }

    # -------------------------------------------------------------------------
    # 10) Save dataset: RAW (.npy copies) or LATENTS (Z_all/Y_all)
    # -------------------------------------------------------------------------
    if not latent_only:
        # RAW mode: copy files to out_root in gate/no_gate subfolders with renumbering
        for kind in ("gate", "no_gate"):
            (out_root / kind / "camera_images").mkdir(parents=True, exist_ok=True)
            (out_root / kind / "tof_distance_array").mkdir(parents=True, exist_ok=True)

        new_items = []
        for i, s in enumerate(selected_items):
            kind = "gate" if int(s.label) == 1 else "no_gate"
            stem = f"{i:06d}"

            dst_img = out_root / kind / "camera_images" / f"{stem}.npy"
            dst_tof = out_root / kind / "tof_distance_array" / f"{stem}.npy"

            # Physical copy to disk
            shutil.copy2(s.img_path, dst_img)
            shutil.copy2(s.tof_path, dst_tof)

            # Update manifest with new paths + src path
            new_items.append(
                {
                    "img_path": str(dst_img),
                    "tof_path": str(dst_tof),
                    "label": int(s.label),
                    "kind": kind,
                    "stem": stem,
                    "src_img_path": s.img_path,
                    "src_tof_path": s.tof_path,
                }
            )

        manifest["items"] = new_items

    else:
        # LATENTS mode: calculate Z_all for selected_items and save Z_all.npy / Y_all.npy
        Z_all = _infer_latents(model=model, samples=selected_items, device=device, batch_size=bs, tap=latent_tap)
        Y_all = np.asarray([int(s.label) for s in selected_items], np.float32).reshape(-1, 1)

        np.save(out_root / "Z_all.npy", Z_all.astype(np.float32, copy=False))
        np.save(out_root / "Y_all.npy", Y_all.astype(np.float32, copy=False))

    # -------------------------------------------------------------------------
    # 11) Write manifest.json and meta.json
    # -------------------------------------------------------------------------
    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    meta = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "latent_only": bool(latent_only),
        "latent_tap": latent_tap,
        "data_selection": method,
        "use_ghost_for_selection": bool(use_ghost),
        "threshold": float(thr),
        "batch_size": int(bs),
        # info on "last" collision (tracks what guided ghost/target)
        "collision_last_name": coll_name,
        "collision_last_count": int(coll_count),
        "collision_last_dir_mtime": coll_dir_mtime,
        # checkpoint used for latents/probs/grad inference
        "ckpt": str(ckpt),
        # final counts of selected samples
        "counts": {
            "gate": int(sum(1 for s in selected_items if int(s.label) == 1)),
            "no_gate": int(sum(1 for s in selected_items if int(s.label) == 0)),
            "total": int(len(selected_items)),
        },
        "note": "Minimal cache: if you change config/ckpt/collision you must rerun with --force.",
    }
    (out_root / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"[prepare_original] wrote original_dataset in: {out_root}")
    return out_root


# =============================================================================
# CLI
# =============================================================================
def main() -> None:
    """
    Usage:
      python prepare_original_data_for_training.py --cfg path/to/config.json [--force]

    --force:
      regenerates even if out_root appears ready (minimal cache).
    """
    ap = argparse.ArgumentParser(description="Prepares original_dataset (raw or latents) for training.")
    ap.add_argument("--cfg", required=True, help="Path config.json")
    ap.add_argument("--force", action="store_true", help="Regenerate even if already present.")
    args = ap.parse_args()

    if GateClassifier is None:
        raise RuntimeError("GateClassifier not importable. Run from correct package or fix paths.")

    prepare_original_dataset_from_config(args.cfg, GateClassifier, force=bool(args.force))


if __name__ == "__main__":
    main()