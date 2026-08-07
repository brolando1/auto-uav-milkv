#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
plot_pca_selected_samples_shared_basis.py (versione "no-normalization")

Cosa fa questo script (high-level):
- Voglio visualizzare come cambiano le rappresentazioni interne (i *latenti*) del mio GateClassifier
  prima e dopo un fine-tuning.
- Per farlo:
  1) carico due checkpoint: BEFORE (prima del fine-tuning) e AFTER (dopo il fine-tuning)
  2) costruisco un set di campioni da plottare, combinando:
     - tutti i sample originali del train (gate e no_gate)
     - i sample di collisione effettivamente usati nel fine-tuning (le "no_gate_collision")
     - e uso selected_train_samples.json per distinguere "selected" vs "not_selected"
  3) faccio forward sul modello per estrarre:
     - i latenti ad un certo punto della rete (latent_tap)
     - e le probabilità p(gate) per colorare le collisioni
  4) faccio PCA 2D sui latenti e plotto due scatter:
     - BEFORE (prima del fine-tuning)
     - AFTER (dopo il fine-tuning)
"""

from __future__ import annotations

import argparse
import json
import sys
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import torch
from mpl_toolkits.axes_grid1 import make_axes_locatable

# ---------------------------------------------------------
# Setup sys.path:
# Questo script vive dentro:
#   .../training_quantization/continual_learning/inference_test
#
# Per importare moduli del repo (compat, lr_data, models, ecc.)
# aggiungo al sys.path:
#   - continual_learning/
#   - training_quantization/
# ---------------------------------------------------------

THIS_DIR = Path(__file__).resolve().parent
CONT_DIR = THIS_DIR.parent
PARENT = CONT_DIR.parent

for p in (CONT_DIR, PARENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from compat import set_device, load_model, extract_latent
from lr_data import list_pairs_under, list_pairs_recursive

# GateClassifier ETH
try:
    from models.gate_classifier_PyTorch_model import GateClassifier
except Exception as e:
    raise ImportError(
        "Impossibile importare GateClassifier da models.gate_classifier_PyTorch_model.\n"
        "Assicurati che la cartella 'training_quantization' contenga la sottocartella 'models' "
        "e che questo script sia dentro 'training_quantization/continual_learning/inference_test'."
    ) from e


# ---------------------------------------------------------
# Riproducibilità: imposto seed e modalità deterministica
# ---------------------------------------------------------

def set_seeds(seed: int = 42, deterministic: bool = True) -> None:
    """Imposta tutti i seed principali per avere risultati riproducibili."""
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
            # non tutte le versioni di torch supportano questa API
            pass


# ---------------------------------------------------------
# Piccolo helper config: in questa versione NON gestisco mean/std
# perché ho rimosso la normalizzazione.
# ---------------------------------------------------------

def _cfg_from_dict(overrides: dict | None = None) -> SimpleNamespace:
    """
    Creo un oggetto config minimale (namespace) solo con ciò che mi serve qui:
    - batch_size per fare inferenza a chunk
    - threshold (anche se in questa versione non lo uso direttamente nel plot)
    - latent_tap di default (può essere sovrascritto da CLI)
    """
    defaults = dict(
        batch_size=128,
        threshold=0.5,
        latent_tap="post_comb2",
    )
    d = defaults.copy()

    if overrides:
        for k, v in overrides.items():
            if v is None:
                continue

            if k == "batch_size":
                try:
                    d[k] = int(v)
                except Exception:
                    d[k] = v

            elif k == "threshold":
                try:
                    d[k] = float(v)
                except Exception:
                    d[k] = v

            else:
                d[k] = v

    return SimpleNamespace(**d)


# ---------------------------------------------------------
# Helpers generali
# ---------------------------------------------------------

def _resolve_path(p: str | None, base: Path) -> str | None:
    """
    Risolvo un path che può essere relativo al config.json.
    Se p è relativo, lo interpreto come base/<p>.
    """
    if p is None or str(p).strip() == "":
        return None
    pp = Path(p)
    if not pp.is_absolute():
        pp = (base / pp).resolve()
    else:
        pp = pp.resolve()
    return str(pp)


def _get_bool(d: Dict[str, Any], key: str, default: bool = False) -> bool:
    """Legge un boolean dal JSON gestendo anche stringhe tipo 'true', '1', ecc."""
    v = d.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


def _list_all_pairs_from_class_split(split_root: Path, cls: str) -> List[Tuple[str, str]]:
    """
    Ritorna tutti i pair (img, tof) dentro <split_root>/<cls>.

    Uso due strategie:
    - list_pairs_under(root): se la struttura è già quella "classica"
    - list_pairs_recursive(root): fallback, cerca ricorsivamente

    Output: lista di tuple (path_img, path_tof) come stringhe.
    """
    root = split_root / cls
    pairs_any = list_pairs_under(root) or list_pairs_recursive(root)

    out: List[Tuple[str, str]] = []
    for it in pairs_any:
        if isinstance(it, (list, tuple)) and len(it) >= 2:
            out.append((str(it[0]), str(it[1])))
    return out


# ---------------------------------------------------------
# INPUT TENSOR: conversione minima (NO NORMALIZATION)
# ---------------------------------------------------------

def _to_chw1_float_tensor(arr: Any, name: str) -> torch.Tensor:
    """
    Converto un array numpy in un tensore torch float32 con shape [1, H, W],
    senza normalizzare.

    Supporto casi comuni:
      - (H, W)                -> ok
      - (1, H, W)             -> prendo [0]
      - (H, W, 1)             -> prendo [:, :, 0]
      - (H, W, 3)             -> converto in grayscale (luma) SENZA /255

    Importante:
    - qui NON faccio né /255 né (x - mean)/std
    - quindi i .npy devono già essere coerenti con l’input atteso dal modello
    """
    a = np.asarray(arr)

    if a.ndim == 2:
        hw = a

    elif a.ndim == 3:
        # (1, H, W)
        if a.shape[0] == 1:
            hw = a[0]
        # (H, W, 1)
        elif a.shape[-1] == 1:
            hw = a[..., 0]
        # (H, W, 3) -> grayscale (luma)
        elif a.shape[-1] == 3:
            af = a.astype(np.float32, copy=False)
            hw = 0.299 * af[..., 0] + 0.587 * af[..., 1] + 0.114 * af[..., 2]
        else:
            raise ValueError(f"{name}: shape 3D non supportata {a.shape}.")

    else:
        raise ValueError(f"{name}: atteso 2D o 3D, trovato shape={a.shape}.")

    hw = hw.astype(np.float32, copy=False)
    return torch.from_numpy(hw).unsqueeze(0)  # [1, H, W]


# ---------------------------------------------------------
# Inferenza: estrazione latenti e probabilità p(gate)
# ---------------------------------------------------------

def _infer_latents_for_pairs(
    model: torch.nn.Module,
    pairs: List[Tuple[str, str]],
    cfg,
    device: torch.device,
    latent_tap: str,
    batch_size: int,
) -> np.ndarray:
    """
    Dato un elenco di coppie (img_path, tof_path), calcolo i latenti del modello
    al tap specificato (latent_tap).

    Output:
      - array numpy con shape [N, ...] (la parte ... dipende dal tap)
      - se serve fare PCA, poi flatteno a [N, D] più avanti
    """
    if not pairs:
        return np.empty((0, 1), dtype=np.float32)

    Z_chunks: List[torch.Tensor] = []
    bs = max(1, int(batch_size))

    model.eval()
    with torch.no_grad():
        buf_i: List[torch.Tensor] = []
        buf_t: List[torch.Tensor] = []

        for i, (ip, tp) in enumerate(pairs, 1):
            img_np = np.load(ip, allow_pickle=False)
            tof_np = np.load(tp, allow_pickle=False)

            bi = _to_chw1_float_tensor(img_np, "camera")  # [1,H,W]
            bt = _to_chw1_float_tensor(tof_np, "tof")     # [1,H,W]

            buf_i.append(bi)
            buf_t.append(bt)

            # quando ho riempito il batch (o sono all'ultimo sample)
            if len(buf_i) == bs or i == len(pairs):
                BI = torch.stack(buf_i, 0).to(device)  # [B,1,H,W]
                BT = torch.stack(buf_t, 0).to(device)  # [B,1,H,W]

                # estraggo latenti al tap
                Z = extract_latent(model, BI, BT, tap=latent_tap).detach().cpu()
                Z_chunks.append(Z)

                buf_i, buf_t = [], []

    Z_t = torch.cat(Z_chunks, dim=0) if Z_chunks else torch.empty((0, 1))
    return Z_t.numpy()


def _infer_probs_for_pairs(
    model: torch.nn.Module,
    pairs: List[Tuple[str, str]],
    cfg,
    device: torch.device,
    batch_size: int,
) -> np.ndarray:
    """
    Calcolo p(gate) per ogni coppia (img,tof) usando il modello completo.

    Output: array [N] float32
    """
    if not pairs:
        return np.empty((0,), dtype=np.float32)

    P_chunks: List[torch.Tensor] = []
    bs = max(1, int(batch_size))

    model.eval()
    with torch.no_grad():
        buf_i: List[torch.Tensor] = []
        buf_t: List[torch.Tensor] = []

        for i, (ip, tp) in enumerate(pairs, 1):
            img_np = np.load(ip, allow_pickle=False)
            tof_np = np.load(tp, allow_pickle=False)

            bi = _to_chw1_float_tensor(img_np, "camera")
            bt = _to_chw1_float_tensor(tof_np, "tof")

            buf_i.append(bi)
            buf_t.append(bt)

            if len(buf_i) == bs or i == len(pairs):
                BI = torch.stack(buf_i, 0).to(device)
                BT = torch.stack(buf_t, 0).to(device)

                # forward completo -> probabilità
                probs = model(BI, BT).detach().cpu().view(-1)  # [B]
                P_chunks.append(probs)

                buf_i, buf_t = [], []

    P_t = torch.cat(P_chunks, dim=0) if P_chunks else torch.empty((0,))
    return P_t.numpy().astype(np.float32)


def _resolve_checkpoint(path: Path) -> Path:
    """
    Utility per risolvere checkpoint:
    - se mi dai direttamente un file .pt -> ok
    - se mi dai una directory -> prendo il .pt più recente (mtime massimo)
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


# ---------------------------------------------------------
# PCA: implementazione minimale (standardizzazione per feature + SVD)
# ---------------------------------------------------------

def _pca_fit_2d_with_stats(X: np.ndarray):
    """
    Fit PCA 2D su X [N, D] dopo standardizzazione per feature (z-score per colonna).

    Ritorno:
      - Z2   : [N,2] proiezione
      - mean : [D] media per feature
      - std  : [D] std per feature (clamp minimo)
      - W    : [D,2] prime due componenti
      - stats: varianza spiegata (PC1, PC2, PC1+PC2) + eigvals principali
    """
    if X.ndim != 2:
        raise ValueError("X deve essere 2D (N, D)")

    N, D = X.shape

    # caso degenerato: pochi campioni
    if N < 2:
        mean = X.mean(axis=0) if N > 0 else np.zeros(D, dtype=np.float32)
        std = X.std(axis=0) if N > 0 else np.ones(D, dtype=np.float32)
        std_safe = std.copy()
        std_safe[std_safe < 1e-8] = 1.0
        Z2 = np.zeros((N, 2), dtype=np.float32)
        W = np.zeros((D, 2), dtype=np.float32)
        stats: Dict[str, Any] = {}
        return Z2, mean.astype(np.float32), std_safe.astype(np.float32), W.astype(np.float32), stats

    # standardizzazione per feature
    mean = X.mean(axis=0, keepdims=True)
    std = X.std(axis=0, keepdims=True)
    std_safe = std.copy()
    std_safe[std_safe < 1e-8] = 1.0
    Xs = (X - mean) / std_safe

    # PCA via SVD
    U, S, Vt = np.linalg.svd(Xs, full_matrices=False)

    eigvals = (S ** 2) / (N - 1)
    total_var = eigvals.sum() if eigvals.sum() > 0 else 1.0
    explained_ratio = eigvals / total_var

    W = Vt[:2].T      # [D,2]
    Z2 = Xs @ W       # [N,2]

    stats = {
        "explained_pc1": float(explained_ratio[0]) if explained_ratio.size > 0 else 0.0,
        "explained_pc2": float(explained_ratio[1]) if explained_ratio.size > 1 else 0.0,
        "explained_pc1_pc2": float(explained_ratio[:2].sum()) if explained_ratio.size > 0 else 0.0,
        "eigvals_first10": eigvals[:10].tolist(),
    }

    return (
        Z2.astype(np.float32),
        mean.squeeze(0).astype(np.float32),
        std_safe.squeeze(0).astype(np.float32),
        W.astype(np.float32),
        stats,
    )


def _project_on_base(
    X_new: np.ndarray,
    mean_base: np.ndarray,
    std_base: np.ndarray,
    W_base: np.ndarray,
) -> np.ndarray:
    """
    Proietto nuovi punti X_new [N,D] sulla base PCA già definita da:
      - mean_base, std_base: per standardizzazione coerente
      - W_base: componenti principali

    Utile quando voglio una base condivisa (es. PCA fit su BEFORE e proietto AFTER).
    """
    if X_new.ndim > 2:
        Xn = X_new.reshape(X_new.shape[0], -1)
    else:
        Xn = X_new

    Xs = (Xn - mean_base[None, :]) / std_base[None, :]
    Z2_new = Xs @ W_base
    return Z2_new.astype(np.float32)


def _print_latent_stats(X: np.ndarray, name: str) -> None:
    """
    Debug: stampo qualche statistica sulla distribuzione dei valori nei latenti.
    Mi serve per capire se ci sono outlier o range strani (soprattutto sulle collisioni).
    """
    X_flat = X.reshape(-1)

    print(f"\n=== Distribuzione valori dei latenti ({name}) ===")
    if X_flat.size == 0:
        print("  (vuoto)")
        return

    mean_val = float(X_flat.mean())
    std_val = float(X_flat.std())
    min_val = float(X_flat.min())
    max_val = float(X_flat.max())
    percentiles = np.percentile(X_flat, [0.1, 1, 5, 50, 95, 99, 99.9])

    print(f"  media      = {mean_val:.5f}")
    print(f"  std        = {std_val:.5f}")
    print(f"  min / max  = {min_val:.5f}  /  {max_val:.5f}")
    print("  percentili [0.1, 1, 5, 50, 95, 99, 99.9]:")
    print("   " + ", ".join(f"{p:.5f}" for p in percentiles))

    if std_val > 0:
        z = np.abs((X_flat - mean_val) / std_val)
        n_out_4 = int((z > 4.0).sum())
        n_out_6 = int((z > 6.0).sum())
        print(f"  outlier |z|>4: {n_out_4} su {X_flat.size}")
        print(f"  outlier |z|>6: {n_out_6} su {X_flat.size}")
    else:
        print("  std ~ 0, impossibile calcolare z-score.")


def _axis_limits(xs: List[float], ys: List[float], pad_ratio: float = 0.05):
    """
    Calcolo limiti di plot con un po' di padding.
    Se tutti i punti hanno la stessa x o y, aggiungo un delta minimo per evitare assi degeneri.
    """
    if not xs or not ys:
        return (-1.0, 1.0, -1.0, 1.0)

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    dx = (xmax - xmin) * pad_ratio
    dy = (ymax - ymin) * pad_ratio

    if dx == 0:
        dx = 0.1
    if dy == 0:
        dy = 0.1

    return (xmin - dx, xmax + dx, ymin - dy, ymax + dy)


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "PCA 2D per confrontare latenti PRIMA/DOPO fine-tuning.\n"
            "Supporta basi PCA indipendenti o condivise (before/after/joint).\n"
            "Usa selected_train_samples.json per distinguere gate/no_gate originali e collisioni.\n"
            "Colora le collisioni in base a p(gate) BEFORE/AFTER con una colorbar condivisa.\n"
            "\nNOTA: in questa versione la NORMALIZZAZIONE è rimossa: i .npy vengono solo convertiti a float32 "
            "e portati a [1,H,W]."
        )
    )

    ap.add_argument("--cfg", required=True, help="Path al file JSON di config (es. ../config.json).")
    ap.add_argument(
        "--selected",
        default=None,
        help=(
            "Path a selected_train_samples.json. "
            "Se omesso, viene preso da <outdir>/selected_train_samples.json nel config."
        ),
    )
    ap.add_argument("--model_before", required=True, help="Checkpoint (.pt) o directory del modello PRIMA del fine-tuning.")
    ap.add_argument("--model_after", required=True, help="Checkpoint (.pt) o directory del modello DOPO il fine-tuning.")
    ap.add_argument(
        "--latent_tap",
        default=None,
        help="Tap per i latenti (es. post_comb2). Se omesso, usa latent_tap dal config o 'post_comb2'.",
    )
    ap.add_argument(
        "--pca_mode",
        default="independent",
        choices=["independent", "before", "after", "joint"],
        help=(
            "Come definire la base PCA:\n"
            "  independent: PCA separata su BEFORE e su AFTER (basi diverse)\n"
            "  before     : PCA fit su BEFORE, AFTER proiettato su base BEFORE\n"
            "  after      : PCA fit su AFTER, BEFORE proiettato su base AFTER\n"
            "  joint      : PCA fit su (BEFORE+AFTER), stessa base per entrambi"
        ),
    )
    ap.add_argument(
        "--share_axes",
        default="auto",
        choices=["auto", "on", "off"],
        help=(
            "Condivisione assi tra subplot:\n"
            "  auto: independent -> assi separati, altrimenti assi condivisi\n"
            "  on  : forza sharex/sharey\n"
            "  off : disabilita sharex/sharey"
        ),
    )
    ap.add_argument("--save", default=None, help="Se specificato, salva il plot PCA in questo path invece di fare plt.show().")

    args = ap.parse_args()

    # ---------------------------------------------------------
    # 1) Carico config JSON
    # ---------------------------------------------------------
    cfg_path = Path(args.cfg).resolve()
    if not cfg_path.is_file():
        raise FileNotFoundError(f"File di config JSON non trovato: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg_json: Dict[str, Any] = json.load(f)

    base = cfg_path.parent

    # ---------------------------------------------------------
    # 2) Individuo dove stanno i dati originali (classification_fixed_root/train)
    # ---------------------------------------------------------
    class_fixed_root_s = _resolve_path(cfg_json.get("classification_fixed_root"), base)
    if class_fixed_root_s is None:
        raise ValueError("Nel config manca 'classification_fixed_root'.")

    class_fixed_root = Path(class_fixed_root_s).resolve()
    train_root = class_fixed_root / "train"

    # ---------------------------------------------------------
    # 3) Individuo selected_train_samples.json
    #    - se l'utente non lo passa, lo cerco in outdir/
    # ---------------------------------------------------------
    outdir_s = _resolve_path(cfg_json.get("outdir"), base)
    outdir_root = Path(outdir_s).resolve() if outdir_s is not None else base

    if args.selected is not None:
        selected_path = Path(args.selected).resolve()
    else:
        selected_path = outdir_root / "selected_train_samples.json"

    if not selected_path.is_file():
        raise FileNotFoundError(f"File selected_train_samples.json non trovato: {selected_path}")

    # ---------------------------------------------------------
    # 4) Setup determinismo / seed + tap per latenti
    # ---------------------------------------------------------
    deterministic = _get_bool(cfg_json, "deterministic", True)
    seed = int(cfg_json.get("seed", 42))
    latent_tap = (args.latent_tap or cfg_json.get("latent_tap") or "post_comb2").strip()

    # Config minimale: qui mi serve soprattutto batch_size
    cfg = _cfg_from_dict(
        {
            "batch_size": cfg_json.get("batch_size", 128),
            "threshold": cfg_json.get("threshold", None),
        }
    )
    batch_size = int(getattr(cfg, "batch_size", 128))

    device = set_device(deterministic=deterministic)
    if deterministic:
        set_seeds(seed, deterministic=True)

    # ---------------------------------------------------------
    # 5) Carico i due modelli (BEFORE/AFTER)
    # ---------------------------------------------------------
    ckpt_before = _resolve_checkpoint(Path(args.model_before))
    ckpt_after = _resolve_checkpoint(Path(args.model_after))

    print(f"[PCA] uso modello BEFORE: {ckpt_before}")
    print(f"[PCA] uso modello AFTER : {ckpt_after}")

    model_before = load_model(str(ckpt_before), device, GateClassifier)
    model_after = load_model(str(ckpt_after), device, GateClassifier)

    # ---------------------------------------------------------
    # 6) Carico selected_train_samples.json per costruire i gruppi
    # ---------------------------------------------------------
    with open(selected_path, "r", encoding="utf-8") as f:
        sel = json.load(f)

    def _make_key(img: str, tof: str) -> Tuple[str, str]:
        """Canonicalizzo i path con resolve(), così i confronti tra file sono robusti."""
        return (str(Path(img).resolve()), str(Path(tof).resolve()))

    sel_gate_keys = {_make_key(d["img"], d["tof"]) for d in sel.get("train_gate", [])}
    sel_nogate_orig_keys = {_make_key(d["img"], d["tof"]) for d in sel.get("train_no_gate_orig", [])}
    sel_nogate_coll = sel.get("train_no_gate_collision", [])

    print(f"[PCA] gate selezionati (orig)      = {len(sel_gate_keys)}")
    print(f"[PCA] no_gate selezionati (orig)   = {len(sel_nogate_orig_keys)}")
    print(f"[PCA] no_gate collision (train)    = {len(sel_nogate_coll)}")

    # ---------------------------------------------------------
    # 7) Costruisco i gruppi da plottare
    # ---------------------------------------------------------
    groups: Dict[str, List[Dict[str, Any]]] = {
        "gate_selected": [],
        "gate_not_selected": [],
        "no_gate_selected": [],
        "no_gate_not_selected": [],
        "no_gate_collision": [],
    }

    # 7.1) Tutti i gate originali
    gate_pairs = _list_all_pairs_from_class_split(train_root, "gate")
    for ip, tp in gate_pairs:
        key = _make_key(ip, tp)
        gname = "gate_selected" if key in sel_gate_keys else "gate_not_selected"
        groups[gname].append({"img": key[0], "tof": key[1], "label": 1})

    # 7.2) Tutti i no_gate originali
    nogate_pairs = _list_all_pairs_from_class_split(train_root, "no_gate")
    for ip, tp in nogate_pairs:
        key = _make_key(ip, tp)
        gname = "no_gate_selected" if key in sel_nogate_orig_keys else "no_gate_not_selected"
        groups[gname].append({"img": key[0], "tof": key[1], "label": 0})

    # 7.3) Solo collisioni usate in train (come da selected_train_samples.json)
    for d in sel_nogate_coll:
        key = _make_key(d["img"], d["tof"])
        groups["no_gate_collision"].append({"img": key[0], "tof": key[1], "label": 0})

    for gname, lst in groups.items():
        print(f"[PCA] gruppo '{gname}': {len(lst)} campioni")

    # ---------------------------------------------------------
    # 8) Appiattisco tutto in una lista unica: è comodo perché voglio
    #    calcolare latenti/probabilità in un solo passaggio mantenendo l’ordine.
    # ---------------------------------------------------------
    samples_all: List[Dict[str, Any]] = []
    for gname, lst in groups.items():
        for s in lst:
            samples_all.append(
                {"group": gname, "img": s["img"], "tof": s["tof"], "label": int(s["label"])}
            )

    if not samples_all:
        raise RuntimeError("Nessun campione disponibile per la PCA (samples_all è vuoto).")

    pairs_all = [(s["img"], s["tof"]) for s in samples_all]
    N = len(pairs_all)

    # ---------------------------------------------------------
    # 9) Inferenza: latenti BEFORE/AFTER
    # ---------------------------------------------------------
    print(f"[PCA] calcolo latenti BEFORE/AFTER per N={N} campioni (tap={latent_tap})...")

    Z_before = _infer_latents_for_pairs(model_before, pairs_all, cfg, device, latent_tap, batch_size)
    Z_after = _infer_latents_for_pairs(model_after, pairs_all, cfg, device, latent_tap, batch_size)

    if Z_before.shape[0] != N or Z_after.shape[0] != N:
        raise RuntimeError("Numero di latenti incoerente con numero di campioni.")

    # ---------------------------------------------------------
    # 10) Inferenza: probabilità p(gate) BEFORE/AFTER
    #     Mi servono soprattutto per colorare i punti delle collisioni.
    # ---------------------------------------------------------
    print("[PCA] calcolo p(gate) BEFORE/AFTER per tutti i campioni...")
    P_before = _infer_probs_for_pairs(model_before, pairs_all, cfg, device, batch_size)
    P_after = _infer_probs_for_pairs(model_after, pairs_all, cfg, device, batch_size)

    if P_before.shape[0] != N or P_after.shape[0] != N:
        raise RuntimeError("Numero di probabilità incoerente con numero di campioni.")

    # ---------------------------------------------------------
    # 11) Preparo i dati per PCA: voglio matrici 2D [N, D]
    # ---------------------------------------------------------
    Xb = Z_before.astype(np.float32)
    Xa = Z_after.astype(np.float32)

    if Xb.ndim > 2:
        Xb = Xb.reshape(N, -1)
        Xa = Xa.reshape(N, -1)
        print(f"[PCA] latenti reshaped a {Xb.shape} (N, D) per PCA")

    # Statistiche di debug sui latenti
    _print_latent_stats(Xb, "tutti i campioni (modello BEFORE)")

    idx_coll = [i for i, s in enumerate(samples_all) if s["group"] == "no_gate_collision"]
    if idx_coll:
        _print_latent_stats(Xb[np.array(idx_coll)], "solo collisioni (modello BEFORE)")

    # ---------------------------------------------------------
    # 12) PCA: a seconda del pca_mode scelgo come definire la base
    # ---------------------------------------------------------
    pca_mode = args.pca_mode

    if pca_mode == "independent":
        print("\n[PCA] fit PCA (modello BEFORE) con standard rescaling...")
        Z2_before, mean_b, std_b, W_b, pca_stats_b = _pca_fit_2d_with_stats(Xb)

        print("\n[PCA] fit PCA (modello AFTER) con standard rescaling...")
        Z2_after, mean_a, std_a, W_a, pca_stats_a = _pca_fit_2d_with_stats(Xa)

    elif pca_mode == "before":
        print("\n[PCA] fit PCA BASE su BEFORE, proietto AFTER sulla base di BEFORE...")
        Z2_before, mean_b, std_b, W_b, pca_stats_b = _pca_fit_2d_with_stats(Xb)
        Z2_after = _project_on_base(Xa, mean_b, std_b, W_b)
        pca_stats_a = {}

    elif pca_mode == "after":
        print("\n[PCA] fit PCA BASE su AFTER, proietto BEFORE sulla base di AFTER...")
        Z2_after, mean_a, std_a, W_a, pca_stats_a = _pca_fit_2d_with_stats(Xa)
        Z2_before = _project_on_base(Xb, mean_a, std_a, W_a)
        pca_stats_b = {}

    elif pca_mode == "joint":
        print("\n[PCA] fit PCA BASE su (BEFORE + AFTER), stessa base per entrambi...")
        X_joint = np.concatenate([Xb, Xa], axis=0)
        Z2_joint, mean_j, std_j, W_j, pca_stats_j = _pca_fit_2d_with_stats(X_joint)
        Z2_before = Z2_joint[:N]
        Z2_after = Z2_joint[N:]
        pca_stats_b = pca_stats_j
        pca_stats_a = pca_stats_j

    else:
        raise ValueError(f"pca_mode non supportato: {pca_mode}")

    # Varianza spiegata (utile come sanity check)
    if pca_stats_b:
        print("\n=== PCA (BASE: BEFORE o JOINT) ===")
        print(f"Varianza spiegata PC1 : {pca_stats_b['explained_pc1'] * 100:.2f}%")
        print(f"Varianza spiegata PC2 : {pca_stats_b['explained_pc2'] * 100:.2f}%")
        print(f"Totale PC1+PC2        : {pca_stats_b['explained_pc1_pc2'] * 100:.2f}%")
        print(f"Primi 10 autovalori   : {pca_stats_b['eigvals_first10']}")

    if pca_stats_a and pca_mode == "independent":
        print("\n=== PCA (BASE: AFTER) ===")
        print(f"Varianza spiegata PC1 : {pca_stats_a['explained_pc1'] * 100:.2f}%")
        print(f"Varianza spiegata PC2 : {pca_stats_a['explained_pc2'] * 100:.2f}%")
        print(f"Totale PC1+PC2        : {pca_stats_a['explained_pc1_pc2'] * 100:.2f}%")
        print(f"Primi 10 autovalori   : {pca_stats_a['eigvals_first10']}")

    # ---------------------------------------------------------
    # 13) Organizzo i punti per gruppo (per plottarli facilmente)
    # ---------------------------------------------------------
    group_to_xy_before: Dict[str, Tuple[List[float], List[float]]] = {g: ([], []) for g in groups.keys()}
    group_to_xy_after: Dict[str, Tuple[List[float], List[float]]] = {g: ([], []) for g in groups.keys()}

    for idx, s in enumerate(samples_all):
        gname = s["group"]

        xb_, yb_ = float(Z2_before[idx, 0]), float(Z2_before[idx, 1])
        xa_, ya_ = float(Z2_after[idx, 0]), float(Z2_after[idx, 1])

        bx, by = group_to_xy_before[gname]
        ax, ay = group_to_xy_after[gname]

        bx.append(xb_)
        by.append(yb_)
        ax.append(xa_)
        ay.append(ya_)

    # Stile grafico per gruppi non-collisione
    styles = {
        "gate_not_selected": dict(marker="o", alpha=0.15, s=10, color="tab:purple"),
        "no_gate_not_selected": dict(marker="o", alpha=0.15, s=10, color="tab:orange"),
        "gate_selected": dict(marker="^", alpha=0.9, s=15, color="tab:blue"),
        "no_gate_selected": dict(marker="s", alpha=0.9, s=15, color="tab:green"),
    }

    # Share axes: in auto, condivido gli assi quando uso una base PCA comune
    if args.share_axes == "on":
        share_axes = True
    elif args.share_axes == "off":
        share_axes = False
    else:
        share_axes = (pca_mode != "independent")

    # ---------------------------------------------------------
    # 14) Plot: due subplot, BEFORE e AFTER
    # ---------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6), sharex=share_axes, sharey=share_axes)

    # BEFORE: plotto tutti i gruppi tranne collisioni
    for gname, (xs, ys) in group_to_xy_before.items():
        if gname == "no_gate_collision" or not xs:
            continue
        ax1.scatter(xs, ys, label=gname, **styles.get(gname, {}))

    # AFTER: idem
    for gname, (xs, ys) in group_to_xy_after.items():
        if gname == "no_gate_collision" or not xs:
            continue
        ax2.scatter(xs, ys, label=gname, **styles.get(gname, {}))

    # ---------------------------------------------------------
    # 15) Collisioni: le evidenzio con marker "x" e colore = p(gate)
    #     Uso un'unica colorbar condivisa tra BEFORE e AFTER.
    # ---------------------------------------------------------
    if idx_coll:
        idx_coll_arr = np.array(idx_coll, dtype=int)

        coll_x_b = Z2_before[idx_coll_arr, 0]
        coll_y_b = Z2_before[idx_coll_arr, 1]
        coll_p_b = P_before[idx_coll_arr]

        coll_x_a = Z2_after[idx_coll_arr, 0]
        coll_y_a = Z2_after[idx_coll_arr, 1]
        coll_p_a = P_after[idx_coll_arr]

        # colorbar condivisa: stesso range per before/after
        pmin = float(min(coll_p_b.min(), coll_p_a.min()))
        pmax = float(max(coll_p_b.max(), coll_p_a.max()))

        norm = plt.Normalize(vmin=pmin, vmax=pmax)
        cmap = "viridis"

        ax1.scatter(
            coll_x_b, coll_y_b,
            c=coll_p_b, cmap=cmap, norm=norm,
            marker="x", s=35, alpha=0.9,
            label="no_gate_collision",
        )
        ax2.scatter(
            coll_x_a, coll_y_a,
            c=coll_p_a, cmap=cmap, norm=norm,
            marker="x", s=35, alpha=0.9,
            label="no_gate_collision",
        )

        # Colorbar agganciata al secondo subplot (così resta a destra)
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])

        divider = make_axes_locatable(ax2)
        cax = divider.append_axes("right", size="5%", pad=0.05)
        cbar = fig.colorbar(sm, cax=cax)
        cbar.set_label("p(gate)")

    # ---------------------------------------------------------
    # 16) Imposto limiti assi (condivisi o separati a seconda del caso)
    # ---------------------------------------------------------
    if share_axes:
        all_x = [v for g in groups.keys() for v in (group_to_xy_before[g][0] + group_to_xy_after[g][0])]
        all_y = [v for g in groups.keys() for v in (group_to_xy_before[g][1] + group_to_xy_after[g][1])]
        x0, x1, y0, y1 = _axis_limits(all_x, all_y, pad_ratio=0.05)

        ax1.set_xlim(x0, x1)
        ax1.set_ylim(y0, y1)
        ax2.set_xlim(x0, x1)
        ax2.set_ylim(y0, y1)
    else:
        all_x_b = [v for g in groups.keys() for v in group_to_xy_before[g][0]]
        all_y_b = [v for g in groups.keys() for v in group_to_xy_before[g][1]]
        all_x_a = [v for g in groups.keys() for v in group_to_xy_after[g][0]]
        all_y_a = [v for g in groups.keys() for v in group_to_xy_after[g][1]]

        xb0, xb1, yb0, yb1 = _axis_limits(all_x_b, all_y_b, pad_ratio=0.05)
        xa0, xa1, ya0, ya1 = _axis_limits(all_x_a, all_y_a, pad_ratio=0.05)

        ax1.set_xlim(xb0, xb1)
        ax1.set_ylim(yb0, yb1)
        ax2.set_xlim(xa0, xa1)
        ax2.set_ylim(ya0, ya1)

    # ---------------------------------------------------------
    # 17) Etichette, titolo, legenda, e output finale
    # ---------------------------------------------------------
    ax1.set_title(f"PRIMA fine-tuning (mode={pca_mode})")
    ax1.set_xlabel("PC1")
    ax1.set_ylabel("PC2")
    ax1.legend(loc="best", fontsize=8)

    ax2.set_title(f"DOPO fine-tuning (mode={pca_mode})")
    ax2.set_xlabel("PC1")
    ax2.legend(loc="best", fontsize=8)

    fig.suptitle(
        f"PCA 2D latenti: BEFORE vs AFTER (mode={pca_mode})\n"
        "Collisioni colorate con p(gate) (colorbar condivisa)",
        fontsize=12,
    )
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])

    if args.save is not None:
        out_p = Path(args.save).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_p, dpi=200)
        print(f"[PCA] plot PCA salvato in: {out_p}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
