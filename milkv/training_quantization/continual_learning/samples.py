from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class BaseSample:
    id: int
    img_path: str
    tof_path: str
    label: int  # 1 = gate, 0 = no_gate

    @property
    def stem(self) -> str:
        return Path(self.img_path).stem


@dataclass
class GateSample(BaseSample):
    pass


@dataclass
class NoGateSample(BaseSample):
    pass


@dataclass
class CollisionSample(BaseSample):
    # label sarà sempre 0 (no_gate) per le collisioni
    pass
