# training_quantization/continual_learning/selection_export.py

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Dict, Any
import json


def save_selected_train_samples(
    outdir: str | Path,
    train_gate: List[Tuple[str, str, int]],
    train_no_gate_orig: List[Tuple[str, str, int]],
    train_no_gate_collision: List[Tuple[str, str, int]],
) -> Path:
    """
    Salva in outdir/selected_train_samples.json i campioni
    usati nel training, in un formato compatibile con
    plot_pca_selected_samples.py:

      {
        "train_gate": [
          {"img": "...", "tof": "..."},
          ...
        ],
        "train_no_gate_orig": [
          {"img": "...", "tof": "..."},
          ...
        ],
        "train_no_gate_collision": [
          {"img": "...", "tof": "..."},
          ...
        ]
      }
    """
    outdir_p = Path(outdir).resolve()
    outdir_p.mkdir(parents=True, exist_ok=True)

    def _to_list(triples):
        return [{"img": str(ip), "tof": str(tp)} for (ip, tp, _) in triples]

    data: Dict[str, Any] = {
        "train_gate": _to_list(train_gate),
        "train_no_gate_orig": _to_list(train_no_gate_orig),
        "train_no_gate_collision": _to_list(train_no_gate_collision),
    }

    out_path = outdir_p / "selected_train_samples.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[PCA] selected_train_samples.json scritto in: {out_path}")
    return out_path
