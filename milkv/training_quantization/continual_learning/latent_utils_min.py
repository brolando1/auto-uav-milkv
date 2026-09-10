from __future__ import annotations

from typing import List

import numpy as np
import torch

# "Robust" import: works both as a package (from .xxx) and as a script (from xxx)
try:
    from .buffer import LatentBuffer
    from .compat import extract_latent
    from .samples import BaseSample
    from .setup_from_config import DataConfig
except Exception:
    from buffer import LatentBuffer
    from compat import extract_latent
    from samples import BaseSample
    from setup_from_config import DataConfig


# Expected shapes for the model / dataset:
# - camera: 168x168
# - tof   :  21x21
IMG_H, IMG_W = 168, 168
TOF_H, TOF_W = 21, 21


def _as_hw(arr: np.ndarray, *, name: str) -> np.ndarray:
    """
    Normalizes ONLY the *shape* of the array (not the values), to get a 2D (H,W).

    Accepts these formats:
      - (H, W)
      - (1, H, W)     -> takes arr[0]
      - (H, W, 1)     -> takes arr[..., 0]

    Returns:
      - a np.ndarray 2D with shape (H, W)

    If the shape is not one of those above, raises ValueError: it means the .npy is not in the expected format.
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
    Converts a numpy array to torch.Tensor float32 with shape [1, H, W].

    Does 2 things:
      1) Uses _as_hw() to get (H,W)
      2) Checks that (H,W) == (exp_h, exp_w) -> if not, error (data "not ready")
      3) Cast to float32 WITHOUT changing the values
      4) Adds the channel dimension: unsqueeze(0) -> [1,H,W]

    Output:
      torch.Tensor shape [1, exp_h, exp_w], dtype float32, on CPU (then move to device).
    """
    hw = _as_hw(arr, name=name)

    if hw.shape != (exp_h, exp_w):
        raise ValueError(f"{name}: shape {hw.shape} != expected {(exp_h, exp_w)}. Data are not 'ready'.")

    hw = hw.astype(np.float32, copy=False)
    return torch.from_numpy(hw).unsqueeze(0)


@torch.no_grad()
def compute_latent_buffer_for_samples(
    *,
    samples: List[BaseSample],
    model: torch.nn.Module,
    data_config: DataConfig,
    device: torch.device,
    latent_tap: str,
) -> LatentBuffer:
    """
    PURPOSE
    -------
    Given a list of samples (each with img_path, tof_path, label),
    calculates the latent "Z" for each sample using the model at the `latent_tap` point,
    and returns a LatentBuffer ready for training in `latents_only` mode.

    What does "latent_tap" mean?
      It is the internal point of the network where you want to "intercept" the activation:
        - post_merge / post_comb1 / post_comb2 / pre_fc
      (see compat.extract_latent)

    INPUT
    -----
    - samples: list of BaseSample (GateSample, NoGateSample, CollisionSample, etc.)
    - model: model already loaded and moved to device
    - data_config: used primarily for batch_size (data_config.batch_size)
    - device: torch.device (cuda or cpu)
    - latent_tap: string specifying where to extract the latent

    OUTPUT (return)
    ---------------
    Returns a LatentBuffer with:
      - buf.tap      = latent_tap
      - buf.Z_all_t  = torch.Tensor [N, ...]  (latents for all samples)
      - buf.Y_all_t  = torch.Tensor [N, 1]    (label float32: 0/1)

    SIDE EFFECT
    -----------
    None: does not modify data_config, does not write to disk.
    """
    N = len(samples)

    # batch size: default 128 if not present / falsy
    bs = max(1, int(getattr(data_config, "batch_size", 128) or 128))

    # Trivial case: no samples -> return empty buffer (consistent)
    if N == 0:
        buf = LatentBuffer(capacity=0)
        buf.tap = latent_tap

        # Here we choose empty tensors with minimal shape (0,1) to avoid None and simplify the caller
        buf.Z_all_t = torch.empty((0, 1), device=device, dtype=torch.float32)
        buf.Y_all_t = torch.empty((0, 1), device=device, dtype=torch.float32)
        return buf

    # Z_chunks: list of latent tensors calculated batch-by-batch.
    #          We will concatenate them at the end into a single tensor [N, ...]
    Z_chunks: List[torch.Tensor] = []

    # Y_list: python list of labels (int), one per sample, which we then convert to tensor [N,1]
    Y_list: List[int] = []

    # Eval mode + no_grad: used because we are only "extracting features" and don't want gradients
    model.eval()

    # Iterate through samples in blocks of batch size (bs)
    for start in range(0, N, bs):
        end = min(N, start + bs)
        chunk = samples[start:end]

        # Batch construction:
        # - imgs: list of tensors [1,168,168]
        # - tofs: list of tensors [1,21,21]
        # - ys  : list of labels
        imgs: List[torch.Tensor] = []
        tofs: List[torch.Tensor] = []
        ys: List[int] = []

        for s in chunk:
            # Load the two numpy files corresponding to the sample
            img_np = np.load(s.img_path, allow_pickle=False)
            tof_np = np.load(s.tof_path, allow_pickle=False)

            # Convert to torch [1,H,W] (CPU), checking shape
            bi = _to_tensor_1hw(img_np, exp_h=IMG_H, exp_w=IMG_W, name="CAMERA")
            bt = _to_tensor_1hw(tof_np, exp_h=TOF_H, exp_w=TOF_W, name="TOF")

            imgs.append(bi)
            tofs.append(bt)
            ys.append(int(s.label))

        # Stack: from list of [1,H,W] -> batch [B,1,H,W]
        BI = torch.stack(imgs, 0).to(device, dtype=torch.float32)  # [B,1,168,168]
        BT = torch.stack(tofs, 0).to(device, dtype=torch.float32)  # [B,1,21,21]

        # Extract latents at the requested tap:
        # - Z_t output is a tensor with shape depending on the tap:
        #     post_merge / post_comb1 / post_comb2 : [B, C, H, W]
        #     pre_fc                              : [B, D]
        #
        # Note: we use .cpu() because we concatenate on CPU and then move back to device,
        #       but you could also keep them on GPU if desired (this style was chosen here).
        Z_t = extract_latent(model, BI, BT, tap=latent_tap).detach().cpu()

        Z_chunks.append(Z_t)
        Y_list.extend(ys)

    # Concatenate all batches along the batch dimension:
    #   [B1,...] + [B2,...] + ... -> [N,...]
    #
    # Then move it to device and force float32
    Z_all_t = torch.cat(Z_chunks, dim=0).to(device, dtype=torch.float32)

    # Create label tensor [N,1] float32
    Y_all_t = torch.as_tensor(Y_list, dtype=torch.float32, device=device).view(-1, 1)

    # Build the final LatentBuffer
    buf = LatentBuffer(capacity=int(Z_all_t.shape[0]))
    buf.tap = latent_tap
    buf.Z_all_t = Z_all_t
    buf.Y_all_t = Y_all_t

    # Returns the buffer ready for:
    #   - data_config.original_buffer.latent_buffer
    #   - data_config.collision_buffer.latent_buffer
    #   - data_config.validation_buffer.latent_buffer
    # and then merge in prepare_training()
    return buf
