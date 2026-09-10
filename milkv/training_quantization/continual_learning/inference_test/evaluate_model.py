#!/usr/bin/env python3
# Esempio:
# python3 evaluate_model.py --cfg ../config.json \
#   --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_0_finetune.pt \
#   --model_label original_model finetune_coll1 \
#   --no_gate ../../collision_dataset/test \
#   --gate ../../original_dataset/test/gate \
#   --outfile coll1

from __future__ import annotations

import argparse
import csv
import json
import sys
import random
from pathlib import Path
from typing import List, Tuple, Dict
from types import SimpleNamespace

import numpy as np
import torch


THIS_DIR = Path(__file__).resolve().parent             # .../training_quantization/continual_learning/inference_test
CONT_DIR = THIS_DIR.parent                             # .../training_quantization/continual_learning
PARENT = CONT_DIR.parent                               # .../training_quantization

for p in (CONT_DIR, PARENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Import locali
from compat import set_device, load_model
from lr_data import list_pairs_under, list_pairs_collision
from lr_eval import confusion_from_probs
from lr_utils import make_unique_run_id

# GateClassifier ETH
try:
    from model.gate_classifier_PyTorch_model import GateClassifier
except Exception as e:
    raise ImportError(
        "Impossibile importare GateClassifier da models.gate_classifier_PyTorch_model.\n"
        "Assicurati che la cartella 'training_quantization' contenga la sottocartella 'models' "
        "e che questo script sia dentro 'training_quantization/continual_learning/inference_test'."
    ) from e


# ---------------------------------------------------------------------
# Seed / determinismo
# ---------------------------------------------------------------------

def set_seeds(seed: int = 42, deterministic: bool = True) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    if deterministic:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except Exception:
            pass


def _cfg_from_dict(overrides: dict | None = None) -> SimpleNamespace:
    # In questo script NON usiamo mean/std per nessuna normalizzazione.
    defaults = dict(
        batch_size=128,
        threshold=0.89,
    )
    d = defaults.copy()
    if overrides:
        for k, v in overrides.items():
            if v is None:
                continue
            if k in ("batch_size",):
                try:
                    d[k] = int(v)
                except Exception:
                    d[k] = v
            elif k in ("threshold",):
                try:
                    d[k] = float(v)
                except Exception:
                    d[k] = v
            else:
                # ignoriamo tutto il resto (mean/std ecc)
                pass
    return SimpleNamespace(**d)


def _load_json_cfg(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_checkpoint(path: Path) -> Path:
    """
    Se path è un file .pt lo ritorna.
    Se path è una directory, ritorna il .pt con mtime più recente.
    """
    path = path.resolve()
    if path.is_file():
        return path
    if not path.exists():
        raise FileNotFoundError(f"Directory dei modelli non trovata: {path}")
    pts = [p for p in path.iterdir() if p.is_file() and p.suffix == ".pt"]
    if not pts:
        raise FileNotFoundError(f"Nessun file .pt trovato in {path}")
    pts.sort(key=lambda p: p.stat().st_mtime)
    return pts[-1]


def _list_gate_pairs(gate_arg: Path) -> List[Tuple[str, str]]:
    """
    Costruisce i pair (img,tof) per i gate.
    Se gate_arg punta a .../test/gate, usa il parent come split_root e cls="gate".
    Altrimenti prova a interpretare gate_arg come radice che contiene direttamente i run.
    """
    gate_arg = gate_arg.resolve()
    if gate_arg.name == "gate":
        split_root = gate_arg.parent
        root = split_root / "gate"
    else:
        root = gate_arg

    from lr_data import list_pairs_recursive

    pairs = list_pairs_under(root)
    if not pairs:
        pairs = list_pairs_recursive(root)
    return [(str(ip), str(tp)) for (ip, tp) in pairs]


def _list_no_gate_pairs_and_counts(no_gate_arg: Path) -> Tuple[List[Tuple[str, str]], int, int]:
    """
    Ritorna:
      - lista (img,tof) per i no_gate
      - count_orig: numero no_gate_original
      - count_coll: numero no_gate_collision
    Regole:
      - Se no_gate_arg contiene una sottocartella 'no_gate' → collision root.
      - Altrimenti viene interpretato come root di no_gate "originali".
    """
    no_gate_arg = no_gate_arg.resolve()

    cand = no_gate_arg / "no_gate"
    if cand.is_dir():
        triples = list_pairs_collision(cand)  # (ip,tp,0)
        pairs = [(ip, tp) for (ip, tp, _) in triples]
        return pairs, 0, len(pairs)

    from lr_data import list_pairs_recursive

    root = no_gate_arg
    pairs_any = list_pairs_under(root)
    if not pairs_any:
        pairs_any = list_pairs_recursive(root)
    return [(str(ip), str(tp)) for (ip, tp) in pairs_any], len(pairs_any), 0


def _metrics_from_confusion(tp: int, tn: int, fp: int, fn: int) -> Dict[str, float]:
    """
    Calcola:
      - sensitivity (TPR, classe gate)
      - specificity (TNR, classe no_gate)
      - macro_average (balanced accuracy)
      - precision, recall, F1 per la classe gate
      - macro_F1 = media delle F1 per gate e no_gate
    """
    tp = int(tp)
    tn = int(tn)
    fp = int(fp)
    fn = int(fn)

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    macro_average = (sensitivity + specificity) / 2.0

    precision_pos = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall_pos = sensitivity
    if (precision_pos + recall_pos) > 0:
        f1_pos = 2.0 * precision_pos * recall_pos / (precision_pos + recall_pos)
    else:
        f1_pos = 0.0

    tp_neg = tn
    fp_neg = fn
    fn_neg = fp

    precision_neg = tp_neg / (tp_neg + fp_neg) if (tp_neg + fp_neg) > 0 else 0.0
    recall_neg = tp_neg / (tp_neg + fn_neg) if (tp_neg + fn_neg) > 0 else 0.0
    if (precision_neg + recall_neg) > 0:
        f1_neg = 2.0 * precision_neg * recall_neg / (precision_neg + recall_neg)
    else:
        f1_neg = 0.0

    macro_f1 = 0.5 * (f1_pos + f1_neg)

    return {
        "sensitivity": sensitivity,
        "specificity": specificity,
        "macro_average": macro_average,
        "precision": precision_pos,
        "recall": recall_pos,
        "F1": f1_pos,
        "macro_F1": macro_f1,
    }


# ---------------------------------------------------------------------
# ZERO-NORMALIZATION INFERENCE
#   - NO mean/std
#   - NO /255
#   - NO crop/resize
#   - Only: make it (1,H,W) float32 to satisfy the model input type/shape
# ---------------------------------------------------------------------

def _ensure_chw1_no_norm(a: np.ndarray, *, name: str) -> np.ndarray:
    """
    Converte in [1,H,W] senza alcuna normalizzazione.
    Accetta:
      - (H,W)
      - (1,H,W)
      - (H,W,1)
    """
    arr = np.asarray(a)
    if arr.ndim == 2:
        out = arr[None, :, :]
    elif arr.ndim == 3 and arr.shape[0] == 1:
        out = arr
    elif arr.ndim == 3 and arr.shape[2] == 1:
        out = np.squeeze(arr, axis=2)[None, :, :]
    else:
        raise ValueError(f"{name}: shape non supportata (atteso (H,W) o (1,H,W) o (H,W,1)), trovato {arr.shape}")
    return out


@torch.no_grad()
def infer_probs_no_norm(
    model: torch.nn.Module,
    pairs: List[Tuple[str, str]],
    device: torch.device,
    *,
    batch_size: int = 128,
    expected_img_hw: Tuple[int, int] | None = (168, 168),
    expected_tof_hw: Tuple[int, int] | None = (21, 21),
) -> np.ndarray:
    """
    Inferenza streaming su coppie (img.npy, tof.npy) -> p(gate),
    SENZA normalizzare niente.

    Converte solo a:
      - img: torch.float32 [B,1,H,W]
      - tof: torch.float32 [B,1,H,W]
    e poi forward.
    """
    if not pairs:
        return np.empty((0,), np.float32)

    bs = max(1, int(batch_size))
    model.eval()

    probs_chunks: List[np.ndarray] = []
    buf_i: List[torch.Tensor] = []
    buf_t: List[torch.Tensor] = []

    for i, (ip, tp) in enumerate(pairs, 1):
        img_np = np.load(ip, allow_pickle=False)
        tof_np = np.load(tp, allow_pickle=False)

        img_np = _ensure_chw1_no_norm(img_np, name="IMG")
        tof_np = _ensure_chw1_no_norm(tof_np, name="TOF")

        # check shapes (opzionale ma utile per scovare mismatch)
        if expected_img_hw is not None:
            H, W = expected_img_hw
            if not (int(img_np.shape[1]) == H and int(img_np.shape[2]) == W):
                raise ValueError(f"IMG shape mismatch per {ip}: trovato {img_np.shape}, atteso (1,{H},{W})")
        if expected_tof_hw is not None:
            Ht, Wt = expected_tof_hw
            if not (int(tof_np.shape[1]) == Ht and int(tof_np.shape[2]) == Wt):
                raise ValueError(f"TOF shape mismatch per {tp}: trovato {tof_np.shape}, atteso (1,{Ht},{Wt})")

        # cast SOLO a float32, senza scaling/normalizzazione
        bi = torch.from_numpy(img_np.astype(np.float32, copy=False))
        bt = torch.from_numpy(tof_np.astype(np.float32, copy=False))

        buf_i.append(bi)
        buf_t.append(bt)

        if len(buf_i) == bs or i == len(pairs):
            BI = torch.stack(buf_i, 0).to(device, dtype=torch.float32)
            BT = torch.stack(buf_t, 0).to(device, dtype=torch.float32)
            p = model(BI, BT).view(-1).detach().cpu().numpy().astype(np.float32, copy=False)
            probs_chunks.append(p)
            buf_i, buf_t = [], []

    return np.concatenate(probs_chunks, axis=0) if probs_chunks else np.empty((0,), np.float32)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Valuta uno o più GateClassifier su un dataset gate/no_gate scelto via CLI.\n"
            "IMPORTANTE: questo script NON normalizza nulla.\n"
        )
    )
    parser.add_argument(
        "--cfg",
        required=True,
        help="Path al file JSON di config (usato solo per batch_size/threshold/seed/deterministic).",
    )
    parser.add_argument(
        "--model",
        nargs="+",
        required=True,
        help="Uno o più checkpoint (.pt) o directory che li contengono.",
    )
    parser.add_argument(
        "--model_label",
        nargs="+",
        default=None,
        help=(
            "Etichetta/e (nome riga) per i modelli, nello stesso ordine di --model. "
            "Se omesso, viene usato lo stem del file modello."
        ),
    )
    parser.add_argument(
        "--gate",
        required=True,
        help="Directory dei gate (es. ../../dataset/classification_fixed/test/gate).",
    )
    parser.add_argument(
        "--no_gate",
        required=True,
        help=(
            "Directory dei no_gate: può essere una root di collisione "
            "(es. ../../dataset_training/collisione_1) oppure una cartella no_gate classica."
        ),
    )
    parser.add_argument(
        "--outdir",
        default=None,
        help=(
            "Directory dove salvare il CSV dei risultati. "
            "Se omesso: usa config['outdir_eval'], poi config['outdir'], "
            "altrimenti la directory del primo modello."
        ),
    )
    parser.add_argument(
        "--outfile",
        default=None,
        help=(
            "Nome del file CSV di output (es. results_collision2.csv). "
            "Se omesso, viene generato automaticamente con timestamp."
        ),
    )

    args = parser.parse_args()

    if args.model_label is not None and len(args.model_label) != len(args.model):
        raise ValueError(
            f"--model_label deve avere lo stesso numero di elementi di --model "
            f"({len(args.model)} modelli, {len(args.model_label)} label)."
        )

    cfg_path = Path(args.cfg).resolve()
    if not cfg_path.is_file():
        raise FileNotFoundError(f"File di config JSON non trovato: {cfg_path}")

    cfg_json = _load_json_cfg(cfg_path)
    cfg = _cfg_from_dict(cfg_json)

    thr = float(getattr(cfg, "threshold", 0.89))
    batch_size = int(getattr(cfg, "batch_size", 128))

    deterministic = bool(cfg_json.get("deterministic", True))
    seed = int(cfg_json.get("seed", 42))

    device = set_device(deterministic=deterministic)
    if deterministic:
        set_seeds(seed, deterministic=True)

    # Coppie gate/no_gate comuni a tutti i modelli
    gate_root = Path(args.gate)
    no_gate_root = Path(args.no_gate)

    gate_pairs = _list_gate_pairs(gate_root)
    no_gate_pairs, n_no_gate_orig, n_no_gate_coll = _list_no_gate_pairs_and_counts(no_gate_root)

    n_gate = len(gate_pairs)
    n_no_gate = len(no_gate_pairs)

    if n_gate == 0:
        raise RuntimeError(f"Nessun gate trovato in: {gate_root}")
    if n_no_gate == 0:
        raise RuntimeError(f"Nessun no_gate trovato in: {no_gate_root}")

    print("----------------------------------------------------------------")
    print("[DATASET TEST]")
    print(f"  gate dir            = {gate_root}")
    print(f"  no_gate dir         = {no_gate_root}")
    print(f"  #gate               = {n_gate}")
    print(f"  #no_gate (orig)     = {n_no_gate_orig}")
    print(f"  #no_gate (collision)= {n_no_gate_coll}")
    print("----------------------------------------------------------------")
    print("[EVAL] Normalization/standardization: DISABLED (no mean/std, no /255, no crop/resize)")
    print("----------------------------------------------------------------")

    pairs_all = gate_pairs + no_gate_pairs
    labels_all = np.concatenate(
        [
            np.ones(n_gate, dtype=np.int64),
            np.zeros(n_no_gate, dtype=np.int64),
        ],
        axis=0,
    )

    results: List[Dict[str, object]] = []

    for idx, mpath_str in enumerate(args.model):
        mpath = Path(mpath_str).resolve()
        ckpt = _resolve_checkpoint(mpath)

        label = args.model_label[idx] if args.model_label is not None else ckpt.stem

        print("----------------------------------------------------------------")
        print(f"[MODEL] label='{label}'  Checkpoint: {ckpt}")

        model = load_model(str(ckpt), device, GateClassifier)
        model.eval()

        probs = infer_probs_no_norm(
            model,
            pairs_all,
            device,
            batch_size=batch_size,
            expected_img_hw=(168, 168),
            expected_tof_hw=(21, 21),
        )

        acc, tp, tn, fp, fn = confusion_from_probs(probs, labels_all, thr)
        metrics = _metrics_from_confusion(tp, tn, fp, fn)

        print(f"  acc = {acc:.6f}")
        print(f"  TP={tp} TN={tn} FP={fp} FN={fn}")
        print(
            f"  sens={metrics['sensitivity']:.6f} "
            f"spec={metrics['specificity']:.6f} "
            f"macro={metrics['macro_average']:.6f} "
            f"F1={metrics['F1']:.6f} "
            f"macro_F1={metrics['macro_F1']:.6f}"
        )

        results.append(
            {
                "label": label,
                "gate_count": n_gate,
                "no_gate_orig_count": n_no_gate_orig,
                "no_gate_collision_count": n_no_gate_coll,
                "FP": int(fp),
                "FN": int(fn),
                "TP": int(tp),
                "TN": int(tn),
                **metrics,
            }
        )

    # -------------------- Salvataggio CSV --------------------
    if args.outdir is not None:
        outdir_root = Path(args.outdir).resolve()
    elif "outdir_eval" in cfg_json:
        outdir_root = Path(cfg_json["outdir_eval"]).resolve()
    elif "outdir" in cfg_json:
        outdir_root = Path(cfg_json["outdir"]).resolve()
    else:
        first = Path(args.model[0]).resolve()
        outdir_root = (first.parent if first.is_file() else first)

    outdir_root.mkdir(parents=True, exist_ok=True)

    if args.outfile is not None and str(args.outfile).strip() != "":
        csv_name = str(args.outfile)
        if not csv_name.lower().endswith(".csv"):
            csv_name += ".csv"
    else:
        csv_name = f"evaluation_results_{make_unique_run_id()}.csv"

    csv_path = outdir_root / csv_name

    print("----------------------------------------------------------------")
    print(f"[CSV] Salvataggio risultati in: {csv_path}")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "label",
                "gate_count",
                "no_gate_orig_count",
                "no_gate_collision_count",
                "FP",
                "FN",
                "TP",
                "TN",
                "sensitivity",
                "specificity",
                "macro_average",
                "precision",
                "recall",
                "F1",
                "macro_F1",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r["label"],
                    r["gate_count"],
                    r["no_gate_orig_count"],
                    r["no_gate_collision_count"],
                    r["FP"],
                    r["FN"],
                    r["TP"],
                    r["TN"],
                    f"{r['sensitivity']:.6f}",
                    f"{r['specificity']:.6f}",
                    f"{r['macro_average']:.6f}",
                    f"{r['precision']:.6f}",
                    f"{r['recall']:.6f}",
                    f"{r['F1']:.6f}",
                    f"{r['macro_F1']:.6f}",
                ]
            )

    print("[DONE] Valutazione completata.")


if __name__ == "__main__":
    main()
