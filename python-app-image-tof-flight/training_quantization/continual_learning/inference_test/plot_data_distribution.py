#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def leggi_train_counts(csv_path: Path):
    """
    Legge un CSV di training del tipo:

    train_gate_count,train_no_gate_orig_count,train_no_gate_collision_count,...

    Ritorna (gate_count, no_gate_count).
    """
    if not csv_path.is_file():
        raise FileNotFoundError(f"File di train non trovato: {csv_path}")

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)  # una sola riga di riepilogo

    gate = int(row["train_gate_count"])
    no_gate = int(row["train_no_gate_orig_count"]) + int(row["train_no_gate_collision_count"])
    return gate, no_gate


def leggi_test_counts(csv_path: Path):
    """
    Legge un CSV di test del tipo:

    label,gate_count,no_gate_orig_count,no_gate_collision_count,...

    I count sono uguali per tutte le righe (uno per modello), quindi
    uso solo la prima riga. Ritorna (gate_count, no_gate_count).
    """
    if not csv_path.is_file():
        raise FileNotFoundError(f"File di test non trovato: {csv_path}")

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row = next(reader)

    gate = int(row["gate_count"])
    no_gate = int(row["no_gate_orig_count"]) + int(row["no_gate_collision_count"])
    return gate, no_gate


def abbrevia_nome_collisione(dirname: str) -> str:
    """
    Cerca di estrarre 'collisionX' dal nome directory e lo mappa in 'collX'.
    Es:
      'experiments_progressive_collision1_random' -> 'coll1'
    Se non trova nulla, ritorna il nome originale.
    """
    m = re.search(r"collision(\d+)", dirname)
    if m:
        return f"coll{m.group(1)}"
    return dirname


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Plot UNICO della distribuzione dei dati di training e test.\n\n"
            "Esempio:\n"
            "  python3 plot_distribuzione_dati_unico.py \\\n"
            "    --dati_train \\\n"
            "      ../experiments_progressive_collision1_random/finetune_train_summary.csv \\\n"
            "      ../experiments_progressive_collision2_random/finetune_train_summary.csv \\\n"
            "      ../experiments_progressive_collision3_random/finetune_train_summary.csv \\\n"
            "    --dati_test \\\n"
            "      ../experiments_progressive_datasetOriginale_random/original_dataset.csv \\\n"
            "      ../experiments_progressive_datasetOriginale_random/coll1.csv \\\n"
            "      ../experiments_progressive_datasetOriginale_random/coll2.csv \\\n"
            "      ../experiments_progressive_datasetOriginale_random/coll3.csv"
        )
    )

    parser.add_argument(
        "--dati_train",
        nargs="+",
        default=[],
        help=(
            "Lista di CSV di training (finetune_train_summary.csv). "
            "Ogni file deve contenere le colonne: "
            "train_gate_count, train_no_gate_orig_count, train_no_gate_collision_count."
        ),
    )
    parser.add_argument(
        "--dati_test",
        nargs="+",
        default=[],
        help=(
            "Lista di CSV di test (es. original_dataset.csv, coll1.csv, coll2.csv...). "
            "Ogni file deve contenere le colonne: "
            "gate_count, no_gate_orig_count, no_gate_collision_count."
        ),
    )

    args = parser.parse_args()

    # ----------------- TRAIN -----------------
    all_datasets = []  # lista di (nome_gruppo, gate_count, no_gate_count)

    for p_str in args.dati_train:
        p = Path(p_str).resolve()
        gate, no_gate = leggi_train_counts(p)

        # Nome sull'asse X = coll1, coll2, coll3, ecc. + suffix "_train"
        dir_name = p.parent.name
        base_name = abbrevia_nome_collisione(dir_name)
        name = f"{base_name}_train"

        all_datasets.append((name, gate, no_gate))

    # ----------------- TEST -----------------
    for p_str in args.dati_test:
        p = Path(p_str).resolve()
        gate, no_gate = leggi_test_counts(p)

        # Nome sull'asse X = original_dataset, coll1, coll2, coll3, ecc. + suffix "_test"
        base_name = p.stem  # es: original_dataset, coll1, coll2, coll3
        name = f"{base_name}_test"

        all_datasets.append((name, gate, no_gate))

    if not all_datasets:
        print("Nessun file passato con --dati_train o --dati_test, niente da plottare.")
        return

    # ----------------- UN SOLO GRAFICO -----------------
    labels = [name for (name, _, _) in all_datasets]
    gate_counts = [g for (_, g, _) in all_datasets]
    no_gate_counts = [n for (_, _, n) in all_datasets]

    x = np.arange(len(labels)) * 1.4  # distanzia i gruppi
    bar_width = 0.35

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.2), 4))

    ax.bar(x - bar_width / 2.0, gate_counts, width=bar_width, label="gate")
    ax.bar(x + bar_width / 2.0, no_gate_counts, width=bar_width, label="no_gate")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("Number of samples")
    ax.set_title("TRAIN and TEST data distribution (gate vs no_gate)")
    ax.legend()

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
