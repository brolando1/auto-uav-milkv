from __future__ import annotations
from pathlib import Path
import numpy as np
import torch

def save_checkpoint_like_training_py(model: torch.nn.Module,
                                     ckpt_path: Path,
                                     epoch: int,
                                     val_bce: float | None,
                                     val_acc: float | None):
    # Retrieve attributes if they exist, otherwise use defaults
    ncs = getattr(model, "num_channels_start", 4)
    dp  = getattr(model, "dropout_p", 0.0)

    # Fallback cases if attributes are explicitly None
    if ncs is None:
        ncs = 4
    if dp is None:
        dp = 0.0

    state = {
        "epoch": int(epoch),
        "num_channels_start": int(ncs),
        "dropout_p": float(dp),
        "gate_classifier_state_dict": model.state_dict(),
        "optimizer_state_dict": None,
        "best_val_bce": (float(val_bce) if (val_bce is not None and not np.isnan(val_bce)) else None),
        "best_val_accuracy": (float(val_acc) if (val_acc is not None) else None),
        "best_val_f1": None,
        "best_val_auroc": None,
    }
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(state, str(ckpt_path))