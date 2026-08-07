from __future__ import annotations

from typing import Dict, Type

from .base import SelectionInput, SelectionStrategy
from .random_sel import RandomSelection
from .bce_sel import BceSelection
from .entropy_sel import EntropySelection
from .kcenter_sel import KCenterSelection
from .gss_greedy_sel import GssGreedySelection

# Registry: nome metodo -> classe strategia
_SELECTION_REGISTRY: Dict[str, Type[SelectionStrategy]] = {
    "random": RandomSelection,
    "bce": BceSelection,
    "entropy": EntropySelection,
    "kcenter_latent": KCenterSelection,
    "gss_greedy": GssGreedySelection,
}


def get_strategy(method: str) -> SelectionStrategy:
    m = str(method).strip().lower()
    if m not in _SELECTION_REGISTRY:
        raise ValueError(f"Unsupported data_selection: {method}")
    return _SELECTION_REGISTRY[m]()
