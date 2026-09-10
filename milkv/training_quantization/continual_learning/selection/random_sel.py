from __future__ import annotations

import numpy as np
import torch

from .base import SelectionInput, SelectionStrategy
from .common import _to_i


class RandomSelection(SelectionStrategy):
    name = "random"

    @property
    def needs_latent(self) -> bool:
        return False

    @property
    def needs_probs(self) -> bool:
        return False

    def select(self, inp: SelectionInput) -> np.ndarray:
        Y = _to_i(inp.Y)
        N = int(Y.numel())
        if N == 0 or inp.K <= 0:
            return np.zeros((0,), dtype=np.int64)

        K = int(min(inp.K, N))
        rng = np.random.RandomState(int(inp.seed))

        gate_quota = inp.gate_quota
        use_balance = gate_quota is not None and 0.0 <= float(gate_quota) <= 1.0

        if not use_balance:
            idx = rng.choice(N, size=K, replace=False)
            return idx.astype(np.int64)

        idx_gate = torch.where(Y == 1)[0]
        idx_nogat = torch.where(Y == 0)[0]

        K_gate = int(round(K * float(gate_quota)))
        K_ng = K - K_gate

        if idx_gate.numel() > 0 and K_gate > 0:
            take_g = rng.choice(idx_gate.numpy(), size=min(K_gate, idx_gate.numel()), replace=False)
        else:
            take_g = np.zeros((0,), dtype=np.int64)

        if idx_nogat.numel() > 0 and K_ng > 0:
            take_n = rng.choice(idx_nogat.numpy(), size=min(K_ng, idx_nogat.numel()), replace=False)
        else:
            take_n = np.zeros((0,), dtype=np.int64)

        sel = np.concatenate([take_g, take_n], axis=0)
        if sel.size < K:
            rest = np.setdiff1d(np.arange(N, dtype=np.int64), sel, assume_unique=False)
            if rest.size > 0:
                extra = rng.choice(rest, size=min(K - sel.size, rest.size), replace=False)
                sel = np.concatenate([sel, extra], axis=0)

        return sel[:K].astype(np.int64)
