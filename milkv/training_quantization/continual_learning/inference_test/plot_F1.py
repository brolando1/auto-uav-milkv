#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


# Nomi dei file CSV (relativi alla cartella sorgente)
CSV_FILES = {
    "original_dataset": "original_dataset.csv",
    "gate+coll1": "coll1.csv",
    "gate+coll2": "coll2.csv",
    "gate+coll3": "coll3.csv",
    "gate+coll4": "coll4.csv",
}

# Modelli nell'ordine che vuoi sulle barre
MODELS = ["original_model", "finetune_coll1", "finetune_coll2", "finetune_coll3"]


def main():
    # ---------------- ARGOMENTI CLI ----------------
    parser = argparse.ArgumentParser(
        description=(
            "Legge più CSV (uno per scenario) da una cartella sorgente "
            "e plottano gli F1 score per modello e scenario."
        )
    )
    parser.add_argument(
        "--src",
        default=None,
        help=(
            "Cartella sorgente dove si trovano i CSV "
            "(default: la cartella in cui si trova questo script)."
        ),
    )

    args = parser.parse_args()

    # Directory dove hai i CSV
    script_dir = Path(__file__).resolve().parent
    if args.src is None:
        base_dir = script_dir
    else:
        base_dir = Path(args.src).resolve()

    if not base_dir.is_dir():
        raise NotADirectoryError(
            f"La cartella sorgente non esiste o non è una directory: {base_dir}"
        )

    print(f"[INFO] Uso come cartella sorgente per i CSV: {base_dir}")

    # Dizionario: stats[scenario][model] = F1
    stats = {scenario: {m: None for m in MODELS} for scenario in CSV_FILES.keys()}

    # ---------------- LETTURA DEI CSV ----------------
    for scenario, fname in CSV_FILES.items():
        path = base_dir / fname
        if not path.is_file():
            raise FileNotFoundError(f"File non trovato: {path}")

        print(f"[INFO] Leggo: {path}")
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                model_name = row["label"].strip()
                if model_name in MODELS:
                    # se nel CSV hai ancora la colonna "F1", lascia così
                    f1 = float(row["F1"])
                    stats[scenario][model_name] = f1

    # --- forzo le tre barre "vuote" richieste ---
    stats["gate+coll1"]["finetune_coll1"] = None
    stats["gate+coll2"]["finetune_coll2"] = None
    stats["gate+coll3"]["finetune_coll3"] = None

    # set di combinazioni in cui è OK avere il valore vuoto
    allowed_missing = {
        ("gate+coll1", "finetune_coll1"),
        ("gate+coll2", "finetune_coll2"),
        ("gate+coll3", "finetune_coll3"),
    }

    # Controllo di aver letto tutti i valori (esclusi i vuoti voluti)
    for scenario, mdict in stats.items():
        for m in MODELS:
            if stats[scenario][m] is None and (scenario, m) not in allowed_missing:
                print(f"Attenzione: nessun valore per {m} in {scenario}")

    # ---------------- PLOT ----------------
    scenarios = list(CSV_FILES.keys())

    # Aumentiamo la distanza tra i gruppi di barre
    x = np.arange(len(scenarios)) * 1.4   # fattore >1 per distanziare i gruppi
    bar_width = 0.22                      # larghezza di ogni barra

    fig, ax = plt.subplots()

    for i, m in enumerate(MODELS):
        # posizione delle barre per questo modello
        offset = (i - (len(MODELS) - 1) / 2) * bar_width
        x_pos = x + offset

        # Se il valore è None (vuoto voluto), uso np.nan → barra invisibile
        values = [
            stats[sc][m] if stats[sc][m] is not None else np.nan
            for sc in scenarios
        ]

        ax.bar(x_pos, values, width=bar_width, label=m)  # nessun colore esplicito

    ax.set_xticks(x)
    ax.set_xticklabels(scenarios)
    ax.set_ylabel("F1 score")
    ax.set_title("F1 score per modello e scenario")

    # Legenda spostata fuori dal grafico, a destra
    ax.legend(
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        borderaxespad=0.0
    )

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
