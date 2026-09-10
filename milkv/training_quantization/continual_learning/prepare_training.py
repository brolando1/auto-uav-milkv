from __future__ import annotations

from typing import List, Tuple, TypeVar

import numpy as np
import torch

try:
    from .buffer import LatentBuffer
    from .lr_data import RawPairsDataset
    from .setup_from_config import DataConfig
    from .samples import BaseSample
except Exception:
    # Fallback quando esegui il file fuori dal package (es. python prepare_training.py)
    from buffer import LatentBuffer
    from lr_data import RawPairsDataset
    from setup_from_config import DataConfig
    from samples import BaseSample

# TypeVar “T” = qualunque sottoclasse di BaseSample
T = TypeVar("T", bound=BaseSample)

# =============================================================================
#  FUNZIONI DI SUPPORTO: shuffle, merge, subset di latents
# =============================================================================

def _make_shuffle_perm(n: int, seed: int) -> List[int]:
    """
    Crea una permutazione casuale deterministica degli indici [0..n-1].

    INPUT
    -----
    n: numero di elementi da permutare
    seed: seed base (DataConfig.seed)

    OUTPUT
    ------
    Lista di lunghezza n contenente una permutazione degli indici.
    Esempio: [2,0,1] significa: nuovo ordine = items[2], items[0], items[1]

    NOTE
    ----
    Usa seed + 999 per non “consumare” direttamente lo stesso seed usato altrove
    (scelta pratica: evita collisioni casuali tra RNG diversi nella pipeline).
    """
    rng = np.random.RandomState(int(seed) + 999)
    return rng.permutation(n).tolist()


def _shuffle_list(items: List[T], seed: int) -> Tuple[List[T], List[int]]:
    """
    Ritorna una copia shufflata della lista e la permutazione usata.

    OUTPUT
    ------
    (items_shuf, perm)
      - items_shuf: lista riordinata
      - perm: permutazione degli indici originali

    Perché ci serve perm?
    - Quando siamo in latents_only, dobbiamo shufflare *anche* i tensori Z/Y nello stesso ordine.
    """
    perm = _make_shuffle_perm(len(items), seed)
    return [items[i] for i in perm], perm


def _merge_latents(buf_a: LatentBuffer, buf_b: LatentBuffer, device: torch.device, tap: str) -> LatentBuffer:
    """
    Concatena due LatentBuffer lungo la dimensione “campioni” (dim=0).

    INPUT
    -----
    buf_a, buf_b: contengono
      - Z_all_t: [Na, ...] e [Nb, ...]
      - Y_all_t: [Na, 1]   e [Nb, 1]
    device: device finale (CPU/GPU) su cui mettere il buffer risultante
    tap: stringa (pre_fc, post_comb1, ...) da mettere in out.tap

    OUTPUT
    ------
    Un nuovo LatentBuffer con:
      - Z_all_t = cat([Za, Zb], dim=0) -> [Na+Nb, ...]
      - Y_all_t = cat([Ya, Yb], dim=0) -> [Na+Nb, 1]
      - capacity = Na+Nb
      - tap = tap
    """
    Za = buf_a.Z_all_t
    Ya = buf_a.Y_all_t
    Zb = buf_b.Z_all_t
    Yb = buf_b.Y_all_t
    if Za is None or Ya is None or Zb is None or Yb is None:
        raise RuntimeError("merge_latents: buffer senza Z_all_t/Y_all_t")

    # Assicura che tutti i tensori siano sul device desiderato (o li sposta se serve)
    Za = Za.to(device) if Za.device != device else Za
    Ya = Ya.to(device) if Ya.device != device else Ya
    Zb = Zb.to(device) if Zb.device != device else Zb
    Yb = Yb.to(device) if Yb.device != device else Yb

    # Concatena campioni (dimensione 0)
    Z = torch.cat([Za, Zb], dim=0)
    Y = torch.cat([Ya, Yb], dim=0)

    out = LatentBuffer(capacity=int(Z.shape[0]))
    out.tap = tap
    out.Z_all_t = Z
    out.Y_all_t = Y
    return out


def _permute_latents(buf: LatentBuffer, perm: List[int], device: torch.device, tap: str) -> LatentBuffer:
    """
    Riordina (shuffle) un LatentBuffer usando una permutazione `perm`.

    INPUT
    -----
    buf: LatentBuffer con Z_all_t [N,...], Y_all_t [N,1]
    perm: lista di indici lunga N (permutazione)
    device: device finale dove mettere i tensori riordinati
    tap: stringa da assegnare al buffer risultante

    OUTPUT
    ------
    Nuovo LatentBuffer con Z/Y riordinati:
      Z = Z_all_t[perm]
      Y = Y_all_t[perm]
    """
    if buf.Z_all_t is None or buf.Y_all_t is None:
        raise RuntimeError("permute_latents: buffer senza Z_all_t/Y_all_t")

    # Indici come tensore (sullo stesso device del buffer originale, per index_select efficiente)
    idx = torch.as_tensor(perm, dtype=torch.long, device=buf.Z_all_t.device)

    # index_select riordina lungo dim=0
    Z = buf.Z_all_t.index_select(0, idx).to(device)
    Y = buf.Y_all_t.index_select(0, idx).to(device)

    out = LatentBuffer(capacity=int(Z.shape[0]))
    out.tap = tap
    out.Z_all_t = Z
    out.Y_all_t = Y
    return out


def _subset_latents(buf: LatentBuffer, indices: List[int], device: torch.device, tap: str) -> LatentBuffer:
    """
    Estrae un sottoinsieme di campioni da un LatentBuffer.

    INPUT
    -----
    indices: lista di indici (non necessariamente ordinati) da tenere.

    OUTPUT
    ------
    - Se indices è vuota: buffer vuoto con tensori shape coerenti:
        Z_all_t = [0, ...], Y_all_t = [0, 1]
    - Altrimenti: buffer contenente solo quei campioni:
        Z = Z_all_t[indices], Y = Y_all_t[indices]
    """
    if buf.Z_all_t is None or buf.Y_all_t is None:
        raise RuntimeError("subset_latents: buffer senza Z_all_t/Y_all_t")

    # Caso subset vuoto: creiamo tensori vuoti con le stesse “feature dims” originali
    if not indices:
        out = LatentBuffer(capacity=0)
        out.tap = tap
        out.Z_all_t = torch.empty((0,) + tuple(buf.Z_all_t.shape[1:]), device=device, dtype=buf.Z_all_t.dtype)
        out.Y_all_t = torch.empty((0,) + tuple(buf.Y_all_t.shape[1:]), device=device, dtype=buf.Y_all_t.dtype)
        return out

    idx = torch.as_tensor(indices, dtype=torch.long, device=buf.Z_all_t.device)
    Z = buf.Z_all_t.index_select(0, idx).to(device)
    Y = buf.Y_all_t.index_select(0, idx).to(device)

    out = LatentBuffer(capacity=int(Z.shape[0]))
    out.tap = tap
    out.Z_all_t = Z
    out.Y_all_t = Y
    return out


# =============================================================================
#  FUNZIONE PRINCIPALE: prepare_training
# =============================================================================

def prepare_training(data_config: DataConfig) -> None:
    """
    Costruisce il *training buffer finale* (DataConfig.training_buffer) a partire da:
      - original_buffer (dataset “originale” selezionato)
      - collision_buffer (tutti i frame della collisione più recente)

    Obiettivo:
      1) creare una lista finale di samples (train_items) che verrà usata per logging/export
      2) creare anche il dataset effettivo da usare nel training:
         - se latents_only=True  -> training_buffer.latent_buffer (Z_all_t/Y_all_t)
         - se latents_only=False -> training_buffer.training_dataset_raw (RawPairsDataset)

    Strategia:
      - Caso “normale”: usa tutti gli original + tutti i collision, poi shuffle.
      - Caso “SPECIAL”: se i no_gate di collisione sono *meno* dei no_gate originali disponibili,
        allora *sottocampiona* gli original per bilanciare:
           total_gate == total_no_gate
        mantenendo TUTTI i frame di collisione (non scarta collisioni).

    SIDE EFFECT
    -----------
    Alla fine svuota original_buffer e collision_buffer (libera memoria),
    lasciando solo training_buffer pronto per run_training().
    """
    # Copie locali (così possiamo svuotare i buffer originali dopo)
    orig_items = list(data_config.original_buffer.items)
    coll_items = list(data_config.collision_buffer.items)

    # Sanity check: devono esistere
    if not coll_items:
        raise RuntimeError("prepare_training: collision_buffer.items è vuoto (hai chiamato prepare_collisions?).")
    if not orig_items:
        raise RuntimeError("prepare_training: original_buffer.items è vuoto (original_dataset non caricato?).")

    # Conta quanti no_gate ci sono nella collisione e quanti no_gate originali disponibili
    coll_nog = [s for s in coll_items if int(s.label) == 0]
    N_coll_nog = len(coll_nog)
    N_orig_nog_avail = sum(1 for s in orig_items if int(s.label) == 0)

    # Special case attivato quando collision no_gate < original no_gate disponibili
    # (in quel caso “ha senso” fare bilanciamento sottocampionando gli original)
    use_special_case = N_coll_nog < N_orig_nog_avail

    # -------------------------------------------------------------------------
    # CASO 1: “normale” -> prendi tutto (original + collision) e shuffle
    # -------------------------------------------------------------------------
    if not use_special_case:
        # Lista completa
        all_items: List[BaseSample] = orig_items + coll_items

        # Shuffle deterministico
        all_items_shuf, perm = _shuffle_list(all_items, seed=int(data_config.seed))

        buf = data_config.training_buffer
        buf.train_items = list(all_items_shuf)

        # ---------- Modalità latents_only: merge e shuffle dei tensori ----------
        if data_config.latents_only:
            if data_config.device is None:
                raise RuntimeError("prepare_training: device None")
            tap = str(data_config.latent_tap)

            ob = data_config.original_buffer.latent_buffer
            cb = data_config.collision_buffer.latent_buffer
            if ob is None or cb is None:
                raise RuntimeError("latents_only: manca latent_buffer in original o collision buffer.")

            # Merge tensori (prima senza shuffle)
            merged = _merge_latents(ob, cb, device=data_config.device, tap=tap)

            # perm deve essere lunga quanto merged (stesso numero di samples)
            if int(len(perm)) != int(len(merged)):
                raise RuntimeError("Mismatch perm vs merged latent length.")

            # Shuffle tensori con la stessa perm usata per i sample
            merged_shuf = _permute_latents(merged, perm, device=data_config.device, tap=tap)

            # Salva nel training buffer
            buf.latent_buffer = merged_shuf
            buf.training_dataset_raw = None

        # ---------- Modalità RAW: costruisci un Dataset che carica .npy ----------
        else:
            triples = [(s.img_path, s.tof_path, int(s.label)) for s in all_items_shuf]
            buf.training_dataset_raw = RawPairsDataset(triples)
            buf.latent_buffer = None

    # -------------------------------------------------------------------------
    # CASO 2: “SPECIAL” -> sottocampiona gli original per bilanciare classi
    # -------------------------------------------------------------------------
    else:
        rng = np.random.RandomState(int(data_config.seed) + 1234)

        # Pool degli original separati in gate e no_gate, ma preservando anche l’indice originale
        # (l’indice serve per subset_latents sul buffer dei latents originali)
        orig_gate_pool: List[Tuple[int, BaseSample]] = []
        orig_nog_pool: List[Tuple[int, BaseSample]] = []
        for i, s in enumerate(orig_items):
            if int(s.label) == 1:
                orig_gate_pool.append((i, s))
            else:
                orig_nog_pool.append((i, s))

        # In teoria collision dovrebbe essere no_gate, ma il codice supporta anche eventuali gate in collision
        coll_gate = [s for s in coll_items if int(s.label) == 1]
        avail_orig_gate = len(orig_gate_pool)
        avail_orig_nog = len(orig_nog_pool)

        # target_orig_nog: prendo un numero di no_gate originali simile ai no_gate collision
        target_orig_nog = min(avail_orig_nog, N_coll_nog)

        # total no_gate = collision no_gate + original no_gate selezionati
        target_total_nog = N_coll_nog + target_orig_nog

        # vogliamo bilanciamento: total_gate == total_no_gate
        target_total_gate = target_total_nog * 3

        # Quanti gate originali mi servono per raggiungere target_total_gate,
        # considerando che potrei già avere coll_gate dentro coll_items
        required_orig_gate = target_total_gate - len(coll_gate)

        # Se non ho abbastanza gate originali, devo abbassare il target_no_gate originale
        # per rendere possibile il bilanciamento senza scartare collisioni.
        if required_orig_gate > avail_orig_gate:
            max_total_gate = avail_orig_gate + len(coll_gate)
            new_target_orig_nog = max_total_gate - N_coll_nog

            # Se addirittura max_total_gate < N_coll_nog, non posso avere gate >= no_gate
            # senza buttare via collision no_gate -> errore “hard”
            if new_target_orig_nog < 0:
                raise RuntimeError(
                    "Impossibile bilanciare gate=no_gate senza scartare collisioni.\n"
                    f"  no_gate collisione = {N_coll_nog}\n"
                    f"  gate originali disponibili = {avail_orig_gate}\n"
                    f"  gate collisione = {len(coll_gate)}\n"
                    "Serve avere almeno tanti gate quanto i no_gate di collisione."
                )

            # Riduci quanti no_gate originali selezionare
            target_orig_nog = int(min(target_orig_nog, new_target_orig_nog))

            # Ricalcola i target e required gate
            target_total_nog = N_coll_nog + target_orig_nog
            target_total_gate = target_total_nog
            required_orig_gate = target_total_gate - len(coll_gate)

        # Se collision avesse più gate del necessario (caso strano), non chiedere gate originali
        if required_orig_gate < 0:
            required_orig_gate = 0

        # Seleziona no_gate originali (sottoinsieme casuale senza reinserimento)
        if target_orig_nog > 0:
            sel_nog_pos = rng.choice(avail_orig_nog, size=target_orig_nog, replace=False).tolist()
            sel_orig_nog = [orig_nog_pool[p] for p in sel_nog_pos]
        else:
            sel_orig_nog = []

        # Seleziona gate originali necessari
        if required_orig_gate > 0:
            sel_gate_pos = rng.choice(avail_orig_gate, size=required_orig_gate, replace=False).tolist()
            sel_orig_gate = [orig_gate_pool[p] for p in sel_gate_pos]
        else:
            sel_orig_gate = []

        # Unisci gate + no_gate originali selezionati (tenendo gli indici originali)
        sel_orig_pairs: List[Tuple[int, BaseSample]] = []
        sel_orig_pairs.extend(sel_orig_gate)
        sel_orig_pairs.extend(sel_orig_nog)

        # Lista samples originali selezionati
        sel_orig_items: List[BaseSample] = [s for (_i, s) in sel_orig_pairs]
        # Lista indici per subset_latents sull’original_buffer.latent_buffer
        sel_orig_indices: List[int] = [int(_i) for (_i, _s) in sel_orig_pairs]

        # Collision: qui NON sottocampioniamo (si tengono tutti i frame)
        sel_coll_items: List[BaseSample] = list(coll_items)
        sel_coll_indices: List[int] = list(range(len(coll_items)))  # indici 0..Nc-1 per buffer collision

        # Merge items e shuffle deterministico
        all_items: List[BaseSample] = sel_orig_items + sel_coll_items
        all_items_shuf, perm = _shuffle_list(all_items, seed=int(data_config.seed))

        buf = data_config.training_buffer
        buf.train_items = list(all_items_shuf)

        # ---------- latents_only: subset -> merge -> shuffle ----------
        if data_config.latents_only:
            if data_config.device is None:
                raise RuntimeError("prepare_training: device None")
            tap = str(data_config.latent_tap)

            ob = data_config.original_buffer.latent_buffer
            cb = data_config.collision_buffer.latent_buffer
            if ob is None or cb is None:
                raise RuntimeError("latents_only: manca latent_buffer in original o collision buffer.")

            # Sottoinsieme dei latents originali e collision (collision: tutti)
            ob_sub = _subset_latents(ob, sel_orig_indices, device=data_config.device, tap=tap)
            cb_sub = _subset_latents(cb, sel_coll_indices, device=data_config.device, tap=tap)

            # Merge dei due subset
            merged = _merge_latents(ob_sub, cb_sub, device=data_config.device, tap=tap)

            if int(len(perm)) != int(len(merged)):
                raise RuntimeError("Mismatch perm vs merged latent length.")

            # Shuffle finale in accordo a train_items
            merged_shuf = _permute_latents(merged, perm, device=data_config.device, tap=tap)
            buf.latent_buffer = merged_shuf
            buf.training_dataset_raw = None

        # ---------- RAW: dataset con triple ----------
        else:
            triples = [(s.img_path, s.tof_path, int(s.label)) for s in all_items_shuf]
            buf.training_dataset_raw = RawPairsDataset(triples)
            buf.latent_buffer = None

        # Log del comportamento “SPECIAL”
        print(
            f"[prepare_training] SPECIAL: coll_no_gate={N_coll_nog} < orig_no_gate_avail={N_orig_nog_avail} "
            f"-> seleziono orig_no_gate={target_orig_nog}, orig_gate={required_orig_gate} "
            f"(gate target = no_gate_total = {target_total_nog})"
        )

    # -------------------------------------------------------------------------
    # Pulizia: dopo aver creato training_buffer, svuota i buffer intermedi
    # -------------------------------------------------------------------------
    data_config.original_buffer.items.clear()
    data_config.original_buffer.latent_buffer = None
    data_config.collision_buffer.items.clear()
    data_config.collision_buffer.latent_buffer = None

    # Log finale (conteggi utili per debugging/monitoring)
    buf = data_config.training_buffer
    print("----------------------------------------------------------------")
    print("[prepare_training] merge completato.")
    print(f"  total train items = {buf.train_total_samples}")
    print(f"  gate              = {buf.train_gate_count}")
    print(f"  no_gate orig       = {buf.train_no_gate_orig_count}")
    print(f"  no_gate collision  = {buf.train_no_gate_collision_count}")
    print("----------------------------------------------------------------")
