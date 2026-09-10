from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

import numpy as np


@dataclass
class SelectionInput:
    """
    Input comune per tutte le strategie di selezione.

    - Z: latenti [N, D] o [N, C,H,W] (se necessari)
    - Y: labels [N] (0/1)
    - P: probabilità [N] (se necessarie)
    - K: numero di elementi da selezionare
    - gate_quota: quota di esempi gate (label=1) in [0,1], oppure None (no bilanciamento)
    - threshold: soglia usata da alcune strategie (per ora ignorata da bce/entropy)
    - Z_ghost / P_ghost: latenti/probabilità dei "ghost" (collisione corrente)
    - seed: seed per RNG locale
    """
    Z: Optional[np.ndarray]
    Y: np.ndarray
    P: Optional[np.ndarray]
    K: int
    gate_quota: Optional[float]
    threshold: float = 0.5
    Z_ghost: Optional[np.ndarray] = None
    P_ghost: Optional[np.ndarray] = None
    seed: int = 0


class SelectionStrategy(Protocol):
    """
    Interfaccia comune per una tecnica di data selection.
    """

    name: str

    @property
    def needs_latent(self) -> bool:
        ...

    @property
    def needs_probs(self) -> bool:
        ...

    def select(self, inp: SelectionInput) -> np.ndarray:
        """
        Ritorna indici (np.int64) nel range [0, N), dove N = len(inp.Y).
        """
        ...
