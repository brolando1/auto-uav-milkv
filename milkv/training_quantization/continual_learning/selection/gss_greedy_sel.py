from __future__ import annotations

import numpy as np
import torch

from .base import SelectionInput, SelectionStrategy


def _to_t(x, dtype=torch.float32) -> torch.Tensor:
    if isinstance(x, torch.Tensor):
        return x.detach().to(dtype=dtype)
    return torch.as_tensor(x, dtype=dtype)


def _to_2d_t(x) -> torch.Tensor:
    X = _to_t(x, dtype=torch.float32)
    return X if X.ndim == 2 else X.reshape(X.shape[0], -1)


def _normalize_rows_t(X: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
    """
    Normalizes each row to L2 norm=1 (if possible).
    So the dot product is the cosine similarity.
    """
    n = torch.linalg.norm(X, ord=2, dim=1, keepdim=True) + eps
    return X / n


def _gss_greedy_single_t(
    G_unit: torch.Tensor,        # [N, D] gradients already normalized (||g_i||=1)
    K: int,
    rng: np.random.RandomState,
    n_subset: int = 5,
    debug: bool = False,          # <-- debug ON/OFF (traditional prints)
    debug_first: int = 50,       # <-- first N iterations detailed
    debug_every: int = 1000,     # <-- then one line every tot
    print_each_replace: bool = True,  # <-- print each replacement
) -> torch.Tensor:
    N = int(G_unit.size(0))
    if N == 0 or K <= 0:
        return torch.zeros((0,), dtype=torch.int64)

    K = int(min(K, N))
    if K >= N:
        return torch.arange(N, dtype=torch.int64)

    order = torch.as_tensor(rng.permutation(N), dtype=torch.int64)

    M_idx = torch.zeros((0,), dtype=torch.int64)
    C: list[float] = []

    # --- debug counters ---
    mem_full_steps = 0
    skip_c_ge_1 = 0
    c_lt_1_steps = 0
    replace_attempts = 0
    replace_done = 0
    maxcos_list: list[float] = []

    for it, i in enumerate(order.tolist()):
        g = G_unit[i]

        # compute c and max_cos (subset)
        if M_idx.numel() == 0:
            max_cos = None
            c = 0.0
        else:
            m = int(M_idx.numel())
            s = min(int(n_subset), m)
            pick = torch.as_tensor(rng.choice(m, size=s, replace=False), dtype=torch.int64)

            B = G_unit[M_idx[pick]]
            sims = (B @ g)                 # cosine similarity (subset)
            max_cos = float(torch.max(sims).item())
            maxcos_list.append(max_cos)
            c = float(max_cos + 1.0)

        # warm-up: fill the memory
        if M_idx.numel() < K:
            M_idx = torch.cat([M_idx, torch.as_tensor([i], dtype=torch.int64)], dim=0)
            C.append(float(c))
            if debug and it < debug_first:
                print(f"[GSS] it={it} WARMUP add idx={i} max_cos={max_cos}")
            continue

        mem_full_steps += 1

        # memory full: if c>=1 (max_cos>=0) skip
        if c >= 1.0:
            skip_c_ge_1 += 1
            if debug and it < debug_first:
                print(f"[GSS] it={it} SKIP idx={i} max_cos={max_cos:.6f} c={c:.6f}")
            if debug and debug_every > 0 and it % debug_every == 0:
                print(f"[GSS] it={it} progress: skip_c>=1={skip_c_ge_1} replace_done={replace_done}")
            continue

        # here max_cos < 0 -> try replacement
        c_lt_1_steps += 1
        replace_attempts += 1

        Ci = torch.tensor(C, dtype=torch.float32)
        Ci_sum = float(torch.sum(Ci)) + 1e-12
        probs = (Ci / Ci_sum).cpu().numpy()
        j = int(rng.choice(len(C), p=probs))

        r = float(rng.rand())
        denom = float(Ci[j] + c + 1e-12)
        replace_prob = float(Ci[j] / denom)

        did_replace = False
        if r < replace_prob:
            M_idx[j] = int(i)
            C[j] = float(c)
            replace_done += 1
            did_replace = True

        if debug and (it < debug_first or (debug_every > 0 and it % debug_every == 0) or (print_each_replace and did_replace)):
            print(
                f"[GSS] it={it} TRY_REPLACE idx={i} "
                f"max_cos={max_cos:.6f} c={c:.6f} j={j} "
                f"rp={replace_prob:.4f} r={r:.4f} REPLACE={did_replace}"
            )

    # --- final summary ---
    if debug:
        print(
            f"[GSS] SUMMARY: N={N} K={K} mem_full_steps={mem_full_steps} "
            f"skip_c>=1={skip_c_ge_1} c<1_steps={c_lt_1_steps} "
            f"replace_attempts={replace_attempts} replace_done={replace_done}"
        )
        if maxcos_list:
            arr = np.asarray(maxcos_list, dtype=np.float32)
            print(
                f"[GSS] max_cos(subset) stats: "
                f"min={arr.min():.6f} p50={np.percentile(arr,50):.6f} "
                f"p90={np.percentile(arr,90):.6f} max={arr.max():.6f} "
                f"neg={(arr < 0).sum()} nonneg={(arr >= 0).sum()}"
            )

    return M_idx[:K]



# ------------------------------------------------------------
# Strategia: GSS su FULL GRADIENT (Z = grad flatten)
# ------------------------------------------------------------

class GssGreedySelection(SelectionStrategy):
    """
# Wrapper for using GSS in the project.

    Here inp.Z are NOT latents: I use them as "full gradient" per-sample:
    - inp.Z: [N, D] full gradients (flattened + concatenated) for each candidate
    - inp.Z_ghost (optional): [M, D] full gradients of ghosts
    """
    name = "gss_greedy"

    @property
    def needs_latent(self) -> bool:
        return True

    @property
    def needs_probs(self) -> bool:
        return False

    def select(self, inp: SelectionInput) -> np.ndarray:
        # if I don't have vectors (gradients), I can't do anything
        if inp.Z is None:
            return np.zeros((0,), dtype=np.int64)

        # put everything in [N, D] form
        G = _to_2d_t(inp.Z).to(torch.float32)
        N = int(G.size(0))
        if N == 0 or inp.K <= 0:
            return np.zeros((0,), dtype=np.int64)

        K = int(min(int(inp.K), N))
        rng = np.random.RandomState(int(inp.seed))

        # normalize to use dot as cosine similarity
        G_unit = _normalize_rows_t(G)

        # ---- case without ghost ----
        if inp.Z_ghost is None:
            sel = _gss_greedy_single_t(
                G_unit,
                K=K,
                rng=rng,
                n_subset=5,
            )
            return sel.cpu().numpy().astype(np.int64)

        # ---- case with ghost ----
        Gg = _to_2d_t(inp.Z_ghost).to(torch.float32)
        if Gg.numel() == 0:
            sel = _gss_greedy_single_t(
                G_unit,
                K=K,
                rng=rng,
                n_subset=5,
            )
            return sel.cpu().numpy().astype(np.int64)

        Gg_unit = _normalize_rows_t(Gg)
        M = int(Gg_unit.size(0))

        # put ghosts first, so I can discard them later, and ask for K+M selections because I know some will fall on ghosts
        G_all = torch.cat([Gg_unit, G_unit], dim=0)
        sel_all = _gss_greedy_single_t(
            G_all,
            K=min(K + M, int(G_all.size(0))),
            rng=rng,
            n_subset=5,
        )

        # keep only indices pointing to the "real" (in unified pool the real start at index M)
        sel_real = sel_all[sel_all >= M] - M
        if sel_real.numel() > K:
            sel_real = sel_real[:K]

        return sel_real.cpu().numpy().astype(np.int64)

