from __future__ import annotations

from pathlib import Path
from typing import List, Optional

# Import “robusto”: funziona sia se esegui come package (from .xxx) sia come script (from xxx)
try:
    from .lr_data import list_pairs_collision
    from .setup_from_config import DataConfig
    from .samples import CollisionSample
    from .latent_utils_min import compute_latent_buffer_for_samples
except Exception:
    from lr_data import list_pairs_collision
    from setup_from_config import DataConfig
    from samples import CollisionSample
    from latent_utils_min import compute_latent_buffer_for_samples


def _parse_collision_index(name: str) -> Optional[int]:
    """
    Dato un nome cartella tipo "collisione_12" prova a estrarre l'indice numerico finale.

    Esempi:
      "collisione_12" -> 12
      "collisione_003" -> 3
      "collisione_last" -> None (perché "last" non è un numero)
      "altro_12" -> None (perché non inizia con collisione_)
    """
    if not name.startswith("collision_"):
        return None
    last = name.split("_")[-1]           # prende l'ultimo pezzo dopo l'underscore
    return int(last) if last.isdigit() else None


def _find_collision_dirs(root: Path) -> List[Path]:
    """
    Cerca dentro `root` tutte le sottocartelle che iniziano con "collisione_".

    Output:
      - una lista di Path, ordinata in modo “stabile”:
        * prima quelle con indice numerico (collisione_1, collisione_2, ...)
        * poi eventuali collisione_qualcosa non numeriche (collisione_last, collisione_test, ...)
    """
    root = root.resolve()
    if not root.exists():
        return []

    # prende SOLO directory del tipo collisione_*
    dirs = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("collision_")]

    def _key(p: Path):
        # se è numerico: (0, idx) -> viene prima
        # se non è numerico: (1, nome) -> viene dopo, ordinato alfabeticamente
        idx = _parse_collision_index(p.name)
        if idx is not None:
            return (0, idx)
        return (1, p.name)

    dirs.sort(key=_key)
    return dirs


def _pick_last_collision_dir(coll_dirs: List[Path]) -> Path:
    """
    Dato l'elenco di directory collisione_* sceglie la “più recente” in senso LOGICO:

    - se esistono collisione_XX numeriche: prende quella con indice più alto (max XX)
      es: collisione_3, collisione_12 -> prende collisione_12

    - altrimenti (solo non numeriche): prende l'ultima in ordine alfabetico.
    """
    numeric = []
    other = []

    for d in coll_dirs:
        idx = _parse_collision_index(d.name)
        if idx is not None:
            numeric.append((idx, d))     # (indice, path)
        else:
            other.append(d)              # collisione_nonNumero

    if numeric:
        numeric.sort(key=lambda x: x[0]) # ordina per indice
        return numeric[-1][1]            # prende quella con indice massimo

    other.sort(key=lambda p: p.name)     # fallback: ordine alfabetico
    return other[-1]


def prepare_collisions(data_config: DataConfig) -> None:
    """
    SCOPO (alto livello)
    -------------------
    1) Trova la collisione “più recente” dentro data_config.dataset_training_root,
       scegliendola come collisione_XX col numero più alto.
    2) Legge TUTTI i frame disponibili in quella collisione (no_gate).
    3) Converte ogni coppia (camera,tof) in un CollisionSample (label=0).
    4) Scrive i risultati in data_config:
         - data_config.coll_last_name
         - data_config.coll_last_root
         - data_config.collision_buffer.items
       e, se latents_only=True:
         - data_config.collision_buffer.latent_buffer  (latenti precomputati)

    OUTPUT (effetti visibili)
    ------------------------
    - Stampa a schermo una riga tipo:
        [prepare_collision] ultima collisione=collisione_12 | ALL frames=340
    - Aggiorna lo stato in data_config (buffer collisioni + info collisione scelta)
    """
    # dove stanno le collisioni nel progetto (es: ../collision_dataset/train)
    ds_root = data_config.dataset_training_root

    # 1) cerca tutte le cartelle collisione_*
    coll_dirs = _find_collision_dirs(ds_root)
    if not coll_dirs:
        # se non ne trova nessuna, tutta la pipeline non ha collisioni da usare
        raise RuntimeError(f"Nessuna collisione trovata in {ds_root}")

    # 2) sceglie la collisione “ultima” (collisione con indice più alto)
    last_dir = _pick_last_collision_dir(coll_dirs)
    last_name = last_dir.name

    # struttura attesa: collisione_X/no_gate/(camera_images + tof_distance_array)
    nog_root = last_dir / "no_gate"

    # 3) legge tutte le coppie (img,tof,label=0) dentro la collisione
    #    Nota: list_pairs_collision ritorna (img_path, tof_path, 0)
    triples = list_pairs_collision(nog_root)

    # 4) salva nel DataConfig “qual è stata l’ultima collisione usata”
    data_config.coll_last_name = last_name
    data_config.coll_last_root = last_dir

    # 5) costruisce la lista di Sample: 1 sample per frame/coppia, label=0 (no_gate collisione)
    samples = [
        CollisionSample(id=i, img_path=ip, tof_path=tp, label=0)
        for i, (ip, tp, _) in enumerate(triples)
    ]

    # 6) mette questi sample nel buffer collisioni: questa è la “materia prima” per prepare_training()
    data_config.collision_buffer.items = samples

    # stampa informativa: quanti frame userai
    print(f"[prepare_collision] ultima collisione={last_name} | ALL frames={len(samples)}")

    # 7) Se NON sei in latents_only: fine qui.
    #    In modalità raw_only, i .npy verranno letti on-the-fly dal Dataset durante il training.
    if not data_config.latents_only:
        data_config.collision_buffer.latent_buffer = None
        return

    # 8) Se sei in latents_only: devi precomputare i latenti col modello originale.
    #    Quindi ti serve che setup() sia già stato chiamato:
    #      - data_config.original_model deve esistere
    #      - data_config.device deve esistere
    if data_config.original_model is None or data_config.device is None:
        raise RuntimeError("Chiama setup() prima di prepare_collisions().")

    # 9) Precalcola latenti Z e label Y per tutti i CollisionSample:
    #    - Z_all_t: tensore [N, ...] (dipende da latent_tap)
    #    - Y_all_t: tensore [N, 1] con zeri (label=0)
    buf = compute_latent_buffer_for_samples(
        samples=samples,
        model=data_config.original_model,
        data_config=data_config,
        device=data_config.device,
        latent_tap=data_config.latent_tap,
    )

    # 10) Salva il buffer latente nel data_config:
    #     questo verrà poi mergiato con gli altri dati in prepare_training()
    data_config.collision_buffer.latent_buffer = buf
