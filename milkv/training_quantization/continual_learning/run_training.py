from __future__ import annotations

# Import con side-effect: imposta variabili d’ambiente “sicure” (es. determinismo, thread, ecc.)
# Se il modulo non c’è (esecuzione fuori package), non blocca l’esecuzione.
try:
    from . import env_safety  # type: ignore  # noqa: F401
except Exception:
    try:
        import env_safety  # type: ignore  # noqa: F401
    except Exception:
        pass

import math
import time
from typing import Any, Dict, Tuple, Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

try:
    # forward_from_latent: dato un “latent” (attivazione interna) produce la probabilità finale
    # DataConfig: contenitore di tutta la config + buffer + modello + optimizer/loss, ecc.
    from .compat import forward_from_latent
    from .setup_from_config import DataConfig
except ImportError:
    from compat import forward_from_latent
    from setup_from_config import DataConfig


# =============================================================================
#  FUNZIONI UTILI: parsing batch, moving su device, formattazione epoch
# =============================================================================

def _unpack_batch(batch):
    """
    Estrae (img, tof, y) da un batch prodotto dal DataLoader.

    Supporta due formati tipici:
      - (img, tof, y)                 -> len=3
      - (img, tof, y, extra_stuff)    -> len=4 (ignora l’ultimo campo)

    OUTPUT
    ------
    img: tensor [B,1,168,168] (tipico)
    tof: tensor [B,1,21,21]   (tipico)
    y  : tensor [B] o [B,1]   -> poi verrà forzato a [B,1]
    """
    if isinstance(batch, (list, tuple)):
        if len(batch) == 4:
            img, tof, y, _ = batch
            return img, tof, y
        if len(batch) == 3:
            img, tof, y = batch
            return img, tof, y

    # Se arriva un formato inatteso, falliamo con messaggio chiaro
    raise ValueError(
        f"Formato batch inatteso: type={type(batch)} "
        f"len={len(batch) if isinstance(batch,(list,tuple)) else 'n/a'}"
    )


def _to_device(img: torch.Tensor, tof: torch.Tensor, y: torch.Tensor, device: torch.device):
    """
    Sposta i tensori su device e impone dtype float32.
    Inoltre y viene reshaped in [B,1], perché BCELoss (come usata qui) si aspetta shape compatibili.

    OUTPUT
    ------
    img, tof, y su device, float32, y in shape [B,1]
    """
    img = img.to(device, dtype=torch.float32, non_blocking=True)
    tof = tof.to(device, dtype=torch.float32, non_blocking=True)
    y = y.to(device, dtype=torch.float32, non_blocking=True).view(-1, 1)
    return img, tof, y


def _epoch_str(ep_local: int, epochs_local: int, base: int) -> str:
    """
    Crea una stringa “carina” da stampare per l’epoch.

    - Se epochs_local<=1: usa un contatore assoluto (base + ep_local) a 3 cifre: 001, 002, ...
      (utile per modalità budget dove non sai “a priori” quante epoche fai)
    - Altrimenti: "ep/epochs", es: "03/10"
    """
    if epochs_local <= 1:
        return f"{base + ep_local:03d}"
    else:
        return f"{ep_local:02d}/{epochs_local}"


# =============================================================================
#  BatchNorm handling: dopo un “tap” alcuni moduli devono stare in train()
# =============================================================================

def _force_bn_modes_after_tap(model: nn.Module, tap: str) -> None:
    """
    Gestione BatchNorm quando alleni “solo” la parte finale della rete (latents_only).

    Idea:
    - Se stai addestrando dal tap in poi, alcuni BatchNorm “dopo il tap” devono stare in train()
      perché fanno parte della porzione che stai aggiornando.
    - Tutti gli altri BatchNorm (prima del tap) restano in eval() per non cambiare statistiche.

    Regola usata qui:
    - tap=post_merge  -> train BN nei blocchi combined_block_1 e combined_block_2
    - tap=post_comb1  -> train BN solo in combined_block_2
    - tap=post_comb2/pre_fc -> nessun BN post-tap (o non rilevante) -> tutti eval
    """
    if tap == "post_merge":
        prefixes = ("combined_block_1", "combined_block_2")
    elif tap == "post_comb1":
        prefixes = ("combined_block_2",)
    elif tap in ("post_comb2", "pre_fc"):
        prefixes = tuple()
    else:
        prefixes = tuple()

    for nmod, msub in model.named_modules():
        if isinstance(msub, nn.BatchNorm2d):
            if any(nmod.startswith(pref) for pref in prefixes):
                msub.train()
            else:
                msub.eval()


# =============================================================================
#  VALUTAZIONE (loss BCE) in modalità LATENTS e in modalità RAW
# =============================================================================

@torch.no_grad()
def _eval_latents_bce(
    model: nn.Module,
    buffer,
    device: torch.device,
    *,
    bce: nn.Module,
    batch_size: int,
    tap: str,
) -> float:
    """
    Calcola la BCE media su un LatentBuffer (Z_all_t, Y_all_t).

    INPUT
    -----
    buffer: oggetto con attributi:
      - Z_all_t: tensor [N, D] o [N,C,H,W] (dipende dal tap)
      - Y_all_t: tensor [N,1]
    tap: indica come interpretare Z e come fare forward (forward_from_latent)

    OUTPUT
    ------
    loss media (float). Se buffer vuoto -> NaN.
    """
    Z_all_t = getattr(buffer, "Z_all_t", None)
    Y_all_t = getattr(buffer, "Y_all_t", None)
    if Z_all_t is None or Y_all_t is None or int(Z_all_t.shape[0]) == 0:
        return float("nan")

    # Assicura che i tensori siano sul device di training
    Z_all_t = Z_all_t.to(device) if Z_all_t.device != device else Z_all_t
    Y_all_t = Y_all_t.to(device) if Y_all_t.device != device else Y_all_t

    N = int(Z_all_t.shape[0])
    bs = max(1, int(batch_size))
    model.eval()

    # running = somma(loss_batch * batch_size)
    running = 0.0
    n = 0
    for start in range(0, N, bs):
        end = min(N, start + bs)
        Z = Z_all_t[start:end]
        y = Y_all_t[start:end]

        # forward “dalla rappresentazione latente” fino alla probabilità finale
        p = forward_from_latent(model, Z, tap=tap)
        loss = bce(p, y)

        running += float(loss.item()) * int(y.size(0))
        n += int(y.size(0))

    return running / max(1, n)


@torch.no_grad()
def _eval_raw_bce(
    model: nn.Module,
    dataset,
    device: torch.device,
    *,
    bce: nn.Module,
    batch_size: int,
) -> float:
    """
    Calcola la BCE media su un dataset RAW (carica img/tof reali).

    OUTPUT
    ------
    loss media (float)
    """
    loader = DataLoader(
        dataset,
        batch_size=max(1, int(batch_size)),
        shuffle=False,
        num_workers=0,
        pin_memory=False,
        persistent_workers=False,
    )
    model.eval()
    running = 0.0
    n = 0
    for batch in loader:
        img, tof, y = _unpack_batch(batch)
        img, tof, y = _to_device(img, tof, y, device)

        # forward completo del modello (img,tof -> prob)
        p = model(img, tof)
        loss = bce(p, y)

        running += float(loss.item()) * int(y.size(0))
        n += int(y.size(0))
    return running / max(1, n)


# =============================================================================
#  TRAINING: modalità LATENTS_ONLY
# =============================================================================

def _train_latents(
    model: nn.Module,
    buffer,
    device: torch.device,
    *,
    bce: nn.Module,
    optimizer: torch.optim.Optimizer,
    epochs_mode: str,
    epochs: int,
    batch_size: int,
    latent_tap: str | None,
    train_time_budget_s: float,
    history: Dict[str, Any],
    global_t0: Optional[float],
    print_epoch_base: int = 0,
    val_buffer=None,
    do_validation: bool = False,
    patience: int = 0,
) -> Tuple[nn.Module, int]:
    """
    TRAINING "LATENTS ONLY" (replay sui latenti)
    ===========================================

    Invece di fare forward completo (img,tof -> prob), questa funzione allena usando
    latenti Z già precomputati (estratti da un modello "base" ad un certo tap).

    INPUT ATTESI
    ------------
    buffer LatentBuffer DEVE contenere:
      - buffer.Z_all_t: torch.Tensor di shape:
            * tap = "pre_fc"      -> [N, D]
            * tap = "post_comb2"  -> [N, C, H, W]
            * tap = "post_comb1"  -> [N, C, H, W]
            * tap = "post_merge"  -> [N, C, H, W]
        dove N = numero di campioni nel buffer.
      - buffer.Y_all_t: torch.Tensor di shape [N, 1]
        contenente label float 0/1 (0=no_gate, 1=gate)
      - opzionale buffer.tap: str (tap con cui sono stati creati i latenti)

    model: nn.Module
      - viene aggiornato SOLO sui parametri che l'optimizer sta ottimizzando
        (tipicamente quelli con requires_grad=True).
      - forward usato qui NON è model(img,tof), ma forward_from_latent(model, Z, tap).

    OUTPUT
    ------
    (model_fine_tuned, epochs_done)
      - model_fine_tuned: modello aggiornato
      - epochs_done: quante epoche ha effettivamente eseguito (può essere < epochs se early stop,
        o "quante ne sono entrate nel budget" se epochs_mode="budget")
    """
    import numpy as np

    # ---------------------------------------------------------------------
    # 0) Controlli di sanità sul buffer
    # ---------------------------------------------------------------------
    # len(buffer) deve essere definito (LatentBuffer implementa __len__)
    if buffer is None or len(buffer) == 0:
        raise RuntimeError("latents_only=True ma il buffer è vuoto o mancante.")

    # ---------------------------------------------------------------------
    # 1) Inizializza history (log) per questo training run
    # ---------------------------------------------------------------------
    # Nota: questa funzione SOVRASCRIVE le liste (clear) perché ogni run deve avere history pulita
    t_setup0 = time.perf_counter()

    history["mode"] = "latents_only" if epochs_mode == "fixed" else "latents_only_budget"
    history["epoch"].clear()                  # lista: [1,2,3,...]
    history["train_loss"].clear()             # lista: loss media per epoca
    history["val_loss"].clear()               # lista: val_loss per epoca (o None)
    history["coll_loss"].clear()              # non usata qui -> sempre None
    history["samples_raw_per_epoch"].clear()  # raw non usato -> 0
    history["samples_replay_per_epoch"].clear()  # qui replay=numero di latenti visti
    history["steps_per_epoch"] = None         # valore scalare settato dopo

    # Tap effettivo:
    # - se latent_tap è passato -> usa quello
    # - altrimenti usa buffer.tap se esiste
    # - fallback -> "pre_fc"
    tap = str(latent_tap) if latent_tap is not None else getattr(buffer, "tap", "pre_fc")

    t_setup1 = time.perf_counter()
    print(f"[timing/latents_only] setup_step1(history+tap) = {t_setup1 - t_setup0:.3f}s")

    # ---------------------------------------------------------------------
    # 2) Estrae Z e Y dal buffer e controlla le shape
    # ---------------------------------------------------------------------
    # Z_all_t: [N, D] oppure [N, C, H, W] a seconda del tap
    # Y_all_t: [N, 1]
    Z_all_t: torch.Tensor | None = getattr(buffer, "Z_all_t", None)
    Y_all_t: torch.Tensor | None = getattr(buffer, "Y_all_t", None)
    if Z_all_t is None or Y_all_t is None:
        raise RuntimeError("latents_only: Z_all_t/Y_all_t mancanti nel buffer.")

    # Sposta su device (GPU/CPU) se necessario:
    # dopo questa fase, Z_all_t e Y_all_t saranno sullo stesso device del modello
    if Z_all_t.device != device:
        Z_all_t = Z_all_t.to(device)
    if Y_all_t.device != device:
        Y_all_t = Y_all_t.to(device)

    # N = numero campioni nel buffer
    buf_len = int(Z_all_t.shape[0])
    if buf_len == 0:
        raise RuntimeError("latents_only: buffer vuoto.")

    # ---------------------------------------------------------------------
    # 3) Calcola gli step per epoca
    # ---------------------------------------------------------------------
    # steps_per_epoch = ceil(N / batch_size)
    # Esempio: N=1000, batch=128 -> 8 step (copri tutto circa una volta)
    steps_per_epoch = max(1, math.ceil(buf_len / max(1, batch_size)))
    history["steps_per_epoch"] = int(steps_per_epoch)

    t_setup2 = time.perf_counter()
    print(f"[timing/latents_only] setup_step2(buffer_to_device+steps_per_epoch) = {t_setup2 - t_setup1:.3f}s")

    # ---------------------------------------------------------------------
    # 4) Early stopping (solo se validation abilitata + patience>0)
    # ---------------------------------------------------------------------
    es_enabled = bool(do_validation) and int(patience) > 0
    best_val = float("inf")   # miglior val_loss (più bassa = meglio)
    best_epoch = 0            # epoca in cui è stata vista la best_val
    bad_epochs = 0            # contatore epoche senza miglioramento
    best_state = None         # snapshot dei pesi migliori (state_dict) su CPU
    total_ep = 0              # contatore epoche effettivamente fatte (anche in budget mode)

    def _is_nan(x: float) -> bool:
        # NaN è l'unico numero tale che x != x
        return x != x

    def _maybe_es_step(val_loss: Optional[float], ep_label: str) -> bool:
        """
        Aggiorna stato di early stopping.

        Input:
          - val_loss: float (loss validation) oppure None
          - ep_label: stringa usata nei print

        Output:
          - True  -> fermati (early stopping)
          - False -> continua

        Regole:
          - se val_loss migliora: salva best_state (copia su CPU) e resetta bad_epochs
          - se non migliora: incrementa bad_epochs
          - se bad_epochs >= patience: stop
        """
        nonlocal best_val, best_epoch, bad_epochs, best_state, total_ep

        if not es_enabled or val_loss is None:
            return False

        v = float(val_loss)
        if _is_nan(v):
            return False

        # Miglioramento: v più piccolo
        if v < best_val:
            best_val = v
            best_epoch = total_ep
            bad_epochs = 0

            # Snapshot pesi migliori:
            # - detach -> non serve grafo
            # - cpu()  -> salviamo su CPU per non tenere memoria GPU
            # - clone() -> copia reale
            best_state = {k: t.detach().cpu().clone() for k, t in model.state_dict().items()}
            return False

        # Nessun miglioramento
        bad_epochs += 1
        if bad_epochs >= int(patience):
            print(
                f"  [early_stop] stop at epoch {ep_label}: "
                f"no improvement for {bad_epochs}/{patience} | best_val={best_val:.6f} at epoch {best_epoch}"
            )
            return True

        return False

    # =========================================================================
    # 5) MODALITÀ "FIXED": epoche fisse
    # =========================================================================
    if epochs_mode == "fixed":
        stopped = False

        # ep è il contatore locale 1..epochs (solo per stampa)
        for ep in range(1, epochs + 1):
            ep_t0 = time.perf_counter()

            # Metti il modello in training mode (dropout/bn in train di default)
            model.train()

            # IMPORTANTISSIMO:
            # Questa funzione:
            # - mette train solo le BN "dopo il tap"
            # - mette eval le BN "prima del tap"
            _force_bn_modes_after_tap(model, tap)

            running, n_lat = 0.0, 0  # running: somma loss pesata, n_lat: #campioni visti

            # perm: permutazione casuale degli indici 0..N-1 per shuffle per-epoca
            perm = np.random.permutation(buf_len)

            # Loop sugli step dell'epoca
            for step in range(steps_per_epoch):
                start = step * batch_size
                end = min(buf_len, start + batch_size)
                if start >= end:
                    continue

                idx_batch = perm[start:end]     # shape: [B] (numpy)
                if len(idx_batch) == 0:
                    continue

                # Trasforma gli indici in torch.LongTensor su device
                # idx_t shape: [B]
                idx_t = torch.as_tensor(idx_batch, dtype=torch.long, device=device)

                # Estrae il batch con index_select lungo dim=0
                # Z shape:
                #   - tap="pre_fc"     -> [B, D]
                #   - tap conv-style   -> [B, C, H, W]
                # yb shape: [B, 1]
                Z = Z_all_t.index_select(0, idx_t)
                yb = Y_all_t.index_select(0, idx_t)

                # Forward "dal tap in poi":
                # p_replay shape: [B, 1] con valori in [0,1]
                p_replay = forward_from_latent(model, Z, tap=tap)

                # BCE loss:
                # loss è scalare (0-dim tensor)
                loss = bce(p_replay, yb)

                # Backprop + update
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()

                # Accumula loss per media pesata
                running += float(loss.item()) * int(yb.size(0))
                n_lat += int(yb.size(0))

            total_ep += 1
            avg_loss = running / max(1, n_lat)  # loss media sull'epoca

            # ---------------- VALIDAZIONE (opzionale) ----------------
            val_loss = None
            if do_validation and val_buffer is not None and len(val_buffer) > 0:
                # _eval_latents_bce usa:
                #   - Z_val: [Nv, ...]
                #   - Y_val: [Nv, 1]
                # e calcola BCE media, senza gradienti
                val_loss = _eval_latents_bce(model, val_buffer, device, bce=bce, batch_size=batch_size, tap=tap)

            ep_t1 = time.perf_counter()
            ep_str = _epoch_str(ep, epochs_local=epochs, base=print_epoch_base)

            # Stampa log epoca
            if val_loss is None:
                print(f"  [latents_only/fixed] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | train_loss={avg_loss:.6f}")
            else:
                print(
                    f"  [latents_only/fixed] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | "
                    f"train_loss={avg_loss:.6f} | val_loss={float(val_loss):.6f}"
                )

            # Salva in history
            history["epoch"].append(total_ep)
            history["train_loss"].append(avg_loss)
            history["val_loss"].append(val_loss)
            history["coll_loss"].append(None)
            history["samples_raw_per_epoch"].append(0)          # RAW non usato in modalità latenti
            history["samples_replay_per_epoch"].append(int(n_lat))  # replay = #latenti visti

            # Early stopping (se abilitato)
            if _maybe_es_step(val_loss, ep_str):
                stopped = True
                break

        # Se early stopping era attivo, ripristina i pesi migliori
        if es_enabled and best_state is not None:
            model.load_state_dict(best_state, strict=True)
            history["early_stop"] = {
                "enabled": True,
                "patience": int(patience),
                "best_epoch": int(best_epoch),
                "best_val_loss": float(best_val),
                "stopped_epoch": int(total_ep) if stopped else None,
            }
        else:
            history["early_stop"] = {"enabled": False}

        model.eval()
        return model, total_ep

    # =========================================================================
    # 6) MODALITÀ "BUDGET": allena finché non scade il tempo
    # =========================================================================
    if train_time_budget_s <= 0.0:
        raise ValueError("epochs_mode='budget' ma train_time_budget_s <= 0.")
    if global_t0 is None:
        global_t0 = time.perf_counter()

    stopped = False
    while True:
        ep_t0 = time.perf_counter()

        model.train()
        _force_bn_modes_after_tap(model, tap)

        running, n_lat = 0.0, 0
        perm = np.random.permutation(buf_len)

        for step in range(steps_per_epoch):
            start = step * batch_size
            end = min(buf_len, start + batch_size)
            if start >= end:
                continue

            idx_batch = perm[start:end]
            if len(idx_batch) == 0:
                continue

            idx_t = torch.as_tensor(idx_batch, dtype=torch.long, device=device)

            # Z: [B, D] oppure [B, C, H, W]
            # yb: [B, 1]
            Z = Z_all_t.index_select(0, idx_t)
            yb = Y_all_t.index_select(0, idx_t)

            # p_replay: [B, 1]
            p_replay = forward_from_latent(model, Z, tap=tap)
            loss = bce(p_replay, yb)

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()

            running += float(loss.item()) * int(yb.size(0))
            n_lat += int(yb.size(0))

        total_ep += 1
        avg_loss = running / max(1, n_lat)

        val_loss = None
        if do_validation and val_buffer is not None and len(val_buffer) > 0:
            val_loss = _eval_latents_bce(model, val_buffer, device, bce=bce, batch_size=batch_size, tap=tap)

        ep_t1 = time.perf_counter()
        ep_str = _epoch_str(total_ep, epochs_local=0, base=print_epoch_base)

        if val_loss is None:
            print(f"[budget/latents_only] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | train_loss={avg_loss:.6f}")
        else:
            print(
                f"[budget/latents_only] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | "
                f"train_loss={avg_loss:.6f} | val_loss={float(val_loss):.6f}"
            )

        history["epoch"].append(total_ep)
        history["train_loss"].append(avg_loss)
        history["val_loss"].append(val_loss)
        history["coll_loss"].append(None)
        history["samples_raw_per_epoch"].append(0)
        history["samples_replay_per_epoch"].append(int(n_lat))

        # Early stopping (eventuale)
        if _maybe_es_step(val_loss, ep_str):
            stopped = True
            break

        # Stop per budget tempo globale
        if (time.perf_counter() - global_t0) >= float(train_time_budget_s):
            break

    # Ripristina best_state se early stopping era attivo
    if es_enabled and best_state is not None:
        model.load_state_dict(best_state, strict=True)
        history["early_stop"] = {
            "enabled": True,
            "patience": int(patience),
            "best_epoch": int(best_epoch),
            "best_val_loss": float(best_val),
            "stopped_epoch": int(total_ep) if stopped else None,
        }
    else:
        history["early_stop"] = {"enabled": False}

    model.eval()
    return model, total_ep


# =============================================================================
#  TRAINING: modalità RAW (img/tof veri)
# =============================================================================

def _train_raw(
    model: nn.Module,
    dataset,
    device: torch.device,
    *,
    bce: nn.Module,
    optimizer: torch.optim.Optimizer,
    epochs_mode: str,
    epochs: int,
    batch_size: int,
    train_time_budget_s: float,
    history: Dict[str, Any],
    global_t0: Optional[float],
    print_epoch_base: int = 0,
    val_dataset=None,
    do_validation: bool = False,
    patience: int = 0,
) -> Tuple[nn.Module, int]:
    """
    TRAINING "RAW" (img/tof -> prob)
    ===============================

    Qui il modello viene allenato con forward COMPLETO:
        (img, tof) -> model(img,tof) -> p -> BCE(p,y)

    INPUT ATTESI
    ------------
    dataset: oggetto indicizzabile usato da DataLoader che produce batch in uno di questi formati:
      - (img, tof, y)
      - (img, tof, y, extra)

    Shape attese per batch:
      - img: [B, 1, 168, 168]  (float32)
      - tof: [B, 1,  21,  21]  (float32)
      - y:   [B, 1]            (float32 0/1)   (qui viene forzato a [B,1] da _to_device)

    OUTPUT
    ------
    (model_fine_tuned, epochs_done)
    """
    if dataset is None or len(dataset) == 0:
        raise RuntimeError("RAW training: dataset vuoto o mancante.")

    # ---------------------------------------------------------------------
    # 1) Init history (pulizia log del run)
    # ---------------------------------------------------------------------
    t_setup0 = time.perf_counter()

    history["mode"] = "raw_only" if epochs_mode == "fixed" else "raw_only_budget"
    history["epoch"].clear()
    history["train_loss"].clear()
    history["val_loss"].clear()
    history["coll_loss"].clear()
    history["samples_raw_per_epoch"].clear()
    history["samples_replay_per_epoch"].clear()
    history["steps_per_epoch"] = None

    t_setup1 = time.perf_counter()
    print(f"[timing/raw_only] setup_step1(history) = {t_setup1 - t_setup0:.3f}s")

    # ---------------------------------------------------------------------
    # 2) DataLoader
    # ---------------------------------------------------------------------
    # shuffle=True => rimescola i campioni ad ogni epoca
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=0,
        pin_memory=False,
        persistent_workers=False,
    )

    # steps_per_epoch = numero di batch prodotti dal loader
    steps_per_epoch = max(1, len(loader))
    history["steps_per_epoch"] = int(steps_per_epoch)

    t_setup2 = time.perf_counter()
    print(f"[timing/raw_only] setup_step2(dataloader+steps_per_epoch) = {t_setup2 - t_setup1:.3f}s")

    # ---------------------------------------------------------------------
    # 3) Early stopping (come in _train_latents)
    # ---------------------------------------------------------------------
    es_enabled = bool(do_validation) and int(patience) > 0
    best_val = float("inf")
    best_epoch = 0
    bad_epochs = 0
    best_state = None
    total_ep = 0

    def _is_nan(x: float) -> bool:
        return x != x

    def _maybe_es_step(val_loss: Optional[float], ep_label: str) -> bool:
        nonlocal best_val, best_epoch, bad_epochs, best_state, total_ep
        if not es_enabled or val_loss is None:
            return False
        v = float(val_loss)
        if _is_nan(v):
            return False
        if v < best_val:
            best_val = v
            best_epoch = total_ep
            bad_epochs = 0
            best_state = {k: t.detach().cpu().clone() for k, t in model.state_dict().items()}
            return False
        bad_epochs += 1
        if bad_epochs >= int(patience):
            print(
                f"  [early_stop] stop at epoch {ep_label}: "
                f"no improvement for {bad_epochs}/{patience} | best_val={best_val:.6f} at epoch {best_epoch}"
            )
            return True
        return False

    # ---------------------------------------------------------------------
    # 4) FIXED
    # ---------------------------------------------------------------------
    if epochs_mode == "fixed":
        stopped = False
        for ep in range(1, epochs + 1):
            ep_t0 = time.perf_counter()
            model.train()

            running, n_raw = 0.0, 0

            # Ogni "batch" è tipicamente:
            #   img: [B,1,168,168], tof: [B,1,21,21], y: [B] o [B,1]
            for batch in loader:
                img, tof, y = _unpack_batch(batch)

                # _to_device forzerà:
                #   img -> float32 su device, shape [B,1,168,168]
                #   tof -> float32 su device, shape [B,1,21,21]
                #   y   -> float32 su device, shape [B,1]
                img, tof, y = _to_device(img, tof, y, device)

                # Forward completo:
                # p_real: [B,1] (sigmoid)
                p_real = model(img, tof)

                # loss scalare
                loss = bce(p_real, y)

                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()

                running += float(loss.item()) * int(y.size(0))
                n_raw += int(y.size(0))

            total_ep += 1
            avg_loss = running / max(1, n_raw)

            # Validazione raw (opzionale): calcola BCE media su val_dataset
            val_loss = None
            if do_validation and val_dataset is not None and len(val_dataset) > 0:
                val_loss = _eval_raw_bce(model, val_dataset, device, bce=bce, batch_size=batch_size)

            ep_t1 = time.perf_counter()
            ep_str = _epoch_str(ep, epochs_local=epochs, base=print_epoch_base)

            if val_loss is None:
                print(f"  [raw_only/fixed] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | train_loss={avg_loss:.6f}")
            else:
                print(
                    f"  [raw_only/fixed] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | "
                    f"train_loss={avg_loss:.6f} | val_loss={float(val_loss):.6f}"
                )

            history["epoch"].append(total_ep)
            history["train_loss"].append(avg_loss)
            history["val_loss"].append(val_loss)
            history["coll_loss"].append(None)
            history["samples_raw_per_epoch"].append(int(n_raw))   # qui RAW usato davvero
            history["samples_replay_per_epoch"].append(0)         # replay non usato

            if _maybe_es_step(val_loss, ep_str):
                stopped = True
                break

        if es_enabled and best_state is not None:
            model.load_state_dict(best_state, strict=True)
            history["early_stop"] = {
                "enabled": True,
                "patience": int(patience),
                "best_epoch": int(best_epoch),
                "best_val_loss": float(best_val),
                "stopped_epoch": int(total_ep) if stopped else None,
            }
        else:
            history["early_stop"] = {"enabled": False}

        model.eval()
        return model, total_ep

    # ---------------------------------------------------------------------
    # 5) BUDGET
    # ---------------------------------------------------------------------
    if train_time_budget_s <= 0.0:
        raise ValueError("epochs_mode='budget' ma train_time_budget_s <= 0.")
    if global_t0 is None:
        global_t0 = time.perf_counter()

    stopped = False
    while True:
        ep_t0 = time.perf_counter()
        model.train()

        running, n_raw = 0.0, 0
        for batch in loader:
            img, tof, y = _unpack_batch(batch)
            img, tof, y = _to_device(img, tof, y, device)

            # p_real: [B,1]
            p_real = model(img, tof)
            loss = bce(p_real, y)

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()

            running += float(loss.item()) * int(y.size(0))
            n_raw += int(y.size(0))

        total_ep += 1
        avg_loss = running / max(1, n_raw)

        val_loss = None
        if do_validation and val_dataset is not None and len(val_dataset) > 0:
            val_loss = _eval_raw_bce(model, val_dataset, device, bce=bce, batch_size=batch_size)

        ep_t1 = time.perf_counter()
        ep_str = _epoch_str(total_ep, epochs_local=0, base=print_epoch_base)

        if val_loss is None:
            print(f"[budget/raw_only] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | train_loss={avg_loss:.6f}")
        else:
            print(
                f"[budget/raw_only] epoch {ep_str} | time={ep_t1-ep_t0:.3f}s | "
                f"train_loss={avg_loss:.6f} | val_loss={float(val_loss):.6f}"
            )

        history["epoch"].append(total_ep)
        history["train_loss"].append(avg_loss)
        history["val_loss"].append(val_loss)
        history["coll_loss"].append(None)
        history["samples_raw_per_epoch"].append(int(n_raw))  # qui RAW
        history["samples_replay_per_epoch"].append(0)

        if _maybe_es_step(val_loss, ep_str):
            stopped = True
            break

        # stop per tempo globale
        if (time.perf_counter() - global_t0) >= float(train_time_budget_s):
            break

    if es_enabled and best_state is not None:
        model.load_state_dict(best_state, strict=True)
        history["early_stop"] = {
            "enabled": True,
            "patience": int(patience),
            "best_epoch": int(best_epoch),
            "best_val_loss": float(best_val),
            "stopped_epoch": int(total_ep) if stopped else None,
        }
    else:
        history["early_stop"] = {"enabled": False}

    model.eval()
    return model, total_ep



# =============================================================================
#  ENTRY POINT: run_training
# =============================================================================

def run_training(data_config: DataConfig, global_t0: Optional[float] = None) -> DataConfig:
    """
    Avvia il training usando i parametri e i buffer già pronti dentro data_config.

    PRECONDIZIONI (cosa deve essere già stato fatto prima)
    ------------------------------------------------------
    - setup() deve aver inizializzato:
        data_config.device
        data_config.original_model
        data_config.bce_loss
        data_config.optimizer
    - prepare_training() deve aver creato:
        training_buffer.latent_buffer  (se latents_only=True)
        oppure training_buffer.training_dataset_raw (se latents_only=False)
    - (opzionale) _load_validation_dataset() se validation=true

    OUTPUT
    ------
    Ritorna lo stesso data_config, ma con:
      - data_config.fine_tuned_model = modello dopo training
      - data_config.training_history = dict con loss per epoca (+ early_stop se attivo)
      - data_config.epochs_done = epoche effettivamente eseguite
      - (solo RAW) training_dataset_raw viene liberato (messo a None) a fine training
      - (se validation e save_train_val_loss_csv=True) appende un CSV train_val_loss_per_epoch.csv in outdir
    """
    # Controlli di sicurezza: se manca qualcosa di fondamentale, meglio fallire subito
    if data_config.device is None:
        raise RuntimeError("data_config.device è None. Hai chiamato setup() prima del training?")
    if data_config.original_model is None and data_config.fine_tuned_model is None:
        raise RuntimeError("Nessun modello di partenza in data_config.")
    if data_config.bce_loss is None or data_config.optimizer is None:
        raise RuntimeError("bce_loss/optimizer non inizializzati (chiama setup()).")

    device = data_config.device

    # Se esiste già un modello fine-tuned (es. iterazioni successive), riparti da quello,
    # altrimenti usa l’original_model.
    model = data_config.fine_tuned_model or data_config.original_model
    assert model is not None

    batch_size = int(getattr(data_config, "batch_size", 128) or 128)
    epochs_mode = str(data_config.epochs_mode).strip().lower()   # "fixed" o "budget"
    epochs = int(data_config.epochs)
    train_time_budget_s = float(data_config.train_time_budget_s)

    bce = data_config.bce_loss
    optimizer = data_config.optimizer

    # History: viene riempito durante il training
    history: Dict[str, Any] = {
        "mode": "",
        "epoch": [],
        "train_loss": [],
        "val_loss": [],
        "coll_loss": [],
        "steps_per_epoch": None,
        "samples_raw_per_epoch": [],
        "samples_replay_per_epoch": [],
    }
    data_config.training_history = history

    # Validazione: attiva solo se validation=true e ci sono sample nel validation_buffer
    do_validation = bool(getattr(data_config, "validation", False)) and len(data_config.validation_buffer.items) > 0
    patience = int(getattr(data_config, "patience", 0) or 0)
    save_train_val_loss_csv = bool(getattr(data_config, "save_train_val_loss_csv", True))

    # -------------------------------------------------------------------------
    # BRANCH 1: latents_only
    # -------------------------------------------------------------------------
    if data_config.latents_only:
        buf = data_config.training_buffer.latent_buffer
        if buf is None or len(buf) == 0:
            raise RuntimeError("latents_only=True ma latent_buffer è vuoto o None.")
        if getattr(buf, "Z_all_t", None) is None or getattr(buf, "Y_all_t", None) is None:
            raise RuntimeError("latents_only: buffer non ha Z_all_t/Y_all_t.")

        val_buf = data_config.validation_buffer.latent_buffer if do_validation else None

        print(
            f"[run_training] modalità latents_only, epochs_mode={epochs_mode}, tap={data_config.latent_tap}, buffer_size={len(buf)}"
        )
        if do_validation:
            print(f"[run_training] validation=ON | validation_samples={len(data_config.validation_buffer.items)}")

        model_ft, epochs_done = _train_latents(
            model,
            buffer=buf,
            device=device,
            bce=bce,
            optimizer=optimizer,
            epochs_mode=epochs_mode,
            epochs=epochs,
            batch_size=batch_size,
            latent_tap=data_config.latent_tap,
            train_time_budget_s=train_time_budget_s,
            history=history,
            global_t0=global_t0,
            print_epoch_base=0,
            val_buffer=val_buf,
            do_validation=do_validation,
            patience=patience,
        )

    # -------------------------------------------------------------------------
    # BRANCH 2: raw_only
    # -------------------------------------------------------------------------
    else:
        dataset = getattr(data_config.training_buffer, "training_dataset_raw", None)
        if dataset is None:
            raise RuntimeError("RAW training: training_dataset_raw è None (chiama prepare_training()).")

        # Se validation è on, costruisce un RawPairsDataset anche per validation
        val_ds = None
        if do_validation:
            try:
                from .lr_data import RawPairsDataset
            except Exception:
                from lr_data import RawPairsDataset

            val_triples = [(s.img_path, s.tof_path, int(s.label)) for s in data_config.validation_buffer.items]
            val_ds = RawPairsDataset(val_triples)

        print(f"[run_training] modalità raw_only, epochs_mode={epochs_mode}, dataset size={len(dataset)}")
        if do_validation:
            print(f"[run_training] validation=ON | validation_samples={len(data_config.validation_buffer.items)}")

        model_ft, epochs_done = _train_raw(
            model,
            dataset=dataset,
            device=device,
            bce=bce,
            optimizer=optimizer,
            epochs_mode=epochs_mode,
            epochs=epochs,
            batch_size=batch_size,
            train_time_budget_s=train_time_budget_s,
            history=history,
            global_t0=global_t0,
            print_epoch_base=0,
            val_dataset=val_ds,
            do_validation=do_validation,
            patience=patience,
        )

    # -------------------------------------------------------------------------
    # Salvataggio risultati nel DataConfig
    # -------------------------------------------------------------------------
    model_ft.eval()
    data_config.fine_tuned_model = model_ft
    data_config.training_history = history
    data_config.epochs_done = int(epochs_done)

    # In modalità RAW, libera il dataset (spesso pesante: contiene liste di path, ecc.)
    if not data_config.latents_only:
        data_config.training_buffer.training_dataset_raw = None

    # -------------------------------------------------------------------------
    # Se validation=ON e save_train_val_loss_csv=True, scrive un CSV in append
    # con train/val loss per epoca
    # -------------------------------------------------------------------------
    if do_validation and save_train_val_loss_csv:
        import csv

        outdir = data_config.outdir
        if outdir is None:
            # fallback: usa model_original_root o suo parent
            outdir = (
                data_config.model_original_root
                if data_config.model_original_root.is_dir()
                else data_config.model_original_root.parent
            )
        outdir.mkdir(parents=True, exist_ok=True)

        csv_path = outdir / "train_val_loss_per_epoch.csv"

        # metadati utili per analisi successive
        tap = str(getattr(data_config, "latent_tap", ""))
        data_selection = str(getattr(data_config, "data_selection", ""))
        lr = float(getattr(data_config, "lr", float("nan")))
        weight_decay = float(getattr(data_config, "weight_decay", float("nan")))

        header = ["epoch", "train_loss", "val_loss", "tap", "data_selection", "learning_rate", "weight_decay"]

        # se file già popolato, separa i run con 2 righe vuote
        file_has_content = csv_path.exists() and (csv_path.stat().st_size > 0)

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)

            if file_has_content:
                w.writerow([])
                w.writerow([])

            # header sempre (uno per run)
            w.writerow(header)

            # righe: una per epoca
            for ep, tr, vl in zip(
                data_config.training_history["epoch"],
                data_config.training_history["train_loss"],
                data_config.training_history["val_loss"],
            ):
                w.writerow([
                    int(ep),
                    f"{float(tr):.8f}",
                    "" if vl is None else f"{float(vl):.8f}",
                    tap,
                    data_selection,
                    f"{lr:.8g}",
                    f"{weight_decay:.8g}",
                ])

        print(f"[CSV] loss per epoca APPEND in: {csv_path}")

    # Log finale
    lr = float(getattr(data_config, "lr", float("nan")))
    print("----------------------------------------------------------------")
    print("[run_training] Training completato.")
    print(f"   mode={'latents_only' if data_config.latents_only else 'raw_only'}, epochs_mode={data_config.epochs_mode}, epochs_done={data_config.epochs_done}")
    print(f"learning rate: {lr}")
    print("----------------------------------------------------------------")

    return data_config