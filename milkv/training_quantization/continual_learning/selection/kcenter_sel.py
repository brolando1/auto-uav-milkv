from __future__ import annotations

from typing import Optional

import numpy as np
import torch

from .base import SelectionInput, SelectionStrategy
from .common import (
    _to_i,
    _to_2d_t,
    _kcenter_select_t,
    _robust_kcenter_base_t,
    _kcenter_with_ghost_t,
)


class KCenterSelection(SelectionStrategy):
    """
    Selection based on latents with **robust k-center**.

    - Uses _robust_kcenter_base_t (farthest-first + outlier removal)
      on latents Z.
    - Optionally supports "ghosts" (current collision) via
      _kcenter_with_ghost_t.
    - Can work with or without gate/no_gate balancing.
    """

    name = "kcenter_latent"

    # fraction of points we can consider outliers and discard
    # (approximates the Ξ parameter of the robust k-center algorithm in the paper)
    robust_outlier_fraction: float = 0.05

    @property
    def needs_latent(self) -> bool:
        return True

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

        Z2 = _to_2d_t(inp.Z).to(torch.float32)
        Zg2: Optional[torch.Tensor] = None
        if inp.Z_ghost is not None:
            Zg2 = _to_2d_t(inp.Z_ghost).to(torch.float32)

        gate_quota = inp.gate_quota
        use_balance = gate_quota is not None and 0.0 <= float(gate_quota) <= 1.0

        idx_gate = torch.where(Y == 1)[0]
        idx_nogat = torch.where(Y == 0)[0]

        of = float(self.robust_outlier_fraction)

        # ----------------------- case WITHOUT balancing -----------------------
        if not use_balance:
            if Zg2 is None or Zg2.numel() == 0:
                # robust k-center sui soli latenti del pool
                sel = _robust_kcenter_base_t(
                    Z2,
                    K,
                    outlier_fraction=of,
                    first="random",
                    rng=rng,
                )[:K]
                return sel.numpy().astype(np.int64)

            # robust k-center con ghost
            sel = _kcenter_with_ghost_t(
                Z2,
                Zg2,
                K,
                outlier_fraction=of,
                first="random",
                rng=rng,
            )[:K]
            return sel.numpy().astype(np.int64)

        # ----------------------- case WITH balancing ------------------------
        k_g = min(idx_gate.numel(), int(round(K * float(gate_quota))))

        # ------ gate ------
        if k_g > 0 and idx_gate.numel() > 0:
            Z_g = Z2[idx_gate]
            sel_g_rel = _kcenter_with_ghost_t(
                Z_g,
                Zg2,
                k_g,
                outlier_fraction=of,
                first="random",
                rng=np.random.RandomState(int(inp.seed) + 1),
            )
        else:
            sel_g_rel = torch.zeros(0, dtype=torch.int64)

        sel_g = idx_gate[sel_g_rel] if sel_g_rel.numel() > 0 else torch.zeros(0, dtype=torch.int64)

        # ------ no_gate ------
        rem = K - sel_g.numel()
        if rem > 0 and idx_nogat.numel() > 0:
            Z_ng = Z2[idx_nogat]
            sel_ng_rel = _kcenter_with_ghost_t(
                Z_ng,
                Zg2,
                rem,
                outlier_fraction=of,
                first="random",
                rng=np.random.RandomState(int(inp.seed) + 2),
            )
        else:
            sel_ng_rel = torch.zeros(0, dtype=torch.int64)

        sel_ng = idx_nogat[sel_ng_rel] if sel_ng_rel.numel() > 0 else torch.zeros(0, dtype=torch.int64)

        sel = torch.cat([sel_g, sel_ng], dim=0)

        # if we still don't have K, fill from the rest with standard robust k-center
        if sel.numel() < K:
            rest_np = np.setdiff1d(np.arange(Z2.size(0)), sel.numpy(), assume_unique=False)
            if rest_np.size > 0:
                rest = torch.from_numpy(rest_np.astype(np.int64))
                add_rel = _robust_kcenter_base_t(
                    Z2[rest],
                    K - sel.numel(),
                    outlier_fraction=of,
                    first="random",
                    rng=np.random.RandomState(int(inp.seed) + 3),
                )
                sel = torch.cat([sel, rest[add_rel]], dim=0)

        return sel[:K].numpy().astype(np.int64)
