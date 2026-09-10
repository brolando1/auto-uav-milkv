from __future__ import annotations

import numpy as np
import torch

from .base import SelectionInput, SelectionStrategy
from .common import (
    _to_i,
    _to_t,
    _sanitize_probs_t,
    _entropy_t,
    _argsort_desc_t,
    _balanced_merge_t,
)


class EntropySelection(SelectionStrategy):
    name = "entropy"

    @property
    def needs_latent(self) -> bool:
        return False

    @property
    def needs_probs(self) -> bool:
        return True

    def select(self, inp: SelectionInput) -> np.ndarray:
        Y = _to_i(inp.Y)
        N = int(Y.numel())
        if N == 0 or inp.K <= 0:
            return np.zeros((0,), dtype=np.int64)

        K = int(min(inp.K, N))
        gate_quota = inp.gate_quota
        use_balance = gate_quota is not None and 0.0 <= float(gate_quota) <= 1.0

        P = _sanitize_probs_t(_to_t(inp.P, dtype=torch.float64)).to(torch.float64)
        S = _entropy_t(P)

        idx_gate = torch.where(Y == 1)[0]
        idx_nogat = torch.where(Y == 0)[0]

        if not use_balance:
            sel = _argsort_desc_t(S)[:K]
            return sel.numpy().astype(np.int64)

        ord_g = idx_gate[_argsort_desc_t(S[idx_gate])]
        ord_ng = idx_nogat[_argsort_desc_t(S[idx_nogat])]
        sel = _balanced_merge_t(ord_g, ord_ng, K, float(gate_quota))
        return sel.numpy().astype(np.int64)
