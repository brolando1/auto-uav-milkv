# training_quantization/continual_learning2/save_statistics.py
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

import torch

try:
    from .lr_checkpoint import save_checkpoint_like_training_py
    from .selection_export import save_selected_train_samples
    from .lr_eval import eval_collisions_full
    from .setup_from_config import DataConfig
except ImportError:
    from lr_checkpoint import save_checkpoint_like_training_py
    from selection_export import save_selected_train_samples
    from lr_eval import eval_collisions_full
    from setup_from_config import DataConfig


def save_statistics(data_config: DataConfig) -> None:
    """
    Fase di SALVATAGGIO:

      - Salva il checkpoint (stile training_gate_classifier.py) se save_checkpoint=True
      - Salva finetune_train_summary.csv se save_train_summary_csv=True
      - Salva selected_train_samples.json se save_selected_train_samples=True
      - (opzionale) valuta la collisione/e post-FT
    """
    model = data_config.fine_tuned_model
    if model is None:
        raise RuntimeError("fine_tuned_model è None: hai chiamato save_statistics prima del training.")

    model_root = data_config.model_original_root
    coll_last_name = data_config.coll_last_name or "collisione_last"

    ckpt_dir = model_root if model_root.is_dir() else model_root.parent
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- CHECKPOINT ----------------
    if bool(getattr(data_config, "save_checkpoint", True)):
        ckpt_name = f"{coll_last_name}_finetune.pt"
        ckpt_out = ckpt_dir / ckpt_name

        save_checkpoint_like_training_py(
            model=model,
            ckpt_path=ckpt_out,
            epoch=data_config.epochs_done,
            val_bce=None,
            val_acc=None,
        )
        print(f"[CHECKPOINT] modello fine-tuned salvato in: {ckpt_out}")

    # ---------------- outdir export (solo se serve) ----------------
    export_outdir: Optional[Path] = None
    need_export_outdir = bool(getattr(data_config, "save_selected_train_samples", True)) or bool(
        getattr(data_config, "save_train_summary_csv", True)
    )

    if need_export_outdir:
        export_outdir = data_config.outdir if data_config.outdir is not None else ckpt_dir
        export_outdir.mkdir(parents=True, exist_ok=True)

    # ---------------- selected_train_samples.json ----------------
    if bool(getattr(data_config, "save_selected_train_samples", True)):
        assert export_outdir is not None

        # Nota: questi vengono dalle property compat di DataConfig (derivati da training_buffer.train_items)
        train_gate = getattr(data_config, "train_gate_triples", [])
        train_ng_orig = getattr(data_config, "train_no_gate_orig_triples", [])
        train_ng_coll = getattr(data_config, "train_no_gate_collision_triples", [])

        save_selected_train_samples(
            outdir=export_outdir,
            train_gate=train_gate,
            train_no_gate_orig=train_ng_orig,
            train_no_gate_collision=train_ng_coll,
        )

    # ---------------- CSV finetune_train_summary.csv ----------------
    if bool(getattr(data_config, "save_train_summary_csv", True)):
        assert export_outdir is not None

        csv_path = export_outdir / "finetune_train_summary.csv"
        buf = data_config.training_buffer

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "train_gate_count",
                    "train_no_gate_orig_count",
                    "train_no_gate_collision_count",
                    "train_total_samples",
                    "epochs_done",
                    "epochs_mode",
                    "train_time_s",
                    "data_selection_method",
                    "latents_only",
                    "use_ghost_for_selection",
                ]
            )
            w.writerow(
                [
                    int(buf.train_gate_count),
                    int(buf.train_no_gate_orig_count),
                    int(buf.train_no_gate_collision_count),
                    int(buf.train_total_samples),
                    int(data_config.epochs_done),
                    str(data_config.epochs_mode),
                    f"{float(data_config.train_time_s):.6f}",
                    str(data_config.data_selection),
                    int(bool(data_config.latents_only)),
                    int(bool(data_config.use_ghost_for_selection)),
                ]
            )

        print(f"[CSV] riepilogo training salvato in: {csv_path}")

    # ---------------- Valutazione collisioni dopo FT ----------------
    if not data_config.eval_collisions_after_ft:
        return

    print("----------------------------------------------------------------")
    print("[EVAL COLLISIONI] post fine-tuning")

    eval_device = data_config.device or torch.device("cpu")

    roots_to_eval: list[tuple[str, Path]] = []

    if data_config.coll_last_root is not None and data_config.coll_last_name is not None:
        roots_to_eval.append((data_config.coll_last_name, data_config.coll_last_root / "no_gate"))
    elif data_config.coll_last_root is not None:
        roots_to_eval.append(("collision_last", data_config.coll_last_root / "no_gate"))
    else:
        guess = data_config.dataset_training_root / (data_config.coll_last_name or "collisione_last") / "no_gate"
        roots_to_eval.append((data_config.coll_last_name or "collisione_last", guess))

    for cname, root in roots_to_eval:
        if not root.exists():
            print(f"  [WARN] collision root non trovato: {root} (skip)")
            continue

        stats = eval_collisions_full(
            model,
            root=root,
            cfg_like=data_config,
            device=eval_device,
            threshold=data_config.threshold,
        )
        print(f"  {cname}: {stats}")

    print("----------------------------------------------------------------")