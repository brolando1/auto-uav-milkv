from __future__ import annotations

from typing import Optional

import numpy as np
import torch


# ---------------------------------------------------------------------
# Base helper functions (ported from lr_select.py)
# ---------------------------------------------------------------------


def _to_t(x, dtype=torch.float64) -> torch.Tensor:
    if isinstance(x, torch.Tensor):
        t = x.detach().to(dtype)
    else:
        t = torch.as_tensor(x, dtype=dtype)
    return t


def _to_i(x) -> torch.Tensor:
    if isinstance(x, torch.Tensor):
        return x.detach().to(torch.int64)
    return torch.as_tensor(x, dtype=torch.int64)


def _sanitize_probs_t(p_t: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    p = torch.nan_to_num(p_t, nan=0.5, posinf=1.0 - eps, neginf=eps)
    return torch.clamp(p, eps, 1.0 - eps)


def _finite_or_zero_t(x: torch.Tensor) -> torch.Tensor:
    return torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


def _logit_t(p: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    p = _sanitize_probs_t(p, eps)
    return torch.log(p) - torch.log(1.0 - p)


def _entropy_t(p: torch.Tensor) -> torch.Tensor:
    p = _sanitize_probs_t(p, 1e-12)
    h = -(p * torch.log(p) + (1.0 - p) * torch.log(1.0 - p))
    return _finite_or_zero_t(h)


def _to_2d_t(arr) -> torch.Tensor:
    """
    Converts a tensor/ndarray into [N, D] by flattening everything except the first dimension.
    """
    X = _to_t(arr, dtype=torch.float32)
    return X if X.ndim == 2 else X.reshape(X.shape[0], -1)


def _argsort_desc_t(x: torch.Tensor) -> torch.Tensor:
    return torch.argsort(x, dim=0, descending=True)


# ---------------------------------------------------------------------
# k-center & robust k-center
# ---------------------------------------------------------------------


def _pairwise_sq_dists_t(X2: torch.Tensor, Y2: Optional[torch.Tensor] = None) -> torch.Tensor:
    """
    Pairwise squared Euclidean distance:

        d2[i, j] = ||X2[i] - Y2[j]||^2

    X2: [M, D], Y2: [N, D] or None (in quel caso Y2 = X2).
    """
    if Y2 is None:
        Y2 = X2

    # Assume already float32
    X2 = X2.to(dtype=torch.float32)
    Y2 = Y2.to(dtype=torch.float32)

    # ||x - y||^2 = ||x||^2 + ||y||^2 - 2 x·y
    x_norm = (X2 ** 2).sum(dim=1, keepdim=True)      # [M, 1]
    y_norm = (Y2 ** 2).sum(dim=1, keepdim=True).T    # [1, N]
    d2 = x_norm + y_norm - 2.0 * X2 @ Y2.T           # [M, N]
    return d2.clamp_(min=0.0)


def _kcenter_select_t(
    X2: torch.Tensor,
    K: int,
    first: str = "random",
    rng: Optional[np.random.RandomState] = None,
) -> torch.Tensor:
    """
    k-center greedy (farthest-first traversal) su X2 [N, D].

    - Sceglie un primo centro (random o maxL2).
    - Mantiene per ogni punto la distanza al centro più vicino.
    - Ad ogni iterazione aggiunge il punto con distanza minima-massima.

    Questo è il building block di base; il "robust" viene costruito sopra.
    """
    N = int(X2.size(0))
    if N == 0 or K <= 0:
        return torch.zeros(0, dtype=torch.int64)

    K = int(min(max(1, K), N))
    if K == N:
        return torch.arange(N, dtype=torch.int64)

    if rng is None:
        rng = np.random.RandomState()

    # Scelta del primo centro
    if first == "maxl2":
        norms = torch.sum(X2 * X2, dim=1)
        c0 = int(torch.argmax(norms).item())
    else:  # "random" (default)
        c0 = int(rng.randint(N))

    centers = [c0]

    # quadratic distance of each point to the nearest center
    d2 = torch.sum((X2 - X2[c0]) ** 2, dim=1)  # [N]

    for _ in range(1, K):
        # point farthest from the nearest center
        j = int(torch.argmax(d2).item())
        centers.append(j)

        # aggiorna le distanze minime al nuovo centro
        new_d2 = torch.sum((X2 - X2[j]) ** 2, dim=1)
        d2 = torch.minimum(d2, new_d2)

    return torch.as_tensor(centers, dtype=torch.int64)


def _robust_kcenter_base_t(
    X2: torch.Tensor,
    K: int,
    outlier_fraction: float = 0.0,
    first: str = "random",
    rng: Optional[np.random.RandomState] = None,
) -> torch.Tensor:
    """
    Simplified robust k-center on a single set of points X2.

    Idea (approximation of algorithm 2 schema in the paper):

      1. Run standard k-center greedy to get K centers.
      2. Calculate, for each point, the distance to the nearest center.
      3. Discard a fraction outlier_fraction of points with the largest distance.
      4. Repeat k-center greedy only on inliers.

    outlier_fraction = 0.0  -> normal k-center.
    """
    N = int(X2.size(0))
    if N == 0 or K <= 0:
        return torch.zeros(0, dtype=torch.int64)

    K = int(min(max(1, K), N))
    if outlier_fraction <= 0.0 or N <= K:
        # non-robust case or very few points
        return _kcenter_select_t(X2, K, first=first, rng=rng)

    # 1) standard k-center on the whole set
    base_centers = _kcenter_select_t(X2, K, first=first, rng=rng)

    # 2) distance to the nearest center for each point
    d2_all = _pairwise_sq_dists_t(X2, X2[base_centers])   # [N, K]
    d_min = d2_all.min(dim=1).values.sqrt_()              # [N]

    # 3) choose the outlier_fraction of points with the largest distances
    xi = int(outlier_fraction * float(N))
    if xi <= 0:
        return base_centers

    _, order = torch.sort(d_min, descending=True)
    outlier_mask = torch.zeros(N, dtype=torch.bool, device=X2.device)
    outlier_mask[order[:xi]] = True
    inlier_mask = ~outlier_mask
    inlier_idx = inlier_mask.nonzero(as_tuple=False).view(-1)

    if inlier_idx.numel() <= K:
        # few inliers, use them all
        return inlier_idx.to(torch.int64)

    # 4) k-center on inliers
    X_in = X2[inlier_idx]
    centers_inliers = _kcenter_select_t(X_in, K, first=first, rng=rng)
    return inlier_idx[centers_inliers].to(torch.int64)


def _kcenter_with_ghost_t(
    X2: torch.Tensor,
    Zg2: Optional[torch.Tensor],
    K: int,
    outlier_fraction: float = 0.0,
    first: str = "random",
    rng: Optional[np.random.RandomState] = None,
) -> torch.Tensor:
    """
    Robust k-center with "ghost" (e.g. current collision):

    - Ghosts are concatenated to candidates: Z_all = [Zg2; X2].
    - Execute robust k-center on Z_all with K_all >= K.
    - At the end discard centers that fall on ghosts and keep only
      those that belong to X2.

    outlier_fraction applied on the combined set Z_all.
    """
    N = int(X2.size(0))
    if N == 0 or K <= 0:
        return torch.zeros(0, dtype=torch.int64)

    K = int(max(1, K))

    if Zg2 is None or Zg2.numel() == 0:
        # no ghost -> robust_kcenter_base on X2
        return _robust_kcenter_base_t(
            X2, K, outlier_fraction=outlier_fraction, first=first, rng=rng
        )

    M = int(Zg2.size(0))
    Zg2 = Zg2.to(dtype=X2.dtype, device=X2.device)

    # unified pool
    Z_all = torch.cat([Zg2, X2], dim=0)  # [M+N, D]

    # select K_all >= K to compensate for possible centers on ghosts
    K_all = min(K + M, int(Z_all.size(0)))
    sel_all = _robust_kcenter_base_t(
        Z_all, K_all, outlier_fraction=outlier_fraction, first=first, rng=rng
    )

    # keep only centers that fall in X2 (index >= M)
    sel_cand = sel_all[sel_all >= M] - M

    if sel_cand.numel() > K:
        sel_cand = sel_cand[:K]

    return sel_cand.to(torch.int64)


# ---------------------------------------------------------------------
# gate / no_gate balancing
# ---------------------------------------------------------------------


def _balanced_merge_t(
    idx_g: torch.Tensor,
    idx_ng: torch.Tensor,
    K: int,
    quota_gate: float,
) -> torch.Tensor:
    K_gate = int(round(K * float(quota_gate)))
    K_ng = K - K_gate

    take_g = idx_g[: min(K_gate, idx_g.numel())]
    take_n = idx_ng[: min(K_ng, idx_ng.numel())]

    sel = torch.cat([take_g, take_n], dim=0)
    if sel.numel() < K:
        rem = torch.cat([idx_g[len(take_g) :], idx_ng[len(take_n) :]], dim=0)
        if rem.numel() > 1:
            perm = torch.randperm(rem.numel())
            rem = rem[perm]
        add = rem[: max(0, K - sel.numel())]
        sel = torch.cat([sel, add], dim=0)
    return sel[:K]


# ---------------------------------------------------------------------
# GSS greedy
# ---------------------------------------------------------------------


def _normalize_rows_t(X: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
    """
    Normalizza ogni riga di X a norma L2 = 1 (se possibile).
    Serve perché nel paper c = max cos(g, G_i) + 1, quindi usiamo
    direttamente il prodotto scalare come cosine similarity.
    """
    n = torch.linalg.norm(X, ord=2, dim=1, keepdim=True) + eps
    return X / n


def _gss_greedy_single_t(
    G_unit: torch.Tensor,
    K: int,
    rng: np.random.RandomState,
    n_subset: int = 32,
) -> torch.Tensor:
    """
    Implementazione fedele (offline) dell'Algoritmo 2 - Greedy Sample Selection.

    Parametri
    ---------
    G_unit : [N, D] torch.Tensor
        "Gradienti" già normalizzati riga-per-riga (||g_i|| = 1), quindi
        <g, G_i> è direttamente la cosine similarity.
    K : int
        Capienza massima della memoria M (M nel paper). Alla fine
        ritorniamo al più K indici.
    rng : np.random.RandomState
        RNG per le scelte casuali (ordine dello stream, RandomSubset e r).
    n_subset : int
        n nel paper: dimensione del RandomSubset(M, n) usato per stimare c.

    Ritorno
    -------
    torch.Tensor [<=K] (dtype=int64)
        Indici nel range [0, N) degli esempi selezionati.
    """
    N = G_unit.size(0)
    if K <= 0 or N == 0:
        return torch.zeros(0, dtype=torch.int64)
    if K >= N:
        return torch.arange(N, dtype=torch.int64)

    # Stream offline: permutiamo gli esempi
    order = torch.as_tensor(rng.permutation(N), dtype=torch.int64)

    # Memoria M (indici nel pool) e vettore C dei punteggi
    M_idx_t = torch.zeros(0, dtype=torch.int64)  # indici in [0, N)
    C: list[float] = []                          # C_i nel paper

    for i in order.tolist():
        g = G_unit[i]  # [D]

        # --- Step 5–7 del paper: stima di c ------------------------
        if M_idx_t.numel() == 0:
            c = 0.0
        else:
            m = M_idx_t.numel()
            s = min(n_subset, m)

            pick = torch.as_tensor(
                rng.choice(m, size=s, replace=False),
                dtype=torch.int64,
            )
            B = G_unit[M_idx_t[pick]]  # [s, D]

            c = float(torch.max(B @ g) + 1.0)

        # Warm-up: while len(M) < K, always insert
        if M_idx_t.numel() < K:
            M_idx_t = torch.cat(
                [M_idx_t, torch.as_tensor([i], dtype=torch.int64)],
                dim=0,
            )
            C.append(float(c))
            continue

        # Memoria piena: rimpiazzo solo se c < 1 (cosine < 0)
        if c >= 1.0:
            continue

        Ci = torch.tensor(C, dtype=torch.float32)
        Ci_sum = float(torch.sum(Ci)) + 1e-12

        probs = (Ci / Ci_sum).cpu().numpy()
        j_rel = int(rng.choice(len(C), p=probs))

        r = rng.rand()

        denom = float(Ci[j_rel] + c + 1e-12)
        replace_prob = float(Ci[j_rel] / denom)

        if r < replace_prob:
            M_idx_t[j_rel] = int(i)
            C[j_rel] = float(c)

    return M_idx_t[:K]
