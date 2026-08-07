#!/usr/bin/env python3
# swarms-drones/training_quantization/continual_learning/setup_from_config.py

from __future__ import annotations

"""
Purpose of the file
===================
This module builds and initializes the pipeline "state" (DataConfig) starting from config.json.

In practice, it performs:
1) load_data_config(): reads config.json and creates a "static" DataConfig (parameters, paths, flags).
2) setup():
   - sets seed and device (CPU/GPU + determinism)
   - loads the original model (latest .pt checkpoint)
   - (if latents_only) freezes model parts before the tap and leaves post-tap parts trainable
   - loads the pre-prepared original_dataset from disk (manifest/meta and, if latents_only, also Z_all/Y_all)
   - loads the validation dataset (if enabled) and, if latents_only, calculates latents on the fly
   - creates loss (BCELoss) and optimizer (Adam) with ONLY trainable parameters

Main Output
===========
The setup(...) function returns a DataConfig object ready for:
- prepare_collisions(data_config)
- prepare_training(data_config)
- run_training(data_config)

Key fields populated by setup():
- data_config.device
- data_config.original_model_ckpt
- data_config.original_model
- data_config.original_buffer.items (+ original_buffer.latent_buffer if latents_only)
- data_config.validation_buffer.items (+ validation_buffer.latent_buffer if latents_only and validation=True)
- data_config.bce_loss
- data_config.optimizer
"""

# -----------------------------------------------------------------------------
# Import "side-effect": sets safe environment variables (if available)
# -----------------------------------------------------------------------------
try:
    from . import env_safety
except Exception:
    try:
        import env_safety
    except Exception:
        pass

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch

# -----------------------------------------------------------------------------
# Import with fallback (package vs. script execution)
# -----------------------------------------------------------------------------
try:
    from .buffer import LatentBuffer
    from .compat import set_device, load_model, freeze_encoder_params
    from .lr_utils import find_latest_checkpoint
    from .samples import BaseSample, GateSample, NoGateSample
    from .state import DataConfig
    from .lr_data import list_pairs_gate_no_gate
except Exception:
    from .buffer import LatentBuffer
    from .compat import set_device, load_model, freeze_encoder_params
    from lr_utils import find_latest_checkpoint
    from samples import BaseSample, GateSample, NoGateSample
    from state import DataConfig
    from lr_data import list_pairs_gate_no_gate


# =============================================================================
# Seed: Reproducibility
# =============================================================================
def set_seeds(seed: int = 42) -> None:
    """
    Sets seeds (Python, NumPy, Torch) to ensure reproducibility for:
    - shuffling
    - random initializations
    - any stochastic operations

    Note: On GPU, torch.cuda.manual_seed_all is also set.
    (Full determinism is handled in set_device(deterministic=...)).
    """
    import random

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# =============================================================================
# Utility: Path resolution, boolean parsing from config and download datset
# =============================================================================
def _resolve_path(p: Optional[str], base: Path) -> Optional[Path]:
    """
    Converts a config string into an absolute Path.

    - None / empty string -> None
    - relative path -> base / path
    - absolute path -> remains absolute

    Example:
      base=/proj/configs, p="../data" => /proj/data (resolved)
    """
    if p is None:
        return None
    s = str(p).strip()
    if not s:
        return None
    pp = Path(s)
    return (base / pp).resolve() if not pp.is_absolute() else pp.resolve()


def _get_bool(d: Dict[str, Any], key: str, default: bool = False) -> bool:
    """
    Reads a boolean from the config dict, supporting:
      - bool
      - strings ("true/false", "1/0", "yes/no", "on/off")
      - numbers
    """
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


# =============================================================================
# 1) Reading config.json -> "Static" DataConfig
# =============================================================================
def load_data_config(config_json_path: str | Path) -> DataConfig:
    """
    Reads config.json and builds a "static" DataConfig.

    "Static" means:
    - contains parameters, paths, and flags
    - does NOT yet contain runtime objects (device, model, optimizer, loaded buffers, ...)

    IMPORTANT NOTES:
    - This version is "RAW": it does not use mean/std or normalization tags.
    - collision_tail_seconds and collision_fps are NO LONGER read:
        * you can remove them from config.json
        * if they remain, they are ignored
    """
    cfg_path = Path(config_json_path).resolve()
    base = cfg_path.parent
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    # ---- Mandatory Paths ----
    model_original_root = _resolve_path(cfg.get("model_original"), base)
    if model_original_root is None:
        raise ValueError("Missing 'model_original' in config.json.")

    ds_training_root = _resolve_path(cfg.get("dataset_training_root", cfg.get("dataset_training_out_root")), base)
    if ds_training_root is None:
        raise ValueError("Missing 'dataset_training_root' (or dataset_training_out_root) in config.json.")

    # outdir can be None: if None, a fallback will be used during the saving phase
    outdir = _resolve_path(cfg.get("outdir"), base)

    # where the already prepared original_dataset is located (manifest/meta + optionally Z_all/Y_all)
    original_dataset_root = _resolve_path(cfg.get("original_dataset_root"), base) or (base / "original_dataset").resolve()

    # ---- Training Parameters ----
    epochs = int(cfg.get("epochs", 5))
    lr = float(cfg.get("lr", 5e-5))
    patience = int(cfg.get("patience", 0))
    weight_decay = float(cfg.get("weight_decay", 0.0))
    batch_size = int(cfg.get("batch_size", 128))

    deterministic = _get_bool(cfg, "deterministic", False)
    seed = int(cfg.get("seed", 42))

    # ---- Latents Mode ----
    latents_only = _get_bool(cfg, "latents_only", True)
    latent_tap = str(cfg.get("latent_tap", "pre_fc")).strip()

    # ---- Data Selection (used elsewhere, but stored in the state here) ----
    data_selection = str(cfg.get("data_selection", "random")).strip().lower()
    use_ghost_for_selection = _get_bool(cfg, "use_ghost_for_selection", False)

    # collision_end_frame (parameter kept for compatibility, read here but might not be used elsewhere)
    collision_end_frame = int(cfg.get("collision_end_frame", 0))

    # ---- Epochs Mode ----
    epochs_mode = str(cfg.get("epochs_mode", "fixed")).strip().lower()  # "fixed" or "budget"
    train_time_budget_s = float(cfg.get("train_time_budget_s", 0.0))
    eval_collisions_after_ft = _get_bool(cfg, "eval_collisions_after_ft", False)

    # ---- Save / Export Flags ----
    save_checkpoint = _get_bool(cfg, "save_checkpoint", True)
    save_train_summary_csv = _get_bool(cfg, "save_train_summary_csv", True)
    save_selected_train_samples = _get_bool(cfg, "save_selected_train_samples", True)
    save_train_val_loss_csv = _get_bool(cfg, "save_train_val_loss_csv", True)

    # Keeping True as default for backward compatibility,
    # but in your config, you will set this to false.
    force_prepare_original_dataset = _get_bool(cfg, "force_prepare_original_dataset", True)

    # threshold used in evaluation (e.g., collision FPR)
    threshold = float(cfg.get("threshold", 0.5))

    # ---- Classification Path (for legacy / compatibility): data_loading_path_classification ----
    # If not explicitly given, try using classification_root.
    dlpc = str(cfg.get("data_loading_path_classification", "")).strip()
    classification_root = _resolve_path(cfg.get("classification_root"), base)
    if not dlpc and classification_root is not None:
        dlpc = str(classification_root)

    # ---------------- VALIDATION ----------------
    validation = _get_bool(cfg, "validation", False)

    # validation_root: if not in config, try (base.parent/validation) or (base/validation)
    validation_root = _resolve_path(cfg.get("validation_root"), base)
    if validation_root is None:
        cand = (base.parent / "validation").resolve()
        validation_root = cand if cand.exists() else (base / "validation").resolve()

    # Returns the "static" DataConfig object.
    return DataConfig(
        config_json_path=cfg_path,
        config_dict=cfg,
        model_original_root=model_original_root,
        dataset_training_root=ds_training_root,
        outdir=outdir,
        original_dataset_root=original_dataset_root,
        epochs=epochs,
        lr=lr,
        patience=patience,
        weight_decay=weight_decay,
        batch_size=batch_size,
        seed=seed,
        deterministic=deterministic,
        latents_only=latents_only,
        latent_tap=latent_tap,
        data_selection=data_selection,
        use_ghost_for_selection=use_ghost_for_selection,
        collision_end_frame=collision_end_frame,
        epochs_mode=epochs_mode,
        train_time_budget_s=train_time_budget_s,
        eval_collisions_after_ft=eval_collisions_after_ft,
        save_checkpoint=save_checkpoint,
        save_train_summary_csv=save_train_summary_csv,
        save_selected_train_samples=save_selected_train_samples,
        save_train_val_loss_csv=save_train_val_loss_csv,
        force_prepare_original_dataset=force_prepare_original_dataset,
        data_loading_path_classification=dlpc,
        threshold=threshold,
        validation=validation,
        validation_root=validation_root,
    )


# =============================================================================
# 2) Model setup for latents_only mode: freeze encoder and unlock post-tap
# =============================================================================
def _prepare_model_for_latents_only(model: torch.nn.Module, tap: str) -> None:
    """
    Freezes the encoder and leaves only the post-tap blocks trainable.

    Supported taps (consistent with compat.extract_latent/forward_from_latent):
      - post_merge  -> train combined_block_1 + combined_block_2 + fully_connected
      - post_comb1  -> train combined_block_2 + fully_connected
      - post_comb2  -> train fully_connected
      - pre_fc      -> train fully_connected
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
# 3) Loading the pre-prepared original_dataset from disk
# =============================================================================
def _load_original_dataset(data_config: DataConfig, device: torch.device) -> None:
    """
    Loads the original_dataset from data_config.original_dataset_root.

    Expected input on disk:
      - meta.json
      - manifest.json
      - if latents_only=True: also Z_all.npy and Y_all.npy

    Effect (side effect on data_config):
      - data_config.original_buffer.items = list of BaseSample (GateSample/NoGateSample)
      - if latents_only:
          data_config.original_buffer.latent_buffer = LatentBuffer with:
            * Z_all_t (torch tensor on device)
            * Y_all_t (torch tensor on device)
            * tap (read from meta.json or fallback to config)
        else:
          data_config.original_buffer.latent_buffer = None
    """
    root = data_config.original_dataset_root
    meta_p = root / "meta.json"
    man_p = root / "manifest.json"

    if not meta_p.exists() or not man_p.exists():
        raise FileNotFoundError(
            f"original_dataset not ready in {root}. "
            f"Expected meta.json + manifest.json (use prepare_original_data_for_training.py)."
        )

    # meta also serves to verify latents_only consistency between config and saved dataset
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    latent_only_saved = bool(meta.get("latent_only", False))
    if latent_only_saved != bool(data_config.latents_only):
        raise RuntimeError(
            f"Mode mismatch: config latents_only={data_config.latents_only} "
            f"but original_dataset latent_only={latent_only_saved}."
        )

    # manifest contains the list of items (path + label)
    manifest = json.loads(man_p.read_text(encoding="utf-8"))
    items = manifest.get("items", [])
    if not isinstance(items, list) or not items:
        raise RuntimeError("manifest.json does not contain valid 'items' or is empty.")

    # Builds sample list in RAM
    samples: List[BaseSample] = []
    for i, it in enumerate(items):
        ip = str(it["img_path"])
        tp = str(it["tof_path"])
        y = int(it["label"])

        if y == 1:
            samples.append(GateSample(id=i, img_path=ip, tof_path=tp, label=1))
        else:
            samples.append(NoGateSample(id=i, img_path=ip, tof_path=tp, label=0))

    data_config.original_buffer.items = samples

    # If latents_only, also load the Z_all/Y_all embeddings
    if data_config.latents_only:
        Zp = root / "Z_all.npy"
        Yp = root / "Y_all.npy"
        if not Zp.exists() or not Yp.exists():
            raise FileNotFoundError(f"latents_only: missing {Zp.name}/{Yp.name} in {root}.")

        Z = np.load(Zp, allow_pickle=False)  # shape [N,...]
        Y = np.load(Yp, allow_pickle=False)  # shape [N,1] typically

        # check sample count consistency
        if int(Z.shape[0]) != len(samples) or int(Y.shape[0]) != len(samples):
            raise RuntimeError(f"Mismatch: Z={Z.shape[0]}, Y={Y.shape[0]}, items={len(samples)}")

        buf = LatentBuffer(capacity=int(Z.shape[0]))
        buf.tap = str(meta.get("latent_tap", data_config.latent_tap))

        # conversion to torch float32 and transfer to device
        buf.Z_all_t = torch.from_numpy(Z.astype(np.float32, copy=False)).to(device)
        buf.Y_all_t = torch.from_numpy(Y.astype(np.float32, copy=False)).to(device)

        data_config.original_buffer.latent_buffer = buf
    else:
        data_config.original_buffer.latent_buffer = None

    print(f"[setup] original_dataset loaded: items={len(samples)}, latent_only={data_config.latents_only}")


# =============================================================================
# 4) Loading the validation dataset (optional)
# =============================================================================
def _load_validation_dataset(data_config: DataConfig, device: torch.device) -> None:
    """
    Loads validation (if validation=True in config).

    Expected structure in validation_root:
      validation_root/
        gate/... (camera_images/tof_distance_array ...)
        no_gate/... (camera_images/tof_distance_array ...)

    Effect on data_config:
      - data_config.validation_buffer.items = sample list
      - if latents_only:
          data_config.validation_buffer.latent_buffer = LatentBuffer calculated on the fly
        else:
          data_config.validation_buffer.latent_buffer = None
    """
    if not bool(getattr(data_config, "validation", False)):
        return

    root = Path(data_config.validation_root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"validation=true but validation_root does not exist: {root}")

    # list_pairs_gate_no_gate returns triples (img_path, tof_path, label)
    triples = list_pairs_gate_no_gate(root)
    if not triples:
        raise RuntimeError(
            f"No files found in validation set: {root} "
            f"(expected gate/ and no_gate/ with camera_images/tof_distance_array)."
        )

    samples: List[BaseSample] = []
    for i, (ip, tp, y) in enumerate(triples):
        if int(y) == 1:
            samples.append(GateSample(id=i, img_path=ip, tof_path=tp, label=1))
        else:
            samples.append(NoGateSample(id=i, img_path=ip, tof_path=tp, label=0))

    data_config.validation_buffer.items = samples

    # If latents_only, we calculate validation latents using the original model
    if data_config.latents_only:
        if data_config.original_model is None or data_config.device is None:
            raise RuntimeError("validation(latents_only): original_model/device not initialized.")

        try:
            from .latent_utils_min import compute_latent_buffer_for_samples
        except Exception:
            from latent_utils_min import compute_latent_buffer_for_samples

        buf = compute_latent_buffer_for_samples(
            samples=samples,
            model=data_config.original_model,
            data_config=data_config,
            device=device,
            latent_tap=data_config.latent_tap,
        )
        data_config.validation_buffer.latent_buffer = buf
    else:
        data_config.validation_buffer.latent_buffer = None

    ng = sum(1 for s in samples if int(s.label) == 0)
    g = sum(1 for s in samples if int(s.label) == 1)
    print(
        f"[setup] validation dataset loaded: items={len(samples)} gate={g} no_gate={ng} "
        f"latents_only={data_config.latents_only}"
    )


# =============================================================================
# 5) Setup ENTRY POINT: returns DataConfig ready for the pipeline
# =============================================================================
def setup(config_json_path: str | Path, GateClassifierCls) -> DataConfig:
    """
    Builds and fully initializes DataConfig.

    Steps:
      A) load_data_config: reads config and creates "static" DataConfig
      B) set_seeds
      C) set_device (CPU/GPU + determinism)
      D) loads latest checkpoint and builds original model
      E) warm-up forward (to initialize modules / avoid overhead on first forward)
      F) if latents_only: freeze encoder and unlock post-tap parameters
      G) load original_dataset (manifest/meta + optionally Z_all/Y_all)
      H) load validation (if enabled)
      I) create loss + optimizer (trainable parameters only)

    Output:
      data_config (DataConfig) with runtime fields populated:
        - device
        - original_model + original_model_ckpt
        - original_buffer (items + latent_buffer if latents_only)
        - validation_buffer (items + latent_buffer if latents_only and validation=True)
        - bce_loss
        - optimizer
    """
    # A) config
    data_config = load_data_config(config_json_path)

    # B) seed
    set_seeds(data_config.seed)

    # C) device
    device = set_device(deterministic=data_config.deterministic)
    data_config.device = device

    # D) load original model from most recent checkpoint
    ckpt = find_latest_checkpoint(data_config.model_original_root)
    model = load_model(str(ckpt), device, GateClassifierCls)

    data_config.original_model_ckpt = ckpt
    data_config.original_model = model

    # E) warm-up: a forward pass with dummy input to initialize modules
    with torch.no_grad():
        _ = model(
            torch.zeros(1, 1, 168, 168, device=device),
            torch.zeros(1, 1, 21, 21, device=device),
        )

    # F) freeze/unfreeze for latents_only
    if data_config.latents_only:
        _prepare_model_for_latents_only(model, data_config.latent_tap)

    # G) load original_dataset
    _load_original_dataset(data_config, device)

    # H) load validation
    _load_validation_dataset(data_config, device)

    # I) Create the loss function object: Binary Cross Entropy.
    bce = torch.nn.BCELoss()

    # Create the optimizer (Adam), i.e., the object that updates model weights during training,
    # passing only trainable parameters to Adam.
    opt = torch.optim.Adam(
        [p for p in model.parameters() if p.requires_grad],
        lr=float(data_config.lr),
        weight_decay=float(getattr(data_config, "weight_decay", 0.0)),
    )

    data_config.bce_loss = bce
    data_config.optimizer = opt

    return data_config