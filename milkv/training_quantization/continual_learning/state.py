from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import torch


try:
    from .buffer import LatentBuffer
    from .samples import BaseSample, GateSample, NoGateSample, CollisionSample
except Exception:
    from buffer import LatentBuffer
    from samples import BaseSample, GateSample, NoGateSample, CollisionSample

if TYPE_CHECKING:
    try:
        from .lr_data import RawPairsDataset
    except Exception:
        from lr_data import RawPairsDataset


@dataclass
class TrainingBuffer:
    """
    Contiene ciò che serve per il training vero e proprio, dopo prepare_training():
      - train_items: lista di sample (shufflati)
      - latent_buffer: se latents_only=True (tensori torch precomputati)
      - training_dataset_raw: se latents_only=False (Dataset torch)
    """
    train_items: List[BaseSample] = field(default_factory=list)
    latent_buffer: Optional[LatentBuffer] = None
    training_dataset_raw: Optional["RawPairsDataset"] = None

    @property
    def train_total_samples(self) -> int:
        return len(self.train_items)

    @property
    def train_gate_count(self) -> int:
        return sum(1 for s in self.train_items if isinstance(s, GateSample))

    @property
    def train_no_gate_collision_count(self) -> int:
        return sum(1 for s in self.train_items if isinstance(s, CollisionSample))

    @property
    def train_no_gate_orig_count(self) -> int:
        return sum(
            1
            for s in self.train_items
            if isinstance(s, NoGateSample) and not isinstance(s, CollisionSample)
        )


@dataclass
class DataBuffer:
    """
    Buffer generico per dataset (original / collision / validation).
    - items: lista di sample (raw)
    - latent_buffer: opzionale (latents_only)
    """
    items: List[BaseSample] = field(default_factory=list)
    latent_buffer: Optional[LatentBuffer] = None


@dataclass
class DataConfig:
    """
    Stato centrale della pipeline:
      - config/paths
      - parametri di training
      - buffers
      - runtime objects (device, model, optimizer, loss)
      - stats
    """
    config_json_path: Path
    config_dict: Dict[str, Any]

    model_original_root: Path
    dataset_training_root: Path
    outdir: Optional[Path]
    original_dataset_root: Path

    epochs: int
    lr: float
    weight_decay: float
    batch_size: int
    patience: int
    seed: int
    deterministic: bool

    latents_only: bool
    latent_tap: str

    data_selection: str
    use_ghost_for_selection: bool

    collision_end_frame: int

    epochs_mode: str
    train_time_budget_s: float
    eval_collisions_after_ft: bool

    save_checkpoint: bool
    save_train_summary_csv: bool
    save_selected_train_samples: bool
    save_train_val_loss_csv: bool
    force_prepare_original_dataset: bool

    data_loading_path_classification: str
    threshold: float

    # ---------------- VALIDATION ----------------
    validation: bool
    validation_root: Path

    # runtime
    device: Optional[torch.device] = None
    original_model_ckpt: Optional[Path] = None
    original_model: Optional[torch.nn.Module] = None
    fine_tuned_model: Optional[torch.nn.Module] = None

    # buffers
    original_buffer: DataBuffer = field(default_factory=DataBuffer)
    collision_buffer: DataBuffer = field(default_factory=DataBuffer)
    validation_buffer: DataBuffer = field(default_factory=DataBuffer)
    training_buffer: TrainingBuffer = field(default_factory=TrainingBuffer)

    # collision info (serve per naming + eval)
    coll_last_name: Optional[str] = None
    coll_last_root: Optional[Path] = None

    # training runtime
    bce_loss: Optional[torch.nn.Module] = None
    optimizer: Optional[torch.optim.Optimizer] = None

    # stats
    training_history: Dict[str, Any] = field(default_factory=dict)
    epochs_done: int = 0
    train_time_s: float = 0.0

    # ------------------------------------------------------------------
    # Compat / convenience
    # ------------------------------------------------------------------

    @property
    def cfg(self) -> SimpleNamespace:
        """
        Alias comodo per accedere a config_dict come attributi:
          data_config.cfg.batch_size, ecc.
        """
        return SimpleNamespace(**(self.config_dict or {}))

    @property
    def training_buffer_train_items(self) -> List[Tuple[str, str, int]]:
        return [(s.img_path, s.tof_path, int(s.label)) for s in self.training_buffer.train_items]

    @property
    def train_gate_triples(self) -> List[Tuple[str, str, int]]:
        return [
            (s.img_path, s.tof_path, int(s.label))
            for s in self.training_buffer.train_items
            if isinstance(s, GateSample)
        ]

    @property
    def train_no_gate_orig_triples(self) -> List[Tuple[str, str, int]]:
        return [
            (s.img_path, s.tof_path, int(s.label))
            for s in self.training_buffer.train_items
            if isinstance(s, NoGateSample) and not isinstance(s, CollisionSample)
        ]

    @property
    def train_no_gate_collision_triples(self) -> List[Tuple[str, str, int]]:
        return [
            (s.img_path, s.tof_path, int(s.label))
            for s in self.training_buffer.train_items
            if isinstance(s, CollisionSample)
        ]